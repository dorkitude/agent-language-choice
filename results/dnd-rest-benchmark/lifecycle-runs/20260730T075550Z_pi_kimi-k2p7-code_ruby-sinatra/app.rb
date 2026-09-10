# frozen_string_literal: true

# D&D DM Tools — Sinatra HTTP API.
#
# Route definitions live in this file. Shared helpers (authentication,
# validation, D&D math, storage access, and common response formatting) are
# provided by modules in lib/ and by the `helpers` block below.

require 'sinatra'
require 'json'
require_relative 'lib/storage'
require_relative 'lib/game_logic'
require_relative 'lib/validation'
require_relative 'lib/auth'
require_relative 'lib/maintenance'

set :bind, '127.0.0.1'
set :port, ENV.fetch('PORT', '4567').to_i

Storage.init_schema!

helpers GameLogic
helpers Validation
helpers Auth

helpers do
  # Looks up a combat session by id; halts 404 if it does not exist.
  def find_combat_session!(id)
    session = Storage.load_session(id)
    json_error(404, 'session not found') unless session
    session
  end

  # Parses the request body as JSON; halts 400 on malformed input.
  def parse_json_body
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    json_error(400, 'invalid json')
  end

  # Shapes a combat session record into the public session response. Additional
  # keys (such as +conditions+) can be merged in for specific endpoints.
  def combat_session_response(session, extra = {})
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: session[:order][session[:turn_index]],
      order: session[:order]
    }.merge(extra)
  end

  # Halts with a JSON error body and the application/json content type.
  def json_error(status, message)
    halt status, { 'Content-Type' => 'application/json' }, JSON.dump(error: message)
  end

  # Validates the campaign id and halts 404 unless the campaign exists.
  def require_campaign_exists!(campaign_id)
    validate_campaign_id!(campaign_id)
    json_error(404, 'campaign not found') unless Storage.campaign_exists?(campaign_id)
  end

  # Loads a play campaign or halts 404. Callers must validate the campaign id
  # first if they need a 400 response for an empty/missing id.
  def load_play_campaign!(campaign_id)
    campaign = Storage.load_play_campaign(campaign_id)
    json_error(404, 'campaign not found') unless campaign
    campaign
  end

  # Halts 403 unless the user owns or is a member of the play campaign.
  def require_play_campaign_access!(campaign, username)
    is_owner = campaign[:owner] == username
    is_member = Storage.play_campaign_member_exists?(campaign[:id], username)
    json_error(403, 'forbidden') unless is_owner || is_member
  end

  # Halts 403 unless the user owns the play campaign.
  def require_play_campaign_owner!(campaign, username)
    json_error(403, 'forbidden') unless campaign[:owner] == username
  end

  # Returns the audit-trail role for an authenticated user in a play campaign.
  def audit_role_for(campaign, username)
    campaign[:owner] == username ? 'DM' : 'player'
  end

  # Returns true when the user may post narrations for a play campaign,
  # either as the campaign owner or as an active delegate with the narrate power.
  def can_narrate?(campaign, username)
    return true if campaign[:owner] == username

    delegation = Storage.load_active_delegation(campaign[:id], username)
    delegation && delegation[:powers].include?('narrate')
  end

  # Returns the actor whose turn it is for a play campaign. When a turn queue
  # exists, the phase determines whether it is the DM's step or a player's step;
  # player steps cycle every other turn number because each player turn is
  # followed by a DM resolution step. During exploration the stored current_actor
  # is used so that combat can return the narrative to the DM. Otherwise the
  # stored current_actor is used (legacy/lobby mode).
  def current_actor_for(campaign, turn_number = nil)
    queue = campaign[:queue] || []
    return campaign[:current_actor] if queue.empty?

    phase = campaign[:phase].to_s
    return campaign[:current_actor] if phase == 'exploration'
    return 'dm' if phase == 'dm'

    players = queue.reject { |actor| actor == 'dm' }
    return 'dm' if players.empty?

    turn = turn_number.nil? ? campaign[:turn_number].to_i : turn_number.to_i
    players[(turn / 2) % players.length]
  end

  # Maps an actor name to the play-campaign phase label.
  def phase_for(actor)
    actor == 'dm' ? 'dm' : 'player'
  end

  # Advances a play campaign from a DM resolution to the next player turn.
  # Returns the next actor's username (or 'dm' when there are no players).
  def advance_play_campaign_turn!(campaign, current_turn_number)
    next_turn_number = current_turn_number.to_i + 1
    queue = campaign[:queue] || []
    players = queue.reject { |actor| actor == 'dm' }
    next_actor = players.empty? ? 'dm' : players[(next_turn_number / 2) % players.length]
    Storage.update_play_campaign_turn(campaign[:id], next_actor, 'player', next_turn_number)
    next_actor
  end

  # Advances a play campaign from a player action to the DM's resolution phase
  # and increments the turn number. Returns 'dm'.
  def advance_to_dm_phase_and_turn!(campaign)
    next_turn_number = campaign[:turn_number].to_i + 1
    Storage.update_play_campaign_turn(campaign[:id], 'dm', 'dm', next_turn_number)
    'dm'
  end

  # Advances a play campaign from a player travel turn to the DM's resolution
  # phase without incrementing the turn number. Returns 'dm'.
  def advance_to_dm_phase!(campaign)
    Storage.update_play_campaign_turn(campaign[:id], 'dm', 'dm', campaign[:turn_number].to_i)
    'dm'
  end

  # Computes the deterministic initiative order for a campaign encounter from
  # its monster roster and bound party combatants. Highest initiative wins;
  # ties are broken by combatant name.
  def encounter_order(monsters, combatants)
    order = []
    monsters.each do |m|
      order << { name: m[:name], kind: 'monster', initiative: m[:initiative], internal_id: m[:monster_id] }
    end
    combatants.each do |c|
      next unless c.is_a?(Hash)

      order << {
        name: c['name'] || c[:name],
        kind: 'player',
        initiative: c['initiative'] || c[:initiative],
        member: c['member'] || c[:member]
      }
    end
    order.sort! do |a, b|
      if a[:initiative] != b[:initiative]
        b[:initiative] <=> a[:initiative]
      else
        a[:name].to_s <=> b[:name].to_s
      end
    end
    order
  end

  # Returns the stored initiative order for an encounter, computing and caching
  # it from the roster when no stored order exists yet.
  def encounter_order_for(campaign_id, encounter_id, monsters, combatants)
    stored = Storage.load_encounter_order(campaign_id, encounter_id)
    if stored && !stored.empty?
      stored
    else
      order = encounter_order(monsters, combatants)
      Storage.save_encounter_order(campaign_id, encounter_id, order)
      order
    end
  end

  # Recomputes and stores the initiative order after the encounter roster changes.
  def refresh_encounter_order!(campaign_id, encounter_id, monsters, combatants)
    order = encounter_order(monsters, combatants)
    Storage.save_encounter_order(campaign_id, encounter_id, order)
    order
  end

  # Reloads the encounter roster and recomputes the stored initiative order.
  # Used by roster mutation routes so they do not duplicate the reload logic.
  def recompute_encounter_order!(campaign_id, encounter_id)
    encounter = Storage.load_encounter(campaign_id, encounter_id)
    monsters = Storage.load_encounter_monsters(campaign_id, encounter_id)
    refresh_encounter_order!(campaign_id, encounter_id, monsters, encounter[:combatants] || [])
  end

  # Public active-combatant shape for encounter turn endpoints.
  def encounter_active(combatant)
    return nil unless combatant

    { name: combatant[:name], kind: combatant[:kind], initiative: combatant[:initiative] }
  end

  # Returns the condition-storage key for an entry in the encounter order.
  # Monsters are keyed by monster_id; bound party members by username.
  def condition_key_for(combatant)
    return nil unless combatant

    combatant[:kind] == 'monster' ? combatant[:internal_id] : combatant[:member]
  end

  # Returns true when +target+ identifies a monster or a bound party member
  # in the encounter.
  def valid_encounter_target?(encounter, monsters, target)
    monsters.any? { |m| m[:monster_id] == target } ||
      (encounter[:combatants] || []).any? { |c| (c[:member] || c['member']) == target }
  end

  # Loads a play campaign and one of its encounters, enforcing access or
  # ownership. Halts with the same precedence as the original routes and returns
  # [campaign, encounter] so callers can perform endpoint-specific work.
  def load_play_encounter!(campaign_id, enc_id, username, require_owner: false)
    campaign = load_play_campaign!(campaign_id)
    require_play_campaign_access!(campaign, username)
    require_play_campaign_owner!(campaign, username) if require_owner

    encounter = Storage.load_encounter(campaign_id, enc_id)
    json_error(404, 'encounter not found') unless encounter

    [campaign, encounter]
  end

  # Decrements remaining rounds for conditions on the newly-active combatant
  # and removes expired conditions at the start of that combatant's turn.
  def apply_condition_decay_for_active!(campaign_id, encounter_id, active)
    key = condition_key_for(active)
    return unless key

    conditions = Storage.load_encounter_conditions(campaign_id, encounter_id)
    return unless conditions.key?(key)

    conditions[key].each do |cond|
      if cond.key?('remaining_rounds')
        cond['remaining_rounds'] = cond['remaining_rounds'].to_i - 1
      elsif cond.key?(:remaining_rounds)
        cond[:remaining_rounds] = cond[:remaining_rounds].to_i - 1
      end
    end
    conditions[key].reject! do |cond|
      rounds = cond.key?('remaining_rounds') ? cond['remaining_rounds'] : cond[:remaining_rounds]
      rounds.to_i <= 0
    end
    conditions.delete(key) if conditions[key].empty?

    Storage.save_encounter_conditions(campaign_id, encounter_id, conditions)
  end

  # Computes the readiness/risk signal flags for a regular campaign. Returns the
  # signals hash and the count of currently active quests.
  def campaign_readiness_signals(campaign_id, campaign)
    open_quests = Storage.campaign_quests(campaign_id).count { |q| q[:status] == 'active' }
    signals = {
      has_dm: campaign && !campaign[:dm].to_s.empty?,
      has_characters: Storage.campaign_characters_count(campaign_id) > 0,
      has_next_session: !Storage.next_campaign_session(campaign_id).nil?,
      has_active_quest: open_quests > 0
    }
    [signals, open_quests]
  end

  # Legacy deadline value for a play campaign turn. Wall-clock time is not
  # used in this benchmark; the deadline is derived deterministically from the
  # current turn number.
  def play_turn_deadline(turn_number)
    return 0 if turn_number.nil?
    turn_number + 3
  end

  # Logical integer deadline for a play campaign turn. The deadline is the
  # logical turn number itself so a fresh turn is never overdue.
  def play_logical_deadline(turn_number)
    return 0 if turn_number.nil?
    turn_number
  end

  # Returns the public settlement shape. For DM responses, the full
  # +discovered_by+ list is included. For player responses, the list is
  # limited to the player's own character id and only when that character has
  # discovered the settlement.
  def settlement_response(settlement, character_id = nil)
    discovered_by = settlement[:discovered_by]
    if character_id
      discovered_by = discovered_by.include?(character_id) ? [character_id] : []
    end

    {
      settlement_id: settlement[:settlement_id],
      name: settlement[:name],
      services: settlement[:services],
      availability: settlement[:availability],
      discovered_by: discovered_by
    }
  end

  # Returns the public shop shape.
  def shop_response(shop)
    {
      shop_id: shop[:shop_id],
      name: shop[:name],
      stock: shop[:stock],
      buy_price: shop[:buy_price],
      sell_price: shop[:sell_price]
    }
  end

  # Returns the public content record shape.
  def content_response(content)
    {
      content_id: content[:content_id],
      kind: content[:kind],
      text: content[:text],
      tags: content[:tags]
    }
  end

  # Builds an encounter summary for a campaign encounter. Looks up each monster
  # slug in the compendium and halts 404 if any slug is missing.
  def encounter_calculation(party, monster_slugs)
    counts = Hash.new(0)
    monster_slugs.each { |slug| counts[slug] += 1 }

    monsters = []
    counts.each do |slug, count|
      monster = Storage.load_monster(slug)
      json_error(404, 'monster not found') unless monster
      monsters << { cr: monster[:cr], count: count }
    end

    thresholds = encounter_thresholds(party)
    base_xp, monster_count = encounter_base_xp(monsters)
    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).to_i
    difficulty = encounter_difficulty(adjusted_xp, thresholds)
    recommendation = recommendation_for(difficulty)

    [base_xp, adjusted_xp, difficulty, monster_count, recommendation]
  end
end


# Domain route groups loaded in precedence order.
require_relative 'lib/routes/core'
require_relative 'lib/routes/characters'
require_relative 'lib/routes/combat_sessions'
require_relative 'lib/routes/auth'
require_relative 'lib/routes/storage'
require_relative 'lib/routes/compendium'
require_relative 'lib/routes/campaigns'
require_relative 'lib/routes/phb'
require_relative 'lib/routes/dm_tools'
require_relative 'lib/routes/downtime'
require_relative 'lib/routes/sessions'
require_relative 'lib/routes/play_lobby'
require_relative 'lib/routes/play_invitations'
require_relative 'lib/routes/play_delegations'
require_relative 'lib/routes/play_audit'
require_relative 'lib/routes/play_projections'
require_relative 'lib/routes/play_idempotent_events'
require_relative 'lib/routes/play_safe_turns'
require_relative 'lib/routes/play_turns'
require_relative 'lib/routes/play_document'
require_relative 'lib/routes/play_exports'
require_relative 'lib/routes/play_imports'
require_relative 'lib/routes/play_migrations'
require_relative 'lib/routes/play_backups'
require_relative 'lib/routes/play_scenes'
require_relative 'lib/routes/play_content'
require_relative 'lib/routes/play_notes'
require_relative 'lib/routes/play_locations'
require_relative 'lib/routes/play_travel_rest'
require_relative 'lib/routes/play_encounters'
require_relative 'lib/routes/play_characters'
require_relative 'lib/routes/play_downtime'
require_relative 'lib/routes/play_loot'
require_relative 'lib/routes/play_transactional_transfers'
require_relative 'lib/routes/play_npcs'
require_relative 'lib/routes/play_factions'
require_relative 'lib/routes/play_relationships'
require_relative 'lib/routes/play_clues'
require_relative 'lib/routes/play_quests'
require_relative 'lib/routes/play_world_events'
require_relative 'lib/routes/play_calendar'
require_relative 'lib/routes/play_settlements'
require_relative 'lib/routes/play_shops'
require_relative 'lib/routes/play_recipes'
require_relative 'lib/routes/play_search_records'
require_relative 'lib/routes/play_rate_events'
require_relative 'lib/routes/play_metrics'
require_relative 'lib/routes/play_replay'
require_relative 'lib/routes/play_rng_ledger'
require_relative 'lib/routes/play_moderation'
require_relative 'lib/routes/play_safety_boundaries'
require_relative 'lib/routes/play_fixture_seeding'
require_relative 'lib/routes/play_service_mode'
require_relative 'lib/routes/play_spectators'
require_relative 'lib/routes/play_feed_events'
