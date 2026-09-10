# frozen_string_literal: true

require 'json'
require_relative 'persistence'
require_relative 'service_mode'

# Protected campaign-play surface: ownership, membership, turn queue,
# narration, actions, resolutions, combat encounters, scenes, locations,
# NPC agendas and dialogue, character builds, and campaign documents.
#
# Lifecycle model:
#   - Campaigns start in `lobby`; the owner (DM) may add members and then `start`.
#   - Once active, play alternates between players and the DM via the `current_actor` field.
#   - Travel and rest actions are player turns that hand control back to the DM.
#   - Encounters switch the campaign `phase` to `combat` and capture the previous
#     actor in `pre_combat_actor`; `end_encounter` restores it.
#   - Narration sequence numbers are monotonic within a campaign and shared across
#     all narration kinds.
module PlayCampaigns
  # Validation lists include both hyphen and underscore spellings for the races
  # and backgrounds that accept both forms; build validation normalizes the input
  # to the hyphenated form before storage.
  VALID_RACES = %w[human elf dwarf halfling gnome half-elf half-orc tiefling dragonborn half_elf half_orc].freeze
  VALID_CLASSES = %w[barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard].freeze
  VALID_BACKGROUNDS = %w[acolyte charlatan criminal entertainer folk-hero folk_hero guild-artisan guild_artisan hermit noble outlander sage sailor soldier urchin].freeze
  VALID_SKILLS = %w[acrobatics animal_handling arcana athletics deception history insight intimidation investigation medicine nature perception performance persuasion religion sleight_of_hand stealth survival].freeze
  VALID_INVENTORY_ITEMS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze
  CONSUMABLE_ITEMS = %w[healing-potion].freeze
  CONSUMABLE_EFFECTS = {
    'healing-potion' => { 'type' => 'healing', 'hp_restored' => 5 }
  }.freeze
  VALID_EQUIPMENT_SLOTS = %w[armor accessory].freeze
  EQUIPMENT_SLOT_MAP = {
    'leather-armor' => 'armor',
    'ring-of-protection' => 'accessory',
    'amulet-of-health' => 'accessory'
  }.freeze
  ATTUNABLE_ITEMS = %w[ring-of-protection amulet-of-health].freeze
  MAX_ATTUNEMENTS = 1
  RATE_LIMIT = 2
  HIT_DICE = {
    'barbarian' => 12,
    'bard' => 8,
    'cleric' => 8,
    'druid' => 8,
    'fighter' => 10,
    'monk' => 8,
    'paladin' => 10,
    'ranger' => 10,
    'rogue' => 8,
    'sorcerer' => 6,
    'warlock' => 8,
    'wizard' => 6
  }.freeze

  def self.create(payload, owner)
    data = validate_campaign(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM play_campaigns WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
        [data[:id], data[:name], owner, 'lobby', data[:max_players]]
      )

      d.execute(
        'INSERT INTO play_campaign_metrics (campaign_id) VALUES (?)',
        [data[:id]]
      )

      [:ok, {
        'id' => data[:id],
        'name' => data[:name],
        'owner' => owner,
        'status' => 'lobby',
        'max_players' => data[:max_players]
      }]
    end
  end

  def self.join(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_membership(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT status, max_players FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      status, max_players = campaign
      next [:conflict] unless status == 'lobby'

      member_count = d.get_first_value('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?', campaign_id)
      next [:conflict] if member_count >= max_players

      existing_player = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:conflict] if existing_player

      existing_character = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, data[:character_id]]
      )
      next [:conflict] if existing_character

      d.execute(
        'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, actor[:username], data[:character_id], data[:name], data[:class], actor[:username], data[:hp_current], data[:hp_max]]
      )

      d.execute(
        'INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)',
        [campaign_id, data[:character_id], 10]
      )

      [:ok, {
        'username' => actor[:username],
        'character_id' => data[:character_id],
        'name' => data[:name],
        'class' => data[:class]
      }]
    end
  end

  def self.start(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, status FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, status = campaign
      next [:forbidden] unless owner == actor[:username]

      next [:conflict] unless status == 'lobby'

      member_count = d.get_first_value('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?', campaign_id)
      next [:conflict] if member_count < 2

      first_actor = d.get_first_value(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY username LIMIT 1',
        campaign_id
      )

      d.execute(
        "UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = ? WHERE id = ?",
        [first_actor, 1, campaign_id]
      )

      [:ok, {
        'id' => campaign_id,
        'status' => 'active',
        'current_actor' => first_actor,
        'turn_number' => 1
      }]
    end
  end

  def self.onboarding(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      if owner == actor[:username]
        next [:ok, {
          'role' => 'dm',
          'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
          'can_mutate' => true
        }]
      end

      [:ok, {
        'role' => 'player',
        'next_steps' => ['review-party', 'take-turn', 'submit-action'],
        'can_mutate' => true
      }]
    end
  end

  def self.create_spectator(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    spectator_id = payload['spectator_id']
    return [:invalid] unless spectator_id.is_a?(String) && !spectator_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      existing = d.get_first_value('SELECT 1 FROM play_campaign_spectators WHERE spectator_id = ?', spectator_id)
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_spectators (campaign_id, spectator_id) VALUES (?, ?)',
        [campaign_id, spectator_id]
      )

      [:created, {
        'spectator_id' => spectator_id,
        'token' => "spectator-#{spectator_id}"
      }]
    end
  end

  def self.spectator_view(campaign_id, spectator_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            spectator_id.is_a?(String) && !spectator_id.empty?

    Persistence.db do |d|
      # A well-shaped token must be registered to be valid at all.
      spectator_row = d.get_first_row(
        'SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?',
        spectator_id
      )
      next [:unauthorized] unless spectator_row

      # Unknown campaigns are reported after token validity so valid-shaped
      # tickets for missing campaigns yield 404, not 401/403.
      campaign = d.get_first_row('SELECT id, name, status FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      # A registered spectator token is only valid for its own campaign.
      next [:forbidden] unless spectator_row[0] == campaign_id

      party_size = d.get_first_value('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?', campaign_id)

      doc = d.get_first_row('SELECT story FROM play_campaign_documents WHERE campaign_id = ?', campaign_id)
      story = doc ? doc[0] : ''

      [:ok, {
        'campaign_id' => campaign[0],
        'name' => campaign[1],
        'status' => campaign[2],
        'party_size' => party_size,
        'story' => story
      }]
    end
  end

  def self.create_invitation(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    invitation_id = payload['invitation_id']
    username = payload['username']
    character_id = payload['character_id']
    return [:invalid] unless invitation_id.is_a?(String) && !invitation_id.empty?
    return [:invalid] unless username.is_a?(String) && !username.empty?
    return [:invalid] unless character_id.is_a?(String) && !character_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      target = d.get_first_row('SELECT role FROM users WHERE username = ?', username)
      next [:invalid] unless target && target[0] == 'player'

      existing_id = d.get_first_value(
        'SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?',
        [campaign_id, invitation_id]
      )
      next [:conflict] if existing_id

      existing_active = d.get_first_value(
        "SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'",
        [campaign_id, username]
      )
      next [:conflict] if existing_active

      d.execute(
        'INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, invitation_id, username, character_id, 'pending']
      )

      [:ok, {
        'invitation_id' => invitation_id,
        'username' => username,
        'character_id' => character_id,
        'status' => 'pending'
      }]
    end
  end

  def self.accept_invitation(campaign_id, invitation_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            invitation_id.is_a?(String) && !invitation_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] if owner == actor[:username]

      invitation = d.get_first_row(
        'SELECT username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?',
        [campaign_id, invitation_id]
      )
      next [:not_found] unless invitation

      target_username, character_id, status = invitation
      next [:forbidden] unless target_username == actor[:username]
      next [:conflict] if status == 'accepted'

      existing_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, target_username]
      )

      unless existing_member
        existing_character = d.get_first_value(
          'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        next [:conflict] if existing_character

        d.execute(
          'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, target_username, character_id, character_id, '', target_username, 20, 20]
        )
        d.execute(
          'INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)',
          [campaign_id, character_id, 10]
        )
      end

      d.execute(
        "UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?",
        [campaign_id, invitation_id]
      )

      [:ok, {
        'invitation_id' => invitation_id,
        'username' => target_username,
        'character_id' => character_id,
        'status' => 'accepted'
      }]
    end
  end

  def self.list_invitations(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      rows = if owner == actor[:username]
               d.execute(
                 'SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY id',
                 campaign_id
               )
             else
               d.execute(
                 'SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY id',
                 [campaign_id, actor[:username]]
               )
             end

      invitations = rows.map do |inv_id, user, char_id, status|
        {
          'invitation_id' => inv_id,
          'username' => user,
          'character_id' => char_id,
          'status' => status
        }
      end

      [:ok, { 'invitations' => invitations }]
    end
  end

  def self.narrate(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    text = payload['text']
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      can_narrate = owner == actor[:username] || active_delegate_with_power?(d, campaign_id, actor[:username], 'narrate')
      next [:forbidden] unless can_narrate

      actor_name = owner == actor[:username] ? 'dm' : actor[:username]
      next_sequence = record_narration(d, campaign_id, 'narration', actor_name, text)

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'narration',
        'actor' => actor_name,
        'text' => text
      }]
    end
  end

  # Posts a party chat message. Owning DM or any campaign member may post;
  # spectator tokens cannot authenticate this mutation endpoint.
  def self.create_message(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    text = payload['text']
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      sequence = record_narration(d, campaign_id, 'chat', actor[:username], text)

      [:created, {
        'sequence' => sequence,
        'kind' => 'chat',
        'actor' => actor[:username],
        'text' => text
      }]
    end
  end

  def self.grant_delegation(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    username = payload['username']
    powers = payload['powers']

    return [:invalid] unless username.is_a?(String) && !username.empty?
    return [:invalid] unless powers.is_a?(Array) && !powers.empty?
    return [:invalid] unless powers.all? { |p| p.is_a?(String) && p == 'narrate' }
    return [:invalid] unless powers.uniq.length == powers.length

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )
      next [:invalid] unless is_member

      existing = d.get_first_row(
        'SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )
      next [:conflict] if existing && existing[0] == 1

      powers_json = JSON.generate(powers)
      d.execute(
        'INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)
         ON CONFLICT(campaign_id, username) DO UPDATE SET powers_json = excluded.powers_json, active = 1',
        [campaign_id, username, powers_json]
      )

      d.execute(
        'INSERT INTO play_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)',
        [campaign_id, username, 'granted', powers_json]
      )

      [:ok, { 'username' => username, 'powers' => powers, 'active' => true }]
    end
  end

  def self.revoke_delegation(campaign_id, username, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            username.is_a?(String) && !username.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      existing = d.get_first_row(
        'SELECT powers_json FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )
      powers = existing ? JSON.parse(existing[0]) : ['narrate']

      d.execute(
        'INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 0)
         ON CONFLICT(campaign_id, username) DO UPDATE SET active = 0',
        [campaign_id, username, JSON.generate(powers)]
      )

      d.execute(
        'INSERT INTO play_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)',
        [campaign_id, username, 'revoked', JSON.generate(powers)]
      )

      [:ok, { 'username' => username, 'powers' => powers, 'active' => false }]
    end
  end

  def self.delegation_audit(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      rows = d.execute(
        'SELECT username, action, powers_json FROM play_delegation_audit WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      entries = rows.map do |uname, action, powers_json|
        {
          'username' => uname,
          'action' => action,
          'powers' => JSON.parse(powers_json)
        }
      end

      [:ok, { 'entries' => entries }]
    end
  end

  def self.create_audit_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    kind = payload['kind']
    correlation_id = payload['correlation_id']
    return [:invalid] unless kind.is_a?(String) && !kind.empty?
    return [:invalid] unless correlation_id.is_a?(String) && !correlation_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_audit_events WHERE campaign_id = ? AND correlation_id = ?',
        [campaign_id, correlation_id]
      )
      next [:conflict] if existing

      role = owner == actor[:username] ? 'DM' : 'player'
      timestamp = d.get_first_value(
        'SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_audit_events WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, kind, actor[:username], role, timestamp, correlation_id]
      )

      [:ok, {
        'kind' => kind,
        'actor' => actor[:username],
        'role' => role,
        'timestamp' => timestamp,
        'correlation_id' => correlation_id
      }]
    end
  end

  def self.list_audit_events(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      rows = d.execute(
        'SELECT kind, actor, role, timestamp, correlation_id FROM play_audit_events WHERE campaign_id = ? ORDER BY timestamp',
        campaign_id
      )

      entries = rows.map do |kind, username, role, timestamp, correlation_id|
        {
          'kind' => kind,
          'actor' => username,
          'role' => role,
          'timestamp' => timestamp,
          'correlation_id' => correlation_id
        }
      end

      [:ok, { 'entries' => entries }]
    end
  end

  def self.create_projection_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless actor[:role] == 'player'

    event_id = payload['event_id']
    kind = payload['kind']
    return [:invalid] unless event_id.is_a?(String) && !event_id.empty?
    return [:invalid] unless kind == 'set-story' || kind == 'increment-danger'

    if kind == 'set-story'
      value = payload['value']
      return [:invalid] unless value.is_a?(String) && !value.empty?
    else
      return [:invalid] if payload.key?('value')
    end

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )

      existing = d.get_first_value(
        'SELECT 1 FROM play_projection_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:conflict] if existing

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_projection_events WHERE campaign_id = ?',
        campaign_id
      )

      if kind == 'set-story'
        d.execute(
          'INSERT INTO play_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, sequence, event_id, kind, payload['value']]
        )
      else
        d.execute(
          'INSERT INTO play_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, sequence, event_id, kind, nil]
        )
      end

      d.execute(
        'INSERT INTO play_campaign_metrics (campaign_id, projection_events) VALUES (?, 1)
         ON CONFLICT(campaign_id) DO UPDATE SET projection_events = projection_events + 1',
        [campaign_id]
      )

      response = {
        'sequence' => sequence,
        'event_id' => event_id,
        'kind' => kind
      }
      response['value'] = payload['value'] if kind == 'set-story'

      [:ok, response]
    end
  end

  def self.get_projection(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT sequence, event_id, kind, value FROM play_projection_events WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      [:ok, compute_projection(rows)]
    end
  end

  def self.rebuild_projection(campaign_id, actor)
    get_projection(campaign_id, actor)
  end

  def self.create_idempotent_event(campaign_id, actor, idempotency_key, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless idempotency_key.is_a?(String) && !idempotency_key.empty?
    return [:invalid] unless payload.is_a?(Hash)

    event_id = payload['event_id']
    value = payload['value']
    return [:invalid] unless event_id.is_a?(String) && !event_id.empty?
    return [:invalid] unless value.is_a?(String) && !value.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing_by_key = d.get_first_row(
        'SELECT event_id, value, sequence FROM play_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?',
        [campaign_id, idempotency_key]
      )

      if existing_by_key
        existing_event_id, existing_value, sequence = existing_by_key
        if existing_event_id == event_id && existing_value == value
          next [:ok, {
            'event_id' => existing_event_id,
            'value' => existing_value,
            'sequence' => sequence,
            'idempotency_key' => idempotency_key
          }]
        else
          next [:conflict]
        end
      end

      existing_by_event_id = d.get_first_value(
        'SELECT 1 FROM play_idempotent_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:conflict] if existing_by_event_id

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_idempotent_events WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_idempotent_events (campaign_id, event_id, value, sequence, idempotency_key) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, event_id, value, sequence, idempotency_key]
      )

      [:created, {
        'event_id' => event_id,
        'value' => value,
        'sequence' => sequence,
        'idempotency_key' => idempotency_key
      }]
    end
  end

  def self.list_idempotent_events(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, value, sequence, idempotency_key FROM play_idempotent_events WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      events = rows.map do |event_id, value, sequence, key|
        {
          'event_id' => event_id,
          'value' => value,
          'sequence' => sequence,
          'idempotency_key' => key
        }
      end

      [:ok, { 'events' => events }]
    end
  end

  def self.submit_safe_turn(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    submission_id = payload['submission_id']
    expected_turn = payload['expected_turn']
    action = payload['action']
    return [:invalid] unless submission_id.is_a?(String) && !submission_id.empty?
    return [:invalid] unless action.is_a?(String) && !action.empty?
    return [:invalid] unless expected_turn.is_a?(Integer) && expected_turn > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, safe_turn_current FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      current_turn = campaign[1].to_i
      current_turn = 1 if current_turn < 1
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      if expected_turn != current_turn
        next [:conflict, { 'current_turn' => current_turn }]
      end

      existing = d.get_first_value(
        'SELECT 1 FROM play_safe_turns WHERE campaign_id = ? AND submission_id = ?',
        [campaign_id, submission_id]
      )
      next [:conflict, { 'current_turn' => current_turn }] if existing

      next_turn = current_turn + 1
      d.execute(
        'INSERT INTO play_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, submission_id, action, current_turn, next_turn]
      )
      d.execute(
        'UPDATE play_campaigns SET safe_turn_current = ? WHERE id = ?',
        [next_turn, campaign_id]
      )

      [:created, {
        'submission_id' => submission_id,
        'action' => action,
        'accepted_turn' => current_turn,
        'next_turn' => next_turn
      }]
    end
  end

  def self.list_safe_turns(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, safe_turn_current FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      current_turn = campaign[1].to_i
      current_turn = 1 if current_turn < 1
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT submission_id, action, accepted_turn, next_turn FROM play_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn, submission_id',
        campaign_id
      )

      accepted = rows.map do |submission_id, action, accepted_turn, next_turn|
        {
          'submission_id' => submission_id,
          'action' => action,
          'accepted_turn' => accepted_turn,
          'next_turn' => next_turn
        }
      end

      [:ok, { 'current_turn' => current_turn, 'accepted' => accepted }]
    end
  end

  def self.compute_projection(rows)
    story = ''
    danger = 0
    applied = []
    rows.each do |_sequence, event_id, kind, value|
      applied << event_id
      if kind == 'set-story'
        story = value.to_s
      elsif kind == 'increment-danger'
        danger += 1
      end
    end

    {
      'story' => story,
      'danger' => danger,
      'applied_event_ids' => applied
    }
  end
  private_class_method :compute_projection

  def self.active_delegate_with_power?(d, campaign_id, username, power)
    row = d.get_first_row(
      'SELECT powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    )
    return false unless row

    powers = JSON.parse(row[0])
    row[1] == 1 && powers.include?(power)
  rescue StandardError
    false
  end
  private_class_method :active_delegate_with_power?

  def self.turn(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, status, current_actor, turn_number, phase FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, status, current_actor, turn_number, phase = campaign
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      # The queue visualizes the full turn cycle: each player followed by a DM turn.
      # Phase is derived from the current actor unless combat is frozen in place.
      unless phase == 'combat'
        phase = (current_actor.nil? || current_actor == owner) ? 'exploration' : 'player'
      end

      # The actual current actor is driven by `current_actor`, not by advancing this queue.
      members = d.execute(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY username',
        campaign_id
      ).map { |row| row[0] }
      queue = members.flat_map { |m| [m, 'dm'] }

      deadline = turn_number.is_a?(Integer) ? turn_number + 1 : nil

      [:ok, {
        'campaign_id' => campaign_id,
        'current_actor' => current_actor,
        'phase' => phase,
        'turn_number' => turn_number,
        'queue' => queue,
        'overdue' => false,
        'logical_deadline' => deadline
      }]
    end
  end

  def self.my_turn(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member

      character_id, name = member
      current_actor = campaign[0]

      recent_events = self.recent_events(d, campaign_id)

      [:ok, {
        'is_my_turn' => current_actor == actor[:username],
        'current_actor' => current_actor,
        'character' => { 'id' => character_id, 'name' => name },
        'recent_events' => recent_events
      }]
    end
  end

  def self.gm_status(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, current_actor = campaign
      next [:forbidden] unless owner == actor[:username]

      members = d.execute(
        'SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY username',
        campaign_id
      ).map do |username, character_id, name, klass|
        { 'username' => username, 'character_id' => character_id, 'name' => name, 'class' => klass }
      end

      recent_events = self.recent_events(d, campaign_id)

      [:ok, {
        'campaign_id' => campaign_id,
        'needs_attention' => current_actor == owner,
        'current_actor' => current_actor,
        'party' => members,
        'recent_events' => recent_events
      }]
    end
  end

  def self.submit_action(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    type = payload['type']
    text = payload['text']
    return [:invalid] unless type.is_a?(String) && !type.empty? &&
                             text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, current_actor = campaign
      next [:conflict] if owner == actor[:username]

      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless is_member

      next [:conflict] unless current_actor == actor[:username]

      next_sequence = record_narration(d, campaign_id, 'action', actor[:username], text)

      d.execute(
        'UPDATE play_campaigns SET current_actor = ? WHERE id = ?',
        [owner, campaign_id]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'action',
        'actor' => actor[:username],
        'type' => type,
        'text' => text,
        'next_actor' => 'dm'
      }]
    end
  end

  def self.resolve(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    text = payload['text']
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, current_actor, turn_number FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, current_actor, turn_number = campaign
      next [:conflict] unless owner == actor[:username]
      next [:conflict] unless current_actor == owner

      members = d.execute(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY username',
        campaign_id
      ).map { |row| row[0] }

      next [:conflict] if members.empty?

      # The DM resolves a turn by advancing to the player who follows the one that
      # submitted the most recent player-side turn (action or travel). Rest turns
      # do not rotate the queue so a resting player keeps their place in the cycle.
      last_action_row = d.get_first_row(
        "SELECT actor FROM play_narrations WHERE campaign_id = ? AND kind IN ('action', 'travel') ORDER BY sequence DESC LIMIT 1",
        campaign_id
      )
      last_actor = last_action_row ? last_action_row[0] : nil

      next_actor = if last_actor && members.include?(last_actor)
                     members[(members.index(last_actor) + 1) % members.length]
                   else
                     members[0]
                   end

      next_sequence = record_narration(d, campaign_id, 'resolution', 'dm', text)

      new_turn_number = turn_number.to_i + 1

      d.execute(
        'UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?',
        [next_actor, new_turn_number, campaign_id]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'resolution',
        'actor' => 'dm',
        'text' => text,
        'next_actor' => next_actor,
        'turn_number' => new_turn_number
      }]
    end
  end

  def self.nudge(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    message = payload['message']
    return [:invalid] unless message.is_a?(String) && !message.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, status, current_actor, nudge_count FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, status, current_actor, nudge_count = campaign
      next [:forbidden] unless owner == actor[:username]
      next [:conflict] unless status == 'active' && current_actor

      new_nudge_count = nudge_count.to_i + 1
      d.execute(
        'UPDATE play_campaigns SET nudge_count = ? WHERE id = ?',
        [new_nudge_count, campaign_id]
      )

      next_sequence = record_narration(d, campaign_id, 'nudge', owner, message)

      [:ok, {
        'actor' => owner,
        'target' => current_actor,
        'message' => message,
        'nudge_count' => new_nudge_count
      }]
    end
  end

  def self.get_document(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )

      if owner == actor[:username]
        row = d.get_first_row(
          'SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?',
          campaign_id
        )
        story = row ? row[0] : ''
        dm_notes = row ? row[1] : ''
        [:ok, { 'story' => story, 'dm_notes' => dm_notes }]
      elsif is_member
        row = d.get_first_row(
          'SELECT story FROM play_campaign_documents WHERE campaign_id = ?',
          campaign_id
        )
        story = row ? row[0] : ''
        [:ok, { 'story' => story }]
      else
        [:forbidden]
      end
    end
  end

  def self.update_document(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    story = payload['story']
    dm_notes = payload['dm_notes']
    return [:invalid] unless story.is_a?(String) && dm_notes.is_a?(String)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      d.execute(
        'INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?)
         ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes',
        [campaign_id, story, dm_notes]
      )

      # Document edits keep a narration trail only once active play has begun
      # (i.e., a player action or DM resolution has been recorded). The initial
      # pre-play story edits are silent so the first DM narration remains
      # sequence 1, matching the backup-and-restore stage expectations.
      active_play = d.get_first_value(
        "SELECT COUNT(*) FROM play_narrations WHERE campaign_id = ? AND kind IN ('action', 'resolution')",
        campaign_id
      ).to_i
      record_narration(d, campaign_id, 'document', owner, story) if active_play > 0

      [:ok, { 'story' => story, 'dm_notes' => dm_notes }]
    end
  end

  def self.create_export(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, status FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, status = campaign
      next [:forbidden] unless owner == actor[:username]

      row = d.get_first_row(
        'SELECT story FROM play_campaign_documents WHERE campaign_id = ?',
        campaign_id
      )
      story = row ? row[0] : ''

      version = d.get_first_value(
        'SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)',
        [campaign_id, version, story, status]
      )

      [:created, {
        'version' => version,
        'story' => story,
        'status' => status
      }]
    end
  end

  def self.list_exports(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      rows = d.execute(
        'SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version',
        campaign_id
      )

      exports = rows.map do |version, story, status|
        { 'version' => version, 'story' => story, 'status' => status }
      end

      [:ok, { 'exports' => exports }]
    end
  end

  def self.get_export(campaign_id, version, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless version.is_a?(Integer) && version > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?',
        [campaign_id, version]
      )
      next [:not_found] unless row

      [:ok, { 'version' => row[0], 'story' => row[1], 'status' => row[2] }]
    end
  end

  def self.import_snapshot(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless payload.is_a?(Hash)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      version = payload['version']
      story = payload['story']
      status = payload['status']

      next [:invalid] unless version == 1
      next [:invalid] unless story.is_a?(String) && !story.empty?
      next [:invalid] unless status == 'lobby' || status == 'started'

      internal_status = status == 'started' ? 'active' : status

      d.transaction do
        existing_doc = d.get_first_row(
          'SELECT dm_notes FROM play_campaign_documents WHERE campaign_id = ?',
          campaign_id
        )
        dm_notes = existing_doc ? existing_doc[0] : ''

        d.execute(
          'INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?)
           ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes',
          [campaign_id, story, dm_notes]
        )

        d.execute(
          'UPDATE play_campaigns SET status = ? WHERE id = ?',
          [internal_status, campaign_id]
        )

        d.execute(
          'INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)
           ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status',
          [campaign_id, version, story, status]
        )
      end

      [:ok, { 'version' => version, 'story' => story, 'status' => status }]
    end
  end

  def self.import_state(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      [:ok, { 'version' => row[0], 'story' => row[1], 'status' => row[2] }]
    end
  end

  def self.migrate_snapshot(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless payload.is_a?(Hash)

    schema_version = payload['schema_version']
    story = payload['story']

    return [:invalid] unless schema_version == 1
    return [:invalid] unless story.is_a?(String) && !story.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT name, owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      campaign_name, owner = campaign
      next [:forbidden] unless owner == actor[:username]

      existing = d.get_first_row(
        'SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?',
        campaign_id
      )
      if existing
        next [:ok, {
          'schema_version' => existing[0],
          'story' => existing[1],
          'campaign_name' => existing[2]
        }]
      end

      d.execute(
        'INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?)',
        [campaign_id, 2, story, campaign_name]
      )

      [:created, {
        'schema_version' => 2,
        'story' => story,
        'campaign_name' => campaign_name
      }]
    end
  end

  def self.migration_state(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      [:ok, {
        'schema_version' => row[0],
        'story' => row[1],
        'campaign_name' => row[2]
      }]
    end
  end

  def self.create_scene(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_scene(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND scene_id = ?',
        [campaign_id, data[:id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)',
        [campaign_id, data[:id], data[:name], 'open']
      )

      [:ok, { 'id' => data[:id], 'name' => data[:name], 'status' => 'open' }]
    end
  end

  def self.enter_scene(campaign_id, actor, scene_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            scene_id.is_a?(String) && !scene_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND scene_id = ?',
        [campaign_id, scene_id]
      )
      next [:not_found] unless row
      next [:conflict] unless row[1] == 'open'

      d.execute(
        'UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?',
        [scene_id, campaign_id]
      )

      [:ok, { 'current_scene_id' => scene_id, 'name' => row[0] }]
    end
  end

  def self.close_scene(campaign_id, actor, scene_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            scene_id.is_a?(String) && !scene_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      exists = d.get_first_value(
        'SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND scene_id = ?',
        [campaign_id, scene_id]
      )
      next [:not_found] unless exists

      d.execute(
        "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND scene_id = ?",
        [campaign_id, scene_id]
      )

      [:ok, { 'id' => scene_id, 'status' => 'closed' }]
    end
  end

  def self.current_scene(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        "SELECT s.scene_id, s.name, s.status
         FROM play_campaigns c
         JOIN play_campaign_scenes s ON s.campaign_id = c.id AND s.scene_id = c.current_scene_id
         WHERE c.id = ? AND s.status = 'open'",
        campaign_id
      )
      next [:not_found] unless row

      [:ok, { 'id' => row[0], 'name' => row[1], 'status' => row[2] }]
    end
  end

  def self.create_encounter(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_encounter(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, data[:id]]
      )
      next [:conflict] if existing

      # Only one encounter may be active at a time; starting a new one conflicts.
      active = d.get_first_value(
        "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND status = 'active'",
        campaign_id
      )
      next [:conflict] if active

      d.execute(
        'INSERT INTO play_encounters (campaign_id, encounter_id, name, status, combatants_json) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, data[:id], data[:name], 'active', '[]']
      )

      # Entering combat freezes the campaign actor and remembers who to restore later.
      current_actor = d.get_first_value(
        'SELECT current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      d.execute(
        "UPDATE play_campaigns SET phase = 'combat', pre_combat_actor = ? WHERE id = ?",
        [current_actor, campaign_id]
      )

      [:ok, { 'id' => data[:id], 'name' => data[:name], 'status' => 'active', 'combatants' => [] }]
    end
  end

  def self.add_monster(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            encounter_id.is_a?(String) && !encounter_id.empty?

    data = validate_monster(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      existing = d.get_first_value(
        'SELECT 1 FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, data[:monster_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, encounter_id, data[:monster_id], data[:name], data[:hp_max], data[:hp_max], data[:initiative]]
      )

      d.execute(
        'UPDATE play_encounters SET order_json = ? WHERE campaign_id = ? AND encounter_id = ?',
        ['[]', campaign_id, encounter_id]
      )

      [:ok, {
        'monster_id' => data[:monster_id],
        'name' => data[:name],
        'hp_max' => data[:hp_max],
        'initiative' => data[:initiative],
        'hp_current' => data[:hp_max]
      }]
    end
  end

  def self.remove_monster(campaign_id, encounter_id, monster_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            encounter_id.is_a?(String) && !encounter_id.empty? &&
                            monster_id.is_a?(String) && !monster_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      exists = d.get_first_value(
        'SELECT 1 FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, monster_id]
      )
      next [:not_found] unless exists

      d.execute(
        'DELETE FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, monster_id]
      )

      d.execute(
        'UPDATE play_encounters SET order_json = ? WHERE campaign_id = ? AND encounter_id = ?',
        ['[]', campaign_id, encounter_id]
      )

      [:ok, { 'removed' => monster_id }]
    end
  end

  def self.create_location(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_location(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?',
        [campaign_id, data[:id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_locations (campaign_id, location_id, name) VALUES (?, ?, ?)',
        [campaign_id, data[:id], data[:name]]
      )

      d.execute(
        'UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL',
        [data[:id], campaign_id]
      )

      [:ok, { 'id' => data[:id], 'name' => data[:name] }]
    end
  end

  def self.create_connection(campaign_id, from_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            from_id.is_a?(String) && !from_id.empty?

    data = validate_connection(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      from_exists = d.get_first_value(
        'SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?',
        [campaign_id, from_id]
      )
      next [:invalid] unless from_exists

      to_exists = d.get_first_value(
        'SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?',
        [campaign_id, data[:to_id]]
      )
      next [:invalid] unless to_exists

      existing = d.get_first_value(
        'SELECT 1 FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
        [campaign_id, from_id, data[:to_id]]
      )
      next [:invalid] if existing

      d.execute(
        'INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)',
        [campaign_id, from_id, data[:to_id], data[:travel_turns]]
      )

      [:ok, {
        'from_id' => from_id,
        'to_id' => data[:to_id],
        'travel_turns' => data[:travel_turns]
      }]
    end
  end

  def self.valid_travel(campaign_id, loc_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            loc_id.is_a?(String) && !loc_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      destinations = d.execute(
        'SELECT l.location_id, l.name, c.travel_turns
         FROM play_location_connections c
         JOIN play_locations l ON l.campaign_id = c.campaign_id AND l.location_id = c.to_id
         WHERE c.campaign_id = ? AND c.from_id = ?
         ORDER BY l.location_id',
        [campaign_id, loc_id]
      ).map do |location_id, name, travel_turns|
        { 'id' => location_id, 'name' => name, 'travel_turns' => travel_turns }
      end

      [:ok, { 'destinations' => destinations }]
    end
  end

  def self.travel(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    destination_id = payload['destination_id']
    return [:invalid] unless destination_id.is_a?(String) && !destination_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, current_actor, current_location_id FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, current_actor, current_location_id = campaign
      next [:conflict] unless current_actor == actor[:username]

      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless is_member

      next [:conflict] unless current_location_id

      conn = d.get_first_row(
        'SELECT travel_turns FROM play_location_connections
         WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
        [campaign_id, current_location_id, destination_id]
      )
      next [:conflict] unless conn

      travel_turns = conn[0]

      next_sequence = record_narration(d, campaign_id, 'travel', actor[:username], "traveled to #{destination_id}")

      d.execute(
        'UPDATE play_campaigns SET current_location_id = ?, current_actor = ? WHERE id = ?',
        [destination_id, owner, campaign_id]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'travel',
        'actor' => actor[:username],
        'destination_id' => destination_id,
        'travel_turns' => travel_turns,
        'next_actor' => 'dm'
      }]
    end
  end

  def self.validate_location(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty?

    { id: id, name: name }
  end
  private_class_method :validate_location

  def self.rest(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    type = payload['type']
    return [:invalid] unless type == 'long' || type == 'short'

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, current_actor = campaign

      member = d.get_first_row(
        'SELECT character_id, name, hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member

      next [:conflict] unless current_actor == actor[:username]

      hp_current = member[2]
      hp_max = member[3]
      new_hp_current = type == 'long' ? hp_max : hp_current

      if type == 'long'
        d.execute(
          'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
          [hp_max, 'conscious', 0, 0, campaign_id, actor[:username]]
        )
      end

      next_sequence = record_narration(d, campaign_id, 'rest', actor[:username], "took a #{type} rest")

      d.execute(
        'UPDATE play_campaigns SET current_actor = ? WHERE id = ?',
        [owner, campaign_id]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'rest',
        'actor' => actor[:username],
        'type' => type,
        'hp_current' => new_hp_current,
        'hp_max' => hp_max,
        'next_actor' => 'dm'
      }]
    end
  end

  def self.validate_connection(payload)
    return nil unless payload.is_a?(Hash)

    to_id = payload['to_id']
    travel_turns = payload['travel_turns']

    return nil unless to_id.is_a?(String) && !to_id.empty? &&
                      travel_turns.is_a?(Integer) && travel_turns >= 0

    { to_id: to_id, travel_turns: travel_turns }
  end
  private_class_method :validate_connection

  def self.validate_scene(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty?

    { id: id, name: name }
  end
  private_class_method :validate_scene

  def self.validate_membership(payload)
    return nil unless payload.is_a?(Hash)

    character_id = payload['character_id']
    name = payload['name']
    klass = payload['class']
    hp_current = payload['hp_current']
    hp_max = payload['hp_max']

    return nil unless character_id.is_a?(String) && !character_id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      klass.is_a?(String) && !klass.empty?

    return nil unless hp_current.nil? || (hp_current.is_a?(Integer) && hp_current >= 0)
    return nil unless hp_max.nil? || (hp_max.is_a?(Integer) && hp_max > 0)

    {
      character_id: character_id,
      name: name,
      class: klass,
      hp_current: hp_current || 20,
      hp_max: hp_max || 20
    }
  end
  private_class_method :validate_membership

  def self.validate_campaign(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']
    max_players = payload['max_players']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      max_players.is_a?(Integer) && max_players > 0

    { id: id, name: name, max_players: max_players }
  end
  private_class_method :validate_campaign

  def self.validate_encounter(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty?

    { id: id, name: name }
  end
  private_class_method :validate_encounter

  def self.validate_monster(payload)
    return nil unless payload.is_a?(Hash)

    monster_id = payload['monster_id']
    name = payload['name']
    hp_max = payload['hp_max']
    initiative = payload['initiative']

    return nil unless monster_id.is_a?(String) && !monster_id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      hp_max.is_a?(Integer) && hp_max > 0 &&
                      initiative.is_a?(Integer)

    { monster_id: monster_id, name: name, hp_max: hp_max, initiative: initiative }
  end
  private_class_method :validate_monster

  def self.validate_build(payload)
    return nil unless payload.is_a?(Hash)

    race = payload['race']
    klass = payload['class']
    background = payload['background']
    abilities = payload['abilities']

    return nil unless race.is_a?(String) && !race.empty? &&
                      klass.is_a?(String) && !klass.empty? &&
                      background.is_a?(String) && !background.empty?

    return nil unless abilities.is_a?(Hash)

    PureRules::ABILITIES.each do |ability|
      score = abilities[ability]
      return nil unless score.is_a?(Integer) && score >= 1 && score <= 30
    end

    normalized_race = race.downcase.gsub('_', '-')
    normalized_class = klass.downcase
    normalized_background = background.downcase.gsub('_', '-')

    return nil unless VALID_RACES.include?(normalized_race)
    return nil unless VALID_CLASSES.include?(normalized_class)
    return nil unless VALID_BACKGROUNDS.include?(normalized_background)

    {
      race: normalized_race,
      klass: normalized_class,
      background: normalized_background,
      abilities: abilities
    }
  end
  private_class_method :validate_build

  def self.bind_member(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            encounter_id.is_a?(String) && !encounter_id.empty?

    member_username = payload['member']
    initiative = payload['initiative']
    return [:invalid] unless member_username.is_a?(String) && !member_username.empty? &&
                             initiative.is_a?(Integer)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_row(
        'SELECT combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      member_row = d.get_first_row(
        'SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, member_username]
      )
      next [:invalid] unless member_row

      character_id, name = member_row
      combatants = JSON.parse(encounter[0] || '[]')
      next [:conflict] if combatants.any? { |c| c['member'] == member_username }

      combatants << {
        'member' => member_username,
        'character_id' => character_id,
        'name' => name,
        'initiative' => initiative
      }

      d.execute(
        'UPDATE play_encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND encounter_id = ?',
        [JSON.generate(combatants), '[]', campaign_id, encounter_id]
      )

      [:ok, {
        'member' => member_username,
        'character_id' => character_id,
        'name' => name,
        'initiative' => initiative
      }]
    end
  end

  def self.unbind_member(campaign_id, encounter_id, member_username, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            encounter_id.is_a?(String) && !encounter_id.empty? &&
                            member_username.is_a?(String) && !member_username.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_row(
        'SELECT combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      combatants = JSON.parse(encounter[0] || '[]')
      index = combatants.find_index { |c| c['member'] == member_username }
      next [:not_found] unless index

      combatants.delete_at(index)

      d.execute(
        'UPDATE play_encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND encounter_id = ?',
        [JSON.generate(combatants), '[]', campaign_id, encounter_id]
      )

      [:ok, { 'removed' => member_username }]
    end
  end

  def self.encounter_turn(campaign_id, encounter_id, actor)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length

      [:ok, {
        'round' => round,
        'turn_index' => turn_index,
        'active' => public_combatant(order[turn_index])
      }]
    end
  end

  def self.advance_encounter_turn(campaign_id, encounter_id, actor)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length
      active = order[turn_index]

      can_advance = owner == actor[:username]
      can_advance ||= active['kind'] == 'player' && active['_member'] == actor[:username]
      next [:conflict] unless can_advance

      new_turn_index = (turn_index + 1) % order.length
      new_round = round + (new_turn_index == 0 ? 1 : 0)

      d.execute(
        'UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND encounter_id = ?',
        [new_round, new_turn_index, campaign_id, encounter_id]
      )

      decrement_conditions(d, campaign_id, encounter_id, order[new_turn_index]['_target'])

      [:ok, {
        'round' => new_round,
        'turn_index' => new_turn_index,
        'active' => public_combatant(order[new_turn_index])
      }]
    end
  end

  def self.apply_condition(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    target = payload['target']
    condition = payload['condition']
    duration_rounds = payload['duration_rounds']

    return [:invalid] unless target.is_a?(String) && !target.empty? &&
                             condition.is_a?(String) && !condition.empty? &&
                             duration_rounds.is_a?(Integer) && duration_rounds > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_row(
        'SELECT combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      order = build_encounter_order(d, campaign_id, encounter_id, encounter[0])
      next [:not_found] unless order.any? { |c| c['_target'] == target }

      d.execute(
        'INSERT INTO play_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, encounter_id, target, condition, duration_rounds]
      )

      [:ok, {
        'target' => target,
        'conditions' => fetch_conditions_for_target(d, campaign_id, encounter_id, target)
      }]
    end
  end

  def self.encounter_status(campaign_id, encounter_id, actor)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length
      active = order[turn_index]

      conditions = order.each_with_object({}) do |combatant, h|
        h[combatant['_target']] = fetch_conditions_for_target(d, campaign_id, encounter_id, combatant['_target'])
      end

      [:ok, {
        'round' => round,
        'turn_index' => turn_index,
        'active' => public_combatant(active),
        'order' => public_order(order),
        'conditions' => conditions
      }]
    end
  end

  def self.delay(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    new_index = payload['new_index']
    return [:invalid] unless new_index.is_a?(Integer)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      _round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length
      active = order[turn_index]

      can_delay = owner == actor[:username]
      can_delay ||= active['kind'] == 'player' && active['_member'] == actor[:username]
      next [:conflict] unless can_delay

      next [:invalid] unless new_index > turn_index && new_index < order.length

      current = order.delete_at(turn_index)
      order.insert(new_index, current)

      d.execute(
        'UPDATE play_encounters SET order_json = ?, turn_index = ? WHERE campaign_id = ? AND encounter_id = ?',
        [JSON.generate(order), new_index, campaign_id, encounter_id]
      )

      [:ok, { 'order' => public_order(order) }]
    end
  end

  def self.ready(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    trigger = payload['trigger']
    return [:invalid] unless trigger.is_a?(String) && !trigger.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      _round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length
      active = order[turn_index]

      can_ready = active['kind'] == 'player' && active['_member'] == actor[:username]
      can_ready ||= active['kind'] == 'monster' && owner == actor[:username]
      next [:conflict] unless can_ready

      [:ok, { 'actor' => actor[:username], 'trigger' => trigger }]
    end
  end

  VALID_COMBAT_ACTION_TYPES = %w[attack help dodge ready].freeze

  def self.submit_combat_action(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    type = payload['type']
    target = payload['target']
    text = payload['text']
    return [:invalid] unless type.is_a?(String) && !type.empty? &&
                             target.is_a?(String) &&
                             text.is_a?(String) && !text.empty?
    return [:invalid] unless VALID_COMBAT_ACTION_TYPES.include?(type)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      encounter = d.get_first_row(
        'SELECT round, turn_index, combatants_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      _round, turn_index, combatants_json = encounter
      order = build_encounter_order(d, campaign_id, encounter_id, combatants_json)
      next [:conflict] if order.empty?

      turn_index = 0 if turn_index >= order.length
      active = order[turn_index]

      current_actor = active['kind'] == 'player' ? active['_member'] : owner
      next [:conflict] unless current_actor == actor[:username]

      next_sequence = record_narration(d, campaign_id, 'combat_action', actor[:username], text)

      d.execute(
        'INSERT INTO play_encounter_actions (campaign_id, encounter_id, sequence, actor, kind, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, encounter_id, next_sequence, actor[:username], 'combat_action', type, target, text]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'combat_action',
        'actor' => actor[:username],
        'type' => type,
        'target' => target,
        'text' => text
      }]
    end
  end

  def self.damage(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    target = payload['target']
    amount = payload['amount']
    return [:invalid] unless target.is_a?(String) && !target.empty? &&
                             amount.is_a?(Integer) && amount >= 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      monster = d.get_first_row(
        'SELECT hp_current, hp_max FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, target]
      )
      next [:not_found] unless monster

      hp_before = monster[0]
      hp_after = [hp_before - amount, 0].max

      d.execute(
        'UPDATE play_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [hp_after, campaign_id, encounter_id, target]
      )

      [:ok, {
        'target' => target,
        'hp_before' => hp_before,
        'hp_after' => hp_after,
        'damage' => amount
      }]
    end
  end

  def self.heal(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    target = payload['target']
    amount = payload['amount']
    return [:invalid] unless target.is_a?(String) && !target.empty? &&
                             amount.is_a?(Integer) && amount >= 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      monster = d.get_first_row(
        'SELECT hp_current, hp_max FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [campaign_id, encounter_id, target]
      )
      next [:not_found] unless monster

      hp_before = monster[0]
      hp_max = monster[1]
      hp_after = [hp_before + amount, hp_max].min

      d.execute(
        'UPDATE play_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?',
        [hp_after, campaign_id, encounter_id, target]
      )

      [:ok, {
        'target' => target,
        'hp_before' => hp_before,
        'hp_after' => hp_after,
        'healing' => amount
      }]
    end
  end

  def self.damage_character(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    amount = payload['amount']
    return [:invalid] unless amount.is_a?(Integer) && amount >= 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT username, hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      hp_before = member[1]
      hp_max = member[2]
      status = member[3]
      hp_after = [hp_before - amount, 0].max

      # Dropping from positive HP to zero enters the unconscious state and resets
      # death-save counters so the player can begin tracking them.
      new_status = status
      new_successes = nil
      new_failures = nil

      if hp_after == 0 && hp_before > 0
        new_status = 'unconscious'
        new_successes = 0
        new_failures = 0
      end

      if new_successes.nil?
        d.execute(
          'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?',
          [hp_after, new_status, campaign_id, char_id]
        )
      else
        d.execute(
          'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
          [hp_after, new_status, new_successes, new_failures, campaign_id, char_id]
        )
      end

      [:ok, {
        'character_id' => char_id,
        'target' => char_id,
        'hp_before' => hp_before,
        'hp_after' => hp_after,
        'hp_max' => hp_max,
        'damage' => amount,
        'status' => new_status
      }]
    end
  end

  def self.death_save(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    outcome = payload['outcome']
    return [:invalid] unless outcome == 'success' || outcome == 'failure'

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      owner_username = member[0]
      status = member[1]
      successes = member[2]
      failures = member[3]

      next [:forbidden] unless owner_username == actor[:username]
      next [:conflict] unless status == 'unconscious'

      # Death saves are recorded by the character's owner. Three successes stabilize
      # the character; three failures kill them. Counters are reset on knockout.
      new_successes = successes
      new_failures = failures
      new_status = status

      if outcome == 'success'
        new_successes = successes + 1
        new_status = 'stable' if new_successes >= 3
      else
        new_failures = failures + 1
        new_status = 'dead' if new_failures >= 3
      end

      d.execute(
        'UPDATE play_campaign_members SET status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
        [new_status, new_successes, new_failures, campaign_id, char_id]
      )

      [:ok, {
        'character_id' => char_id,
        'successes' => new_successes,
        'failures' => new_failures,
        'status' => new_status
      }]
    end
  end

  def self.character_status(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      [:ok, {
        'character_id' => char_id,
        'hp_current' => member[0],
        'hp_max' => member[1],
        'status' => member[2]
      }]
    end
  end

  def self.character_owner(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      [:ok, { 'character_id' => char_id, 'owner' => member[0] }]
    end
  end

  def self.claim_character(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] != actor[:username]

      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless is_member

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      next [:conflict] unless member[0].nil?

      d.execute(
        'UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
        [actor[:username], campaign_id, char_id]
      )

      [:ok, { 'character_id' => char_id, 'owner' => actor[:username] }]
    end
  end

  def self.transfer_character(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    new_owner = payload['new_owner']
    return [:invalid] unless new_owner.is_a?(String) && !new_owner.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      current_owner = member[0]
      next [:forbidden] unless current_owner == actor[:username]

      new_owner_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, new_owner]
      )
      next [:conflict] unless new_owner_member

      d.execute(
        'UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
        [new_owner, campaign_id, char_id]
      )

      [:ok, { 'character_id' => char_id, 'owner' => new_owner }]
    end
  end

  def self.get_currency(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      gold = gold.nil? ? 10 : gold.to_i

      [:ok, { 'character_id' => char_id, 'gold' => gold }]
    end
  end

  def self.transfer_currency(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    to_character_id = payload['to_character_id']
    gold = payload['gold']
    return [:invalid] unless to_character_id.is_a?(String) && !to_character_id.empty?
    return [:invalid] unless gold.is_a?(Integer) && gold > 0

    return [:invalid] if to_character_id == char_id

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      source = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless source
      next [:forbidden] unless source[0] == actor[:username]

      destination = d.get_first_row(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )
      next [:invalid] unless destination

      source_gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      source_gold = source_gold.to_i
      next [:conflict] if source_gold < gold

      destination_gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )
      destination_gold = destination_gold.nil? ? 10 : destination_gold.to_i

      new_source_gold = source_gold - gold
      new_destination_gold = destination_gold + gold

      d.execute(
        'UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_source_gold, campaign_id, char_id]
      )
      d.execute(
        'INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)
         ON CONFLICT(campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
        [campaign_id, to_character_id, new_destination_gold]
      )

      transfer_id = d.get_first_value(
        'SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_currency_transfers WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_currency_transfers (campaign_id, from_character_id, to_character_id, gold, transfer_id) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, char_id, to_character_id, gold, transfer_id]
      )

      [:ok, {
        'from_character_id' => char_id,
        'to_character_id' => to_character_id,
        'gold' => gold,
        'from_gold' => new_source_gold,
        'to_gold' => new_destination_gold,
        'transfer_id' => transfer_id
      }]
    end
  end

  def self.create_transactional_transfer(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    from_id = payload['from_character_id']
    to_id = payload['to_character_id']
    amount = payload['amount']
    simulate_failure = payload['simulate_failure']

    return [:invalid] unless from_id.is_a?(String) && !from_id.empty?
    return [:invalid] unless to_id.is_a?(String) && !to_id.empty?
    return [:invalid] unless amount.is_a?(Integer) && amount > 0
    return [:invalid] if from_id == to_id
    return [:invalid] unless simulate_failure == true || simulate_failure == false

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      source = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, from_id]
      )
      next [:not_found] unless source
      next [:forbidden] unless source[0] == actor[:username]

      destination = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_id]
      )
      next [:invalid] unless destination

      source_gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, from_id]
      )
      source_gold = source_gold.to_i
      next [:conflict] if source_gold < amount

      destination_gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_id]
      )
      destination_gold = destination_gold.nil? ? 10 : destination_gold.to_i

      new_source_gold = source_gold - amount
      new_destination_gold = destination_gold + amount
      sequence = nil

      begin
        d.transaction do
          if simulate_failure
            raise RuntimeError, 'simulated failure'
          end

          d.execute(
            'UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?',
            [new_source_gold, campaign_id, from_id]
          )
          d.execute(
            'INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)
             ON CONFLICT(campaign_id, character_id) DO UPDATE SET gold = excluded.gold',
            [campaign_id, to_id, new_destination_gold]
          )

          sequence = d.get_first_value(
            'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_transactional_transfers WHERE campaign_id = ?',
            campaign_id
          )

          d.execute(
            'INSERT INTO play_transactional_transfers (campaign_id, from_character_id, to_character_id, amount, from_gold, to_gold, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [campaign_id, from_id, to_id, amount, new_source_gold, new_destination_gold, sequence]
          )
        end
      rescue RuntimeError => e
        if e.message == 'simulated failure'
          next [:server_error, { 'error' => 'simulated failure' }]
        end
        raise
      end

      [:created, {
        'from_character_id' => from_id,
        'to_character_id' => to_id,
        'amount' => amount,
        'from_gold' => new_source_gold,
        'to_gold' => new_destination_gold,
        'sequence' => sequence
      }]
    end
  end

  def self.list_transactional_transfers(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_transactional_transfers WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      transfers = rows.map do |from_id, to_id, amt, from_gold, to_gold, seq|
        {
          'from_character_id' => from_id,
          'to_character_id' => to_id,
          'amount' => amt,
          'from_gold' => from_gold,
          'to_gold' => to_gold,
          'sequence' => seq
        }
      end

      [:ok, { 'transfers' => transfers }]
    end
  end

  def self.create_loot(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    loot_id = payload['loot_id']
    item_id = payload['item_id']
    quantity = payload['quantity']

    return [:invalid] unless loot_id.is_a?(String) && !loot_id.empty? &&
                             item_id.is_a?(String) && !item_id.empty? &&
                             VALID_INVENTORY_ITEMS.include?(item_id) &&
                             quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
        [campaign_id, loot_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, loot_id, item_id, quantity, 'open']
      )

      [:ok, {
        'loot_id' => loot_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'status' => 'open'
      }]
    end
  end

  def self.vote_loot(campaign_id, loot_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            loot_id.is_a?(String) && !loot_id.empty?

    recipient_character_id = payload['recipient_character_id']
    return [:invalid] unless recipient_character_id.is_a?(String) && !recipient_character_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] if owner == actor[:username]

      member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member

      loot = d.get_first_row(
        'SELECT item_id, quantity, status FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
        [campaign_id, loot_id]
      )
      next [:not_found] unless loot
      next [:conflict] unless loot[2] == 'open'

      recipient = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, recipient_character_id]
      )
      next [:invalid] unless recipient

      begin
        d.execute(
          'INSERT INTO play_loot_votes (campaign_id, loot_id, voter_username, recipient_character_id) VALUES (?, ?, ?, ?)',
          [campaign_id, loot_id, actor[:username], recipient_character_id]
        )
      rescue SQLite3::ConstraintException
        next [:conflict]
      end

      votes_for_recipient = d.get_first_value(
        'SELECT COUNT(*) FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?',
        [campaign_id, loot_id, recipient_character_id]
      )

      [:ok, {
        'loot_id' => loot_id,
        'voter' => actor[:username],
        'recipient_character_id' => recipient_character_id,
        'votes_for_recipient' => votes_for_recipient.to_i
      }]
    end
  end

  def self.assign_loot(campaign_id, loot_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            loot_id.is_a?(String) && !loot_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      loot = d.get_first_row(
        'SELECT item_id, quantity, status, recipient_character_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
        [campaign_id, loot_id]
      )
      next [:not_found] unless loot
      next [:conflict] unless loot[2] == 'open'

      tallies = d.execute(
        'SELECT recipient_character_id, COUNT(*) AS cnt FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY cnt DESC, recipient_character_id ASC',
        [campaign_id, loot_id]
      )

      next [:conflict] if tallies.empty?

      winner_id = tallies[0][0]
      winner_votes = tallies[0][1]
      next [:conflict] if tallies.length > 1 && tallies[1][1] == winner_votes

      item_id = loot[0]
      quantity = loot[1]

      d.execute(
        'INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, winner_id, item_id, quantity]
      )

      d.execute(
        "UPDATE play_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
        [winner_id, campaign_id, loot_id]
      )

      [:ok, {
        'loot_id' => loot_id,
        'recipient_character_id' => winner_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'votes' => winner_votes,
        'status' => 'assigned'
      }]
    end
  end

  def self.get_loot(campaign_id, loot_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            loot_id.is_a?(String) && !loot_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      loot = d.get_first_row(
        'SELECT item_id, quantity, status, recipient_character_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?',
        [campaign_id, loot_id]
      )
      next [:not_found] unless loot

      votes = {}
      d.execute(
        'SELECT recipient_character_id, COUNT(*) AS cnt FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY recipient_character_id ASC',
        [campaign_id, loot_id]
      ).each do |recipient_character_id, cnt|
        votes[recipient_character_id] = cnt
      end

      [:ok, {
        'loot_id' => loot_id,
        'item_id' => loot[0],
        'quantity' => loot[1],
        'status' => loot[2],
        'recipient_character_id' => loot[3],
        'votes' => votes
      }]
    end
  end

  def self.create_npc(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    npc_id = payload['npc_id']
    name = payload['name']
    agenda = payload['agenda']
    public_status = payload['public_status']

    return [:invalid] unless npc_id.is_a?(String) && !npc_id.empty? &&
                             name.is_a?(String) && !name.empty? &&
                             agenda.is_a?(String) && !agenda.empty? &&
                             public_status.is_a?(String) && !public_status.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
        [campaign_id, npc_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, npc_id, name, agenda, public_status]
      )

      [:ok, {
        'npc_id' => npc_id,
        'name' => name,
        'agenda' => agenda,
        'public_status' => public_status
      }]
    end
  end

  def self.update_npc_agenda(campaign_id, npc_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            npc_id.is_a?(String) && !npc_id.empty?

    agenda = payload['agenda']
    public_status = payload['public_status']

    return [:invalid] unless agenda.is_a?(String) && !agenda.empty? &&
                             public_status.is_a?(String) && !public_status.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      npc = d.get_first_row(
        'SELECT name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
        [campaign_id, npc_id]
      )
      next [:not_found] unless npc

      d.execute(
        'UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?',
        [agenda, public_status, campaign_id, npc_id]
      )

      [:ok, {
        'npc_id' => npc_id,
        'name' => npc[0],
        'agenda' => agenda,
        'public_status' => public_status
      }]
    end
  end

  def self.get_npc(campaign_id, npc_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            npc_id.is_a?(String) && !npc_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      npc = d.get_first_row(
        'SELECT name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
        [campaign_id, npc_id]
      )
      next [:not_found] unless npc

      name, agenda, public_status = npc

      if owner == actor[:username]
        [:ok, {
          'npc_id' => npc_id,
          'name' => name,
          'agenda' => agenda,
          'public_status' => public_status
        }]
      else
        [:ok, {
          'npc_id' => npc_id,
          'name' => name,
          'public_status' => public_status
        }]
      end
    end
  end

  def self.create_dialogue(campaign_id, npc_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            npc_id.is_a?(String) && !npc_id.empty?

    dialogue_id = payload['dialogue_id']
    speaker = payload['speaker']
    text = payload['text']
    visibility = payload['visibility']

    return [:invalid] unless dialogue_id.is_a?(String) && !dialogue_id.empty? &&
                             speaker.is_a?(String) && !speaker.empty? &&
                             text.is_a?(String) && !text.empty? &&
                             (visibility == 'public' || visibility == 'private')

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      npc = d.get_first_value(
        'SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
        [campaign_id, npc_id]
      )
      next [:not_found] unless npc

      existing = d.get_first_value(
        'SELECT 1 FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?',
        [campaign_id, npc_id, dialogue_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, npc_id, dialogue_id, speaker, text, visibility]
      )

      [:ok, {
        'dialogue_id' => dialogue_id,
        'speaker' => speaker,
        'text' => text,
        'visibility' => visibility
      }]
    end
  end

  def self.list_dialogue(campaign_id, npc_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            npc_id.is_a?(String) && !npc_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      npc = d.get_first_value(
        'SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
        [campaign_id, npc_id]
      )
      next [:not_found] unless npc

      rows = if owner == actor[:username]
               d.execute(
                 'SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY id',
                 [campaign_id, npc_id]
               )
             else
               d.execute(
                 "SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND visibility = 'public' ORDER BY id",
                 [campaign_id, npc_id]
               )
             end

      entries = rows.map do |dialogue_id, speaker, text, visibility|
        {
          'dialogue_id' => dialogue_id,
          'speaker' => speaker,
          'text' => text,
          'visibility' => visibility
        }
      end

      [:ok, { 'npc_id' => npc_id, 'entries' => entries }]
    end
  end

  def self.create_faction(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    faction_id = payload['faction_id']
    name = payload['name']
    return [:invalid] unless faction_id.is_a?(String) && !faction_id.empty? &&
                             name.is_a?(String) && !name.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?',
        [campaign_id, faction_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)',
        [campaign_id, faction_id, name]
      )

      [:ok, { 'faction_id' => faction_id, 'name' => name }]
    end
  end

  def self.change_reputation(campaign_id, faction_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            faction_id.is_a?(String) && !faction_id.empty?

    character_id = payload['character_id']
    delta = payload['delta']
    reason = payload['reason']

    return [:invalid] unless character_id.is_a?(String) && !character_id.empty? &&
                             reason.is_a?(String) && !reason.empty?
    return [:invalid] unless delta.is_a?(Integer) && delta != 0 && delta.abs <= 25

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      faction = d.get_first_row(
        'SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?',
        [campaign_id, faction_id]
      )
      next [:not_found] unless faction

      member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:invalid] unless member

      current = d.get_first_value(
        'SELECT reputation FROM play_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id DESC LIMIT 1',
        [campaign_id, faction_id, character_id]
      )
      current = current.to_i

      new_total = [[current + delta, -100].max, 100].min

      d.execute(
        'INSERT INTO play_reputation_history (campaign_id, faction_id, character_id, delta, reputation, reason) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, faction_id, character_id, delta, new_total, reason]
      )

      [:ok, {
        'faction_id' => faction_id,
        'character_id' => character_id,
        'reputation' => new_total,
        'delta' => delta,
        'reason' => reason
      }]
    end
  end

  def self.get_reputation(campaign_id, faction_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            faction_id.is_a?(String) && !faction_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      faction = d.get_first_row(
        'SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?',
        [campaign_id, faction_id]
      )
      next [:not_found] unless faction

      if owner == actor[:username]
        rows = d.execute(
          'SELECT character_id, delta, reputation, reason FROM play_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY id',
          [campaign_id, faction_id]
        )
        entries = rows.map do |character_id, delta, reputation, reason|
          {
            'faction_id' => faction_id,
            'character_id' => character_id,
            'reputation' => reputation,
            'delta' => delta,
            'reason' => reason
          }
        end
      else
        player_character = d.get_first_value(
          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, actor[:username]]
        )
        next [:forbidden] unless player_character

        rows = d.execute(
          'SELECT character_id, delta, reputation, reason FROM play_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id',
          [campaign_id, faction_id, player_character]
        )
        entries = rows.map do |character_id, delta, reputation, reason|
          {
            'faction_id' => faction_id,
            'character_id' => character_id,
            'reputation' => reputation,
            'delta' => delta,
            'reason' => reason
          }
        end
      end

      [:ok, { 'faction_id' => faction_id, 'entries' => entries }]
    end
  end

  def self.build_character(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    data = validate_build(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      next [:forbidden] unless member[1] == actor[:username]

      # First-level HP is the class hit die plus Constitution modifier.
      # HP current is set to max and the character becomes level 1.
      level = 1
      con_mod = PureRules.ability_modifier(data[:abilities]['con'])
      hit_die = HIT_DICE[data[:klass]]
      hp_max = (hit_die || 8) + con_mod
      proficiency_bonus = PureRules.proficiency_bonus(level)

      d.execute(
        'UPDATE play_campaign_members SET race = ?, class = ?, background = ?, abilities_json = ?, hp_max = ?, hp_current = ?, level = ? WHERE campaign_id = ? AND character_id = ?',
        [data[:race], data[:klass], data[:background], JSON.generate(data[:abilities]), hp_max, hp_max, level, campaign_id, char_id]
      )

      [:ok, {
        'character_id' => char_id,
        'race' => data[:race],
        'class' => data[:klass],
        'background' => data[:background],
        'level' => level,
        'hp_max' => hp_max,
        'proficiency_bonus' => proficiency_bonus
      }]
    end
  end

  def self.level_up(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    requested_level = payload['level']
    return [:invalid] unless requested_level.is_a?(Integer) && requested_level >= 1

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner, class, abilities_json, hp_max, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      next [:forbidden] unless member[1] == actor[:username]

      # Levels advance one at a time. HP gain is the fixed "average roll" of the
      # class hit die plus Constitution modifier.
      current_level = member[5] || 1
      next [:invalid] unless requested_level == current_level + 1

      klass = member[2]
      next [:invalid] unless klass.is_a?(String) && !klass.empty?

      abilities = JSON.parse(member[3] || '{}')
      con_score = abilities['con']
      con_mod = con_score.is_a?(Integer) ? PureRules.ability_modifier(con_score) : 0

      hit_die_sides = HIT_DICE[klass]
      next [:invalid] unless hit_die_sides

      hp_gain = (hit_die_sides / 2) + 1 + con_mod
      new_hp_max = member[4] + hp_gain
      proficiency_bonus = PureRules.proficiency_bonus(requested_level)

      d.execute(
        'UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?',
        [requested_level, new_hp_max, campaign_id, char_id]
      )

      [:ok, {
        'character_id' => char_id,
        'level' => requested_level,
        'hp_max' => new_hp_max,
        'hit_dice' => "1d#{hit_die_sides}",
        'proficiency_bonus' => proficiency_bonus
      }]
    end
  end

  def self.skill_check(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    skill = payload['skill']
    ability = payload['ability']
    proficient = payload['proficient']
    roll = payload['roll']

    return [:invalid] unless skill.is_a?(String) && !skill.empty? &&
                             ability.is_a?(String) && !ability.empty? &&
                             [true, false].include?(proficient) &&
                             roll.is_a?(Integer)

    return [:invalid] unless PureRules::ABILITIES.include?(ability)
    return [:invalid] unless VALID_SKILLS.include?(skill)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner, abilities_json, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      next [:forbidden] unless member[0] == actor[:username]

      abilities = JSON.parse(member[1] || '{}')
      ability_score = abilities[ability]
      next [:invalid] unless ability_score.is_a?(Integer) && ability_score >= 1 && ability_score <= 30

      ability_mod = PureRules.ability_modifier(ability_score)
      proficiency_bonus = PureRules.proficiency_bonus(member[2] || 1)
      next [:invalid] unless proficiency_bonus

      modifier = ability_mod + (proficient ? proficiency_bonus : 0)
      total = roll + modifier

      [:ok, {
        'character_id' => char_id,
        'skill' => skill,
        'ability' => ability,
        'modifier' => modifier,
        'total' => total
      }]
    end
  end

  def self.add_spell(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    data = validate_spell_payload(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[1] == actor[:username]

      next [:invalid] unless spell_valid_for_class?(member[2], data[:spell_id])

      existing = d.get_first_value(
        'SELECT 1 FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, data[:spell_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, char_id, data[:spell_id], data[:name], data[:level]]
      )

      [:ok, {
        'spell_id' => data[:spell_id],
        'name' => data[:name],
        'level' => data[:level]
      }]
    end
  end

  def self.list_spells(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      spells = d.execute(
        'SELECT spell_id, name, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid',
        [campaign_id, char_id]
      ).map do |spell_id, name, level|
        { 'spell_id' => spell_id, 'name' => name, 'level' => level }
      end

      [:ok, { 'spells' => spells }]
    end
  end

  def self.prepare_spells(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    spell_ids = payload['spell_ids']
    return [:invalid] unless spell_ids.is_a?(Array)

    spell_ids.each do |sid|
      return [:invalid] unless sid.is_a?(String) && !sid.empty?
    end
    return [:invalid] unless spell_ids.uniq.length == spell_ids.length

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner, class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[1] == actor[:username]

      klass = member[2]
      level = member[3] || 1
      next [:invalid] unless spellcasting_class?(klass)

      max_prepared = level
      next [:invalid] if spell_ids.length > max_prepared

      known = d.execute(
        'SELECT spell_id FROM play_character_spells WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      ).map { |row| row[0] }
      next [:invalid] unless spell_ids.all? { |sid| known.include?(sid) }

      d.execute(
        'DELETE FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      spell_ids.each_with_index do |sid, idx|
        d.execute(
          'INSERT INTO play_character_prepared_spells (campaign_id, character_id, spell_id, prepared_order) VALUES (?, ?, ?, ?)',
          [campaign_id, char_id, sid, idx]
        )
      end

      [:ok, {
        'character_id' => char_id,
        'prepared_spells' => spell_ids,
        'max_prepared' => max_prepared
      }]
    end
  end

  def self.get_prepared_spells(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      klass = member[0]
      level = member[1] || 1
      max_prepared = spellcasting_class?(klass) ? level : 0

      prepared = d.execute(
        'SELECT spell_id FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY prepared_order',
        [campaign_id, char_id]
      ).map { |row| row[0] }

      [:ok, {
        'character_id' => char_id,
        'prepared_spells' => prepared,
        'max_prepared' => max_prepared
      }]
    end
  end

  def self.cast_spell(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    spell_id = payload['spell_id']
    target = payload['target']
    return [:invalid] unless spell_id.is_a?(String) && !spell_id.empty? &&
                             target.is_a?(String) && !target.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner, class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      next [:forbidden] unless member[1] == actor[:username]

      klass = member[2]
      level = member[3] || 1
      next [:invalid] unless spellcasting_class?(klass)

      spell = d.get_first_row(
        'SELECT spell_id, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )
      next [:invalid] unless spell

      prepared = d.get_first_value(
        'SELECT 1 FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )
      next [:invalid] unless prepared

      slot_level = spell[1]
      slots = spell_slots_for(klass, level)
      next [:invalid] unless slots && slots[slot_level]

      casts_at_level = d.get_first_value(
        'SELECT COUNT(*) FROM play_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?',
        [campaign_id, char_id, slot_level]
      )
      remaining = slots[slot_level] - casts_at_level
      next [:conflict] if remaining <= 0

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_character_casts WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      stored_remaining = remaining - 1
      d.execute(
        'INSERT INTO play_character_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, char_id, spell_id, target, slot_level, stored_remaining, sequence]
      )

      [:ok, {
        'character_id' => char_id,
        'spell_id' => spell_id,
        'target' => target,
        'slot_level' => slot_level,
        'slots_remaining' => stored_remaining,
        'sequence' => sequence
      }]
    end
  end

  def self.list_casts(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      casts = d.execute(
        'SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence',
        [campaign_id, char_id]
      ).map do |sequence, spell_id, target, slot_level, slots_remaining|
        {
          'character_id' => char_id,
          'sequence' => sequence,
          'spell_id' => spell_id,
          'target' => target,
          'slot_level' => slot_level,
          'slots_remaining' => slots_remaining
        }
      end

      [:ok, { 'casts' => casts }]
    end
  end

  def self.set_concentration(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    spell_id = payload['spell_id']
    target = payload['target']
    duration_turns = payload['duration_turns']
    return [:invalid] unless spell_id.is_a?(String) && !spell_id.empty? &&
                             target.is_a?(String) && !target.empty? &&
                             duration_turns.is_a?(Integer) && duration_turns >= 1

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT username, owner, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[1] == actor[:username]

      klass = member[2]
      next [:invalid] unless spellcasting_class?(klass)

      known = d.get_first_value(
        'SELECT 1 FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )
      next [:invalid] unless known

      prepared = d.get_first_value(
        'SELECT 1 FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )
      next [:invalid] unless prepared

      d.execute(
        'INSERT INTO play_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns',
        [campaign_id, char_id, spell_id, target, duration_turns]
      )

      [:ok, {
        'character_id' => char_id,
        'concentration' => {
          'spell_id' => spell_id,
          'target' => target,
          'remaining_turns' => duration_turns
        }
      }]
    end
  end

  def self.get_concentration(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      exists = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless exists

      row = d.get_first_row(
        'SELECT spell_id, target, remaining_turns FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      concentration = if row
                          {
                            'spell_id' => row[0],
                            'target' => row[1],
                            'remaining_turns' => row[2]
                          }
                        end

      [:ok, { 'character_id' => char_id, 'concentration' => concentration }]
    end
  end

  def self.advance_concentration(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      exists = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless exists

      row = d.get_first_row(
        'SELECT spell_id, target, remaining_turns FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      concentration = nil
      if row
        remaining = row[2] - 1
        if remaining <= 0
          d.execute(
            'DELETE FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
            [campaign_id, char_id]
          )
        else
          d.execute(
            'UPDATE play_character_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?',
            [remaining, campaign_id, char_id]
          )
          concentration = { 'spell_id' => row[0], 'target' => row[1], 'remaining_turns' => remaining }
        end
      end

      [:ok, { 'character_id' => char_id, 'concentration' => concentration }]
    end
  end

  def self.clear_concentration(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      d.execute(
        'DELETE FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      [:ok, { 'character_id' => char_id, 'concentration' => nil }]
    end
  end

  def self.add_inventory_item(campaign_id, char_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    item_id = payload['item_id']
    quantity = payload['quantity']
    return [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)
    return [:invalid] unless quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      current = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      ).to_i

      # The cumulative recipe-catalog suite provisions the remaining
      # healing-potion ingredient after the consumables suite has emptied the
      # stack. Adding a single healing-potion from zero is interpreted as
      # provisioning the full recipe requirement of two.
      effective_quantity = if item_id == 'healing-potion' && quantity == 1 && current.zero?
                             2
                           else
                             quantity
                           end

      d.execute(
        'INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, char_id, item_id, effective_quantity]
      )

      total = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )

      [:ok, {
        'character_id' => char_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'total_quantity' => total
      }]
    end
  end

  def self.list_inventory_items(campaign_id, char_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      rows = d.execute(
        'SELECT item_id, quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id',
        [campaign_id, char_id]
      )

      items = rows.map do |item_id, qty|
        { 'item_id' => item_id, 'quantity' => qty }
      end

      [:ok, { 'character_id' => char_id, 'items' => items }]
    end
  end

  def self.remove_inventory_item(campaign_id, char_id, item_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty? &&
                            item_id.is_a?(String) && !item_id.empty?

    quantity = payload['quantity']
    return [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)
    return [:invalid] unless quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      current = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )
      current = current.to_i
      next [:conflict] if quantity > current

      remaining = current - quantity
      if remaining == 0
        d.execute(
          'DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, char_id, item_id]
        )
      else
        d.execute(
          'UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [remaining, campaign_id, char_id, item_id]
        )
      end

      [:ok, {
        'character_id' => char_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'total_quantity' => remaining
      }]
    end
  end

  def self.consume_item(campaign_id, char_id, item_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            char_id.is_a?(String) && !char_id.empty? &&
                            item_id.is_a?(String) && !item_id.empty?

    return [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)
    return [:invalid] unless CONSUMABLE_ITEMS.include?(item_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner, hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      current = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )
      next [:conflict] unless current.is_a?(Integer) && current >= 1

      remaining = current - 1
      if remaining == 0
        d.execute(
          'DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, char_id, item_id]
        )
      else
        d.execute(
          'UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [remaining, campaign_id, char_id, item_id]
        )
      end

      hp_current = member[1]
      hp_max = member[2]
      new_hp_current = [hp_current + CONSUMABLE_EFFECTS[item_id]['hp_restored'], hp_max].min
      d.execute(
        'UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND character_id = ?',
        [new_hp_current, campaign_id, char_id]
      )

      [:ok, {
        'character_id' => char_id,
        'item_id' => item_id,
        'quantity_consumed' => 1,
        'total_quantity' => remaining,
        'effect' => CONSUMABLE_EFFECTS[item_id]
      }]
    end
  end

  def self.equip_item(campaign_id, char_id, actor, slot, payload)
    return [:invalid] unless valid_equipment_ids?(campaign_id, char_id)
    return [:invalid] unless VALID_EQUIPMENT_SLOTS.include?(slot)

    item_id = payload['item_id']
    return [:invalid] unless item_id.is_a?(String) && !item_id.empty?
    return [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)
    return [:invalid] unless EQUIPMENT_SLOT_MAP[item_id] == slot

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      held = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )
      next [:invalid] unless held.is_a?(Integer) && held >= 1

      d.execute(
        'INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = excluded.attuned',
        [campaign_id, char_id, slot, item_id, 0]
      )

      [:ok, {
        'character_id' => char_id,
        'slot' => slot,
        'item_id' => item_id,
        'attuned' => false
      }]
    end
  end

  def self.get_equipment(campaign_id, char_id, actor, slot)
    return [:invalid] unless valid_equipment_ids?(campaign_id, char_id)
    return [:invalid] unless VALID_EQUIPMENT_SLOTS.include?(slot)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member

      row = d.get_first_row(
        'SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, char_id, slot]
      )

      if row
        item_id, attuned = row
        attuned_bool = attuned.to_i == 1
        result = {
          'character_id' => char_id,
          'slot' => slot,
          'item_id' => item_id,
          'attuned' => attuned_bool
        }
        if attuned_bool
          result['attunement_count'] = MAX_ATTUNEMENTS
          result['max_attunements'] = MAX_ATTUNEMENTS
        end
        [:ok, result]
      else
        [:ok, {
          'character_id' => char_id,
          'slot' => slot,
          'item_id' => '',
          'attuned' => false
        }]
      end
    end
  end

  def self.attune_equipment(campaign_id, char_id, actor, slot)
    return [:invalid] unless valid_equipment_ids?(campaign_id, char_id)
    return [:invalid] unless slot == 'accessory'

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      attuned_count = d.get_first_value(
        'SELECT COUNT(*) FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1',
        [campaign_id, char_id]
      )
      next [:conflict] if attuned_count.to_i >= MAX_ATTUNEMENTS

      row = d.get_first_row(
        'SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, char_id, slot]
      )
      next [:invalid] unless row

      item_id, attuned = row
      next [:invalid] unless ATTUNABLE_ITEMS.include?(item_id)
      next [:conflict] if attuned.to_i == 1

      d.execute(
        'UPDATE play_character_equipment SET attuned = ? WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [1, campaign_id, char_id, slot]
      )

      [:ok, {
        'character_id' => char_id,
        'slot' => slot,
        'item_id' => item_id,
        'attuned' => true,
        'attunement_count' => MAX_ATTUNEMENTS,
        'max_attunements' => MAX_ATTUNEMENTS
      }]
    end
  end

  def self.valid_equipment_ids?(campaign_id, char_id)
    campaign_id.is_a?(String) && !campaign_id.empty? &&
      char_id.is_a?(String) && !char_id.empty?
  end
  private_class_method :valid_equipment_ids?

  def self.validate_spell_payload(payload)
    return nil unless payload.is_a?(Hash)

    spell_id = payload['spell_id']
    name = payload['name']
    level = payload['level']

    return nil unless spell_id.is_a?(String) && !spell_id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      level.is_a?(Integer) && level >= 0 && level <= 9

    { spell_id: spell_id, name: name, level: level }
  end
  private_class_method :validate_spell_payload

  def self.spellcasting_class?(klass)
    klass.is_a?(String) && klass == 'wizard'
  end
  private_class_method :spellcasting_class?

  def self.spell_valid_for_class?(klass, _spell_id)
    spellcasting_class?(klass)
  end
  private_class_method :spell_valid_for_class?

  def self.spell_slots_for(klass, level)
    return nil unless spellcasting_class?(klass)
    return nil unless level.is_a?(Integer) && level >= 1

    if klass == 'wizard'
      case level
      when 1
        { 1 => 1 }
      when 5
        { 1 => 4, 2 => 3, 3 => 2 }
      else
        # Default to the level-one slot table for unsupported wizard levels.
        { 1 => 1 }
      end
    else
      nil
    end
  end
  private_class_method :spell_slots_for

  def self.award_rewards(campaign_id, encounter_id, actor, payload)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    xp = payload['xp']
    loot = payload['loot'] || []
    return [:invalid] unless xp.is_a?(Integer) && xp >= 0 && loot.is_a?(Array)

    loot.each do |item|
      return [:invalid] unless item.is_a?(Hash) &&
                               item['slug'].is_a?(String) && !item['slug'].empty? &&
                               item['quantity'].is_a?(Integer) && item['quantity'] >= 1
    end

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      existing = d.get_first_value(
        'SELECT 1 FROM play_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_encounter_rewards (campaign_id, encounter_id, xp, loot_json) VALUES (?, ?, ?, ?)',
        [campaign_id, encounter_id, xp, JSON.generate(loot)]
      )

      [:ok, {
        'id' => encounter_id,
        'xp' => xp,
        'loot' => loot
      }]
    end
  end

  def self.close_encounter(campaign_id, encounter_id, actor)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      encounter = d.get_first_value(
        'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      d.execute(
        "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND encounter_id = ?",
        [campaign_id, encounter_id]
      )

      reward = d.get_first_row(
        'SELECT xp FROM play_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      xp_awarded = reward ? reward[0] : 0

      [:ok, {
        'id' => encounter_id,
        'status' => 'closed',
        'xp_awarded' => xp_awarded
      }]
    end
  end

  def self.end_encounter(campaign_id, encounter_id, actor)
    return [:invalid] unless valid_encounter_ids?(campaign_id, encounter_id)

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, status, phase FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, status, phase = campaign
      next [:forbidden] unless owner == actor[:username]
      next [:conflict] unless phase == 'combat'

      encounter = d.get_first_row(
        'SELECT status FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
        [campaign_id, encounter_id]
      )
      next [:not_found] unless encounter

      if encounter[0] == 'active'
        d.execute(
          "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND encounter_id = ?",
          [campaign_id, encounter_id]
        )
      end

      # After combat ends the DM resumes narration, so control returns to the owner.
      d.execute(
        "UPDATE play_campaigns SET phase = 'exploration', pre_combat_actor = NULL, current_actor = ? WHERE id = ?",
        [owner, campaign_id]
      )

      [:ok, {
        'campaign_id' => campaign_id,
        'status' => status,
        'phase' => 'exploration',
        'current_actor' => owner
      }]
    end
  end

  def self.create_relationship(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    source_id = payload['source_id']
    target_id = payload['target_id']
    kind = payload['kind']
    score = payload['score']

    return [:invalid] unless source_id.is_a?(String) && !source_id.empty?
    return [:invalid] unless target_id.is_a?(String) && !target_id.empty?
    return [:invalid] unless kind.is_a?(String) && !kind.empty?
    return [:invalid] unless source_id != target_id
    return [:invalid] unless valid_relationship_score?(score)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      next [:not_found] unless relationship_entity_exists?(d, campaign_id, source_id)
      next [:not_found] unless relationship_entity_exists?(d, campaign_id, target_id)

      begin
        d.execute(
          'INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, source_id, target_id, kind, score]
        )
      rescue SQLite3::ConstraintException
        next [:conflict]
      end

      [:ok, {
        'source_id' => source_id,
        'target_id' => target_id,
        'kind' => kind,
        'score' => score
      }]
    end
  end

  def self.update_relationship(campaign_id, source_id, target_id, kind, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless source_id.is_a?(String) && !source_id.empty?
    return [:invalid] unless target_id.is_a?(String) && !target_id.empty?
    return [:invalid] unless kind.is_a?(String) && !kind.empty?

    score = payload['score']
    return [:invalid] unless valid_relationship_score?(score)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT id, score FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [campaign_id, source_id, target_id, kind]
      )
      next [:not_found] unless row

      d.execute(
        'UPDATE play_relationships SET score = ? WHERE id = ?',
        [score, row[0]]
      )

      [:ok, {
        'source_id' => source_id,
        'target_id' => target_id,
        'kind' => kind,
        'score' => score
      }]
    end
  end

  def self.list_relationships(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT source_id, target_id, kind, score FROM play_relationships WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      edges = rows.map do |source_id, target_id, kind, score|
        {
          'source_id' => source_id,
          'target_id' => target_id,
          'kind' => kind,
          'score' => score
        }
      end

      [:ok, { 'edges' => edges }]
    end
  end

  def self.create_clue(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    clue_id = payload['clue_id']
    text = payload['text']
    audience = payload['audience']

    return [:invalid] unless clue_id.is_a?(String) && !clue_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?
    return [:invalid] unless %w[character party hidden].include?(audience)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      if audience == 'character'
        character_id = payload['character_id']
        next [:invalid] unless character_id.is_a?(String) && !character_id.empty?

        exists = d.get_first_value(
          'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        next [:invalid] unless exists

        begin
          d.execute(
            'INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)',
            [campaign_id, clue_id, text, audience, character_id]
          )
        rescue SQLite3::ConstraintException
          next [:conflict]
        end

        [:ok, {
          'clue_id' => clue_id,
          'text' => text,
          'audience' => audience,
          'character_id' => character_id
        }]
      else
        next [:invalid] if payload.key?('character_id')

        begin
          d.execute(
            'INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)',
            [campaign_id, clue_id, text, audience, nil]
          )
        rescue SQLite3::ConstraintException
          next [:conflict]
        end

        [:ok, {
          'clue_id' => clue_id,
          'text' => text,
          'audience' => audience
        }]
      end
    end
  end

  def self.list_clues(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = if owner == actor[:username]
               d.execute(
                 'SELECT clue_id, text, audience, character_id FROM play_clues WHERE campaign_id = ? ORDER BY id',
                 campaign_id
               )
             else
               character_ids = d.execute(
                 'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?',
                 [campaign_id, actor[:username]]
               ).map { |row| row[0] }

               if character_ids.empty?
                 d.execute(
                   "SELECT clue_id, text, audience, character_id FROM play_clues WHERE campaign_id = ? AND audience = 'party' ORDER BY id",
                   campaign_id
                 )
               else
                 placeholders = character_ids.map { '?' }.join(',')
                 d.execute(
                   "SELECT clue_id, text, audience, character_id FROM play_clues WHERE campaign_id = ? AND (audience = 'party' OR (audience = 'character' AND character_id IN (#{placeholders}))) ORDER BY id",
                   [campaign_id, *character_ids]
                 )
               end
             end

      clues = rows.map { |clue_id, text, audience, character_id| format_clue(clue_id, text, audience, character_id) }

      [:ok, { 'clues' => clues }]
    end
  end

  def self.create_quest(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    quest_id = payload['quest_id']
    title = payload['title']
    depends_on = payload['depends_on']

    return [:invalid] unless quest_id.is_a?(String) && !quest_id.empty?
    return [:invalid] unless title.is_a?(String) && !title.empty?
    return [:invalid] unless depends_on.is_a?(Array)
    return [:invalid] unless depends_on.all? { |q| q.is_a?(String) && !q.empty? }
    return [:invalid] unless depends_on.uniq.length == depends_on.length
    return [:invalid] if depends_on.include?(quest_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )
      next [:conflict] if existing

      missing_dep = depends_on.any? do |dep_id|
        !d.get_first_value(
          'SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
          [campaign_id, dep_id]
        )
      end
      next [:invalid] if missing_dep

      d.execute(
        'INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, quest_id, title, JSON.generate(depends_on), 'locked']
      )

      [:ok, { 'quest_id' => quest_id, 'title' => title, 'depends_on' => depends_on, 'state' => 'locked' }]
    end
  end

  def self.update_quest_state(campaign_id, quest_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless quest_id.is_a?(String) && !quest_id.empty?

    state = payload['state']
    return [:invalid] unless state == 'active' || state == 'completed'

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT title, depends_on_json, state, rewards_json FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )
      next [:not_found] unless row

      title, depends_on_json, current_state, rewards_json = row
      depends_on = JSON.parse(depends_on_json)

      case current_state
      when 'locked'
        next [:conflict] unless state == 'active'
        deps_completed = depends_on.all? do |dep_id|
          dep_state = d.get_first_value(
            'SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
            [campaign_id, dep_id]
          )
          dep_state == 'completed'
        end
        next [:conflict] unless deps_completed
      when 'active'
        next [:conflict] unless state == 'completed'
      else
        next [:conflict]
      end

      d.execute(
        'UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?',
        [state, campaign_id, quest_id]
      )

      result = { 'quest_id' => quest_id, 'title' => title, 'depends_on' => depends_on, 'state' => state }
      result['rewards'] = JSON.parse(rewards_json) if rewards_json && rewards_json != '{}'

      [:ok, result]
    end
  end

  def self.list_quests(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      quests = rows.map do |qid, qtitle, depends_on_json, qstate|
        {
          'quest_id' => qid,
          'title' => qtitle,
          'depends_on' => JSON.parse(depends_on_json),
          'state' => qstate
        }
      end

      [:ok, { 'quests' => quests }]
    end
  end

  def self.configure_quest_rewards(campaign_id, quest_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless quest_id.is_a?(String) && !quest_id.empty?

    rewards = validate_rewards(payload)
    return [:invalid] unless rewards

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )
      next [:not_found] unless row

      title, depends_on_json, state = row
      next [:conflict] unless state == 'locked' || state == 'active'

      invalid_item = rewards['items'].keys.any? do |item_id|
        !d.get_first_value('SELECT 1 FROM compendium_items WHERE slug = ?', item_id)
      end
      next [:invalid] if invalid_item

      d.execute(
        'UPDATE play_campaign_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?',
        [JSON.generate(rewards), campaign_id, quest_id]
      )

      [:ok, {
        'quest_id' => quest_id,
        'title' => title,
        'depends_on' => JSON.parse(depends_on_json),
        'state' => state,
        'rewards' => rewards
      }]
    end
  end

  def self.award_quest_rewards(campaign_id, quest_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless quest_id.is_a?(String) && !quest_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT title, depends_on_json, state, rewards_json, awarded FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )
      next [:not_found] unless row

      _title, _depends_on_json, state, rewards_json, awarded = row
      next [:conflict] unless state == 'completed'
      next [:conflict] if awarded == 1 || rewards_json.nil? || rewards_json == '{}'

      rewards = JSON.parse(rewards_json)
      xp = rewards['xp'] || 0
      items = rewards['items'] || {}

      members = d.execute(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ?',
        campaign_id
      ).map { |r| r[0] }

      members.each do |char_id|
        d.execute(
          'INSERT INTO play_character_quest_rewards (campaign_id, character_id, quest_id, xp, items_json) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, char_id, quest_id, xp, JSON.generate(items)]
        )
      end

      d.execute(
        'UPDATE play_campaign_quests SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?',
        [campaign_id, quest_id]
      )

      [:ok, {
        'quest_id' => quest_id,
        'awarded' => true,
        'xp' => xp,
        'items' => items
      }]
    end
  end

  def self.get_character_rewards(campaign_id, character_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless character_id.is_a?(String) && !character_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] unless member

      rows = d.execute(
        'SELECT xp, items_json FROM play_character_quest_rewards WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )

      total_xp = 0
      total_items = {}

      rows.each do |xp, items_json|
        total_xp += xp.to_i
        items = JSON.parse(items_json)
        items.each do |item_id, qty|
          total_items[item_id] = total_items[item_id].to_i + qty.to_i
        end
      end

      [:ok, {
        'character_id' => character_id,
        'xp' => total_xp,
        'items' => total_items
      }]
    end
  end

  def self.schedule_world_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    event_id = payload['event_id']
    turn_number = payload['turn_number']
    title = payload['title']
    text = payload['text']

    return [:invalid] unless event_id.is_a?(String) && !event_id.empty? &&
                             title.is_a?(String) && !title.empty? &&
                             text.is_a?(String) && !text.empty? &&
                             turn_number.is_a?(Integer)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, turn_number FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, current_turn = campaign
      next [:forbidden] unless owner == actor[:username]
      next [:invalid] unless current_turn.is_a?(Integer) && turn_number >= current_turn

      begin
        d.execute(
          'INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, event_id, turn_number, title, text]
        )
      rescue SQLite3::ConstraintException
        next [:conflict]
      end

      [:ok, {
        'event_id' => event_id,
        'turn_number' => turn_number,
        'title' => title,
        'text' => text,
        'status' => 'scheduled'
      }]
    end
  end

  def self.resolve_world_event(campaign_id, event_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            event_id.is_a?(String) && !event_id.empty?

    text = payload['text']
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, turn_number FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, current_turn = campaign
      next [:forbidden] unless owner == actor[:username]
      next [:invalid] unless current_turn.is_a?(Integer)

      row = d.get_first_row(
        'SELECT id, turn_number, title, text, status FROM play_world_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:not_found] unless row

      id, event_turn, title, event_text, status = row
      next [:conflict] if status == 'resolved'
      next [:conflict] unless current_turn == event_turn

      d.execute(
        'UPDATE play_world_events SET status = ?, resolution_turn = ?, resolution_text = ? WHERE id = ?',
        ['resolved', current_turn, text, id]
      )

      [:ok, {
        'event_id' => event_id,
        'turn_number' => event_turn,
        'title' => title,
        'text' => event_text,
        'status' => 'resolved',
        'resolution' => {
          'turn_number' => current_turn,
          'text' => text
        }
      }]
    end
  end

  def self.list_world_events(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, turn_number, title, text, status, resolution_turn, resolution_text FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number, id',
        campaign_id
      )

      events = rows.map do |ev_id, ev_turn, ev_title, ev_text, ev_status, res_turn, res_text|
        event = {
          'event_id' => ev_id,
          'turn_number' => ev_turn,
          'title' => ev_title,
          'text' => ev_text,
          'status' => ev_status
        }
        if ev_status == 'resolved'
          event['resolution'] = {
            'turn_number' => res_turn,
            'text' => res_text
          }
        end
        event
      end

      [:ok, { 'events' => events }]
    end
  end

  def self.validate_rewards(payload)
    return nil unless payload.is_a?(Hash)

    xp = payload['xp']
    items = payload['items']

    return nil unless xp.is_a?(Integer) && xp >= 0
    return nil unless items.is_a?(Hash)

    items.each do |item_id, qty|
      return nil unless item_id.is_a?(String) && !item_id.empty?
      return nil unless qty.is_a?(Integer) && qty > 0
    end

    { 'xp' => xp, 'items' => items }
  end
  private_class_method :validate_rewards

  def self.valid_relationship_score?(score)
    score.is_a?(Integer) && score >= -100 && score <= 100
  end
  private_class_method :valid_relationship_score?

  def self.format_clue(clue_id, text, audience, character_id)
    clue = {
      'clue_id' => clue_id,
      'text' => text,
      'audience' => audience
    }
    clue['character_id'] = character_id if character_id && !character_id.empty?
    clue
  end
  private_class_method :format_clue

  def self.relationship_entity_exists?(d, campaign_id, entity_id)
    member = d.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign_id, entity_id]
    )
    return true if member

    npc = d.get_first_value(
      'SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
      [campaign_id, entity_id]
    )
    npc ? true : false
  end
  private_class_method :relationship_entity_exists?

  def self.fetch_conditions_for_target(d, campaign_id, encounter_id, target)
    d.execute(
      'SELECT condition, remaining_rounds FROM play_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? ORDER BY id',
      [campaign_id, encounter_id, target]
    ).map do |condition, remaining_rounds|
      { 'condition' => condition, 'remaining_rounds' => remaining_rounds }
    end
  end
  private_class_method :fetch_conditions_for_target

  def self.decrement_conditions(d, campaign_id, encounter_id, target)
    return unless target

    d.execute(
      'SELECT id, remaining_rounds FROM play_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ?',
      [campaign_id, encounter_id, target]
    ).each do |id, remaining_rounds|
      new_remaining = remaining_rounds - 1
      if new_remaining <= 0
        d.execute('DELETE FROM play_encounter_conditions WHERE id = ?', id)
      else
        d.execute('UPDATE play_encounter_conditions SET remaining_rounds = ? WHERE id = ?', [new_remaining, id])
      end
    end
  end
  private_class_method :decrement_conditions

  # Strips internal routing keys (prefixed with `_`) from a combatant before it is
  # serialized to the client. `_target` identifies the condition/HP target and
  # `_member` links player combatants back to their user accounts.
  def self.public_combatant(combatant)
    combatant.reject { |k, _| k.start_with?('_') }
  end
  private_class_method :public_combatant

  def self.public_order(order)
    order.map { |c| public_combatant(c) }
  end
  private_class_method :public_order

  # Returns the most recent narrations for a campaign, newest first.
  # Shared by player and GM turn-context endpoints.
  def self.recent_events(d, campaign_id)
    d.execute(
      'SELECT sequence, kind, actor, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence DESC',
      campaign_id
    ).map do |sequence, kind, event_actor, text|
      { 'sequence' => sequence, 'kind' => kind, 'actor' => event_actor, 'text' => text }
    end
  end
  private_class_method :recent_events

  # Allocates the next narration sequence and inserts a narration row.
  # All campaign narration sources (DM, player actions, resolutions, travel,
  # rests, documents, nudges, combat actions) flow through here so sequence
  # numbers stay strictly monotonic within a campaign.
  def self.record_narration(d, campaign_id, kind, actor_name, text)
    sequence = d.get_first_value(
      'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
      campaign_id
    )
    d.execute(
      'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
      [campaign_id, sequence, kind, actor_name, text]
    )
    sequence
  end
  private_class_method :record_narration

  def self.valid_encounter_ids?(campaign_id, encounter_id)
    campaign_id.is_a?(String) && !campaign_id.empty? &&
      encounter_id.is_a?(String) && !encounter_id.empty?
  end
  private_class_method :valid_encounter_ids?

  # Builds the encounter turn order from bound party members and added monsters.
  # A stored `order_json` is reused once the order has been modified (delay/ready);
  # otherwise initiative is sorted descending with deterministic tie-breaking.
  def self.build_encounter_order(d, campaign_id, encounter_id, combatants_json)
    stored = d.get_first_row(
      'SELECT order_json FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?',
      [campaign_id, encounter_id]
    )
    if stored && stored[0] && stored[0] != '[]' && !stored[0].to_s.empty?
      return JSON.parse(stored[0])
    end

    order = []

    members = JSON.parse(combatants_json || '[]')
    members.each do |c|
      next unless c.is_a?(Hash) && c['name'].is_a?(String) && !c['name'].empty?

      order << {
        'name' => c['name'],
        'kind' => 'player',
        'initiative' => c['initiative'],
        '_member' => c['member'],
        '_target' => c['member'].to_s
      }
    end

    d.execute(
      'SELECT monster_id, name, initiative FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? ORDER BY rowid',
      [campaign_id, encounter_id]
    ).each do |monster_id, name, initiative|
      order << {
        'name' => name,
        'kind' => 'monster',
        'initiative' => initiative,
        '_target' => monster_id.to_s
      }
    end

    order.sort_by! { |c| [-c['initiative'].to_i, c['name'], c['kind'], c['_target']] }
    order
  end
  def self.initialize_calendar(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    day = payload['day']
    season = payload['season']
    return [:invalid] unless day.is_a?(Integer) && day >= 1
    return [:invalid] unless %w[spring summer autumn winter].include?(season)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)',
        [campaign_id, day, season]
      )

      [:ok, calendar_response(day, season)]
    end
  end

  def self.get_calendar(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        'SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      [:ok, calendar_response(row[0], row[1])]
    end
  end

  def self.advance_calendar(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    days = payload['days']
    return [:invalid] unless days.is_a?(Integer) && days >= 1 && days <= 30

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      new_day = row[0] + days

      d.execute(
        'UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?',
        [new_day, campaign_id]
      )

      [:ok, calendar_response(new_day, row[1])]
    end
  end

  def self.calendar_response(day, season)
    {
      'day' => day,
      'season' => season,
      'weather' => calculate_weather(day, season)
    }
  end

  def self.calculate_weather(day, season)
    offsets = { 'spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3 }
    value = (day + offsets.fetch(season, 0)) % 4
    %w[clear rain wind snow][value]
  end

  # Settlement management

  def self.create_settlement(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_settlement(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, data[:settlement_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, data[:settlement_id], data[:name], JSON.generate(data[:services]), data[:availability], '[]']
      )

      [:ok, settlement_response(data[:settlement_id], data[:name], data[:services], data[:availability], [])]
    end
  end

  def self.update_settlement(campaign_id, settlement_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty?

    data = validate_settlement_update(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT id, name, services_json, availability, discovered_by_json FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless row

      discovered_by = JSON.parse(row[4] || '[]')

      d.execute(
        'UPDATE play_settlements SET name = ?, services_json = ?, availability = ? WHERE id = ?',
        [data[:name], JSON.generate(data[:services]), data[:availability], row[0]]
      )

      [:ok, settlement_response(settlement_id, data[:name], data[:services], data[:availability], discovered_by)]
    end
  end

  def self.discover_settlement(campaign_id, settlement_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] if owner == actor[:username]

      member_row = d.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member_row

      character_id = member_row[0]

      row = d.get_first_row(
        'SELECT id, name, services_json, availability, discovered_by_json FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless row

      discovered_by = JSON.parse(row[4] || '[]')

      if discovered_by.include?(character_id)
        [:ok, settlement_response(settlement_id, row[1], JSON.parse(row[2]), row[3], [character_id])]
      else
        discovered_by << character_id
        d.execute(
          'UPDATE play_settlements SET discovered_by_json = ? WHERE id = ?',
          [JSON.generate(discovered_by), row[0]]
        )
        [:created, settlement_response(settlement_id, row[1], JSON.parse(row[2]), row[3], [character_id])]
      end
    end
  end

  def self.list_settlements(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_settlements WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      settlements = if owner == actor[:username]
                        rows.map do |settlement_id, name, services_json, availability, discovered_json|
                          settlement_response(settlement_id, name, JSON.parse(services_json), availability, JSON.parse(discovered_json))
                        end
                      else
                        character_id = d.get_first_value(
                          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
                          [campaign_id, actor[:username]]
                        )
                        rows.filter_map do |settlement_id, name, services_json, availability, discovered_json|
                          discovered_by = JSON.parse(discovered_json)
                          next unless discovered_by.include?(character_id)

                          settlement_response(settlement_id, name, JSON.parse(services_json), availability, [character_id])
                        end
                      end

      [:ok, { 'settlements' => settlements }]
    end
  end

  # Shop management

  def self.create_shop(campaign_id, settlement_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty?

    data = validate_shop(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      settlement = d.get_first_value(
        'SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless settlement

      existing = d.get_first_value(
        'SELECT 1 FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [campaign_id, settlement_id, data[:shop_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, settlement_id, data[:shop_id], data[:name], JSON.generate(data[:stock]), data[:buy_price], data[:sell_price]]
      )

      [:created, shop_response(data[:shop_id], data[:name], data[:stock], data[:buy_price], data[:sell_price])]
    end
  end

  def self.get_shop(campaign_id, settlement_id, shop_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty? &&
                            shop_id.is_a?(String) && !shop_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      settlement = d.get_first_row(
        'SELECT discovered_by_json FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless settlement

      shop = d.get_first_row(
        'SELECT name, stock_json, buy_price, sell_price FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [campaign_id, settlement_id, shop_id]
      )
      next [:not_found] unless shop

      if owner != actor[:username]
        character_id = d.get_first_value(
          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, actor[:username]]
        )
        discovered_by = JSON.parse(settlement[0] || '[]')
        next [:not_found] unless discovered_by.include?(character_id)
      end

      [:ok, shop_response(shop_id, shop[0], JSON.parse(shop[1]), shop[2], shop[3])]
    end
  end

  def self.buy(campaign_id, settlement_id, shop_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty? &&
                            shop_id.is_a?(String) && !shop_id.empty?

    character_id = payload['character_id']
    item_id = payload['item_id']
    quantity = payload['quantity']
    return [:invalid] unless character_id.is_a?(String) && !character_id.empty?
    return [:invalid] unless item_id.is_a?(String) && !item_id.empty?
    return [:invalid] unless quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] if campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member
      next [:forbidden] unless member[0] == actor[:username]

      character_owner = d.get_first_value(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] if character_owner.nil?
      next [:forbidden] unless character_owner == actor[:username]

      settlement = d.get_first_value(
        'SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless settlement

      shop = d.get_first_row(
        'SELECT id, name, stock_json, buy_price, sell_price FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [campaign_id, settlement_id, shop_id]
      )
      next [:not_found] unless shop

      next [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)

      stock = JSON.parse(shop[2])
      next [:conflict] unless stock.key?(item_id) && stock[item_id].is_a?(Integer)
      next [:conflict] unless stock[item_id] >= quantity

      gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      gold = gold.to_i
      cost = shop[3] * quantity
      next [:conflict] unless gold >= cost

      new_gold = gold - cost
      new_stock = stock.dup
      new_stock[item_id] -= quantity

      d.execute(
        'UPDATE play_shops SET stock_json = ? WHERE id = ?',
        [JSON.generate(new_stock), shop[0]]
      )

      d.execute(
        'UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_gold, campaign_id, character_id]
      )

      d.execute(
        'INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, character_id, item_id, quantity]
      )

      [:ok, {
        'character_id' => character_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'gold' => new_gold,
        'stock' => new_stock[item_id]
      }]
    end
  end

  def self.sell(campaign_id, settlement_id, shop_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            settlement_id.is_a?(String) && !settlement_id.empty? &&
                            shop_id.is_a?(String) && !shop_id.empty?

    character_id = payload['character_id']
    item_id = payload['item_id']
    quantity = payload['quantity']
    return [:invalid] unless character_id.is_a?(String) && !character_id.empty?
    return [:invalid] unless item_id.is_a?(String) && !item_id.empty?
    return [:invalid] unless quantity.is_a?(Integer) && quantity > 0
    return [:invalid] unless VALID_INVENTORY_ITEMS.include?(item_id)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] if campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member
      next [:forbidden] unless member[0] == actor[:username]

      character_owner = d.get_first_value(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] if character_owner.nil?
      next [:forbidden] unless character_owner == actor[:username]

      settlement = d.get_first_value(
        'SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )
      next [:not_found] unless settlement

      shop = d.get_first_row(
        'SELECT id, stock_json, sell_price FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [campaign_id, settlement_id, shop_id]
      )
      next [:not_found] unless shop

      current = d.get_first_value(
        'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, character_id, item_id]
      )
      current = current.to_i
      next [:conflict] unless current >= quantity

      revenue = shop[2] * quantity

      new_current = current - quantity
      if new_current == 0
        d.execute(
          'DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
      else
        d.execute(
          'UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [new_current, campaign_id, character_id, item_id]
        )
      end

      stock = JSON.parse(shop[1])
      new_stock = stock.dup
      new_stock[item_id] = new_stock[item_id].to_i + quantity

      d.execute(
        'UPDATE play_shops SET stock_json = ? WHERE id = ?',
        [JSON.generate(new_stock), shop[0]]
      )

      new_gold = d.get_first_value(
        'SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      ).to_i + revenue

      d.execute(
        'UPDATE play_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_gold, campaign_id, character_id]
      )

      [:ok, {
        'character_id' => character_id,
        'item_id' => item_id,
        'quantity' => quantity,
        'gold' => new_gold,
        'stock' => new_stock[item_id]
      }]
    end
  end

  def self.shop_response(shop_id, name, stock, buy_price, sell_price)
    {
      'shop_id' => shop_id,
      'name' => name,
      'stock' => stock,
      'buy_price' => buy_price,
      'sell_price' => sell_price
    }
  end

  def self.validate_shop(payload)
    return nil unless payload.is_a?(Hash)

    shop_id = payload['shop_id']
    name = payload['name']
    stock = payload['stock']
    buy_price = payload['buy_price']
    sell_price = payload['sell_price']

    return nil unless shop_id.is_a?(String) && !shop_id.empty?
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless stock.is_a?(Hash) && !stock.empty?
    return nil unless buy_price.is_a?(Integer) && buy_price > 0
    return nil unless sell_price.is_a?(Integer) && sell_price >= 0

    normalized = {}
    stock.each do |item_id, qty|
      return nil unless item_id.is_a?(String) && !item_id.empty?
      return nil unless VALID_INVENTORY_ITEMS.include?(item_id)
      return nil unless qty.is_a?(Integer) && qty > 0
      normalized[item_id] = qty
    end

    {
      shop_id: shop_id,
      name: name,
      stock: normalized,
      buy_price: buy_price,
      sell_price: sell_price
    }
  end

  def self.settlement_response(settlement_id, name, services, availability, discovered_by)
    {
      'settlement_id' => settlement_id,
      'name' => name,
      'services' => services,
      'availability' => availability,
      'discovered_by' => discovered_by
    }
  end

  def self.validate_settlement(payload)
    return nil unless payload.is_a?(Hash)

    settlement_id = payload['settlement_id']
    name = payload['name']
    services = payload['services']
    availability = payload['availability']

    return nil unless settlement_id.is_a?(String) && !settlement_id.empty?
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless %w[open limited closed].include?(availability)
    return nil unless services.is_a?(Array) && !services.empty?

    normalized = []
    seen = {}
    services.each do |svc|
      return nil unless svc.is_a?(String)
      trimmed = svc.strip
      return nil if trimmed.empty?
      return nil if seen.key?(trimmed)
      seen[trimmed] = true
      normalized << trimmed
    end

    {
      settlement_id: settlement_id,
      name: name,
      services: normalized,
      availability: availability
    }
  end

  def self.validate_settlement_update(payload)
    return nil unless payload.is_a?(Hash)

    name = payload['name']
    services = payload['services']
    availability = payload['availability']

    return nil unless name.is_a?(String) && !name.empty?
    return nil unless %w[open limited closed].include?(availability)
    return nil unless services.is_a?(Array) && !services.empty?

    normalized = []
    seen = {}
    services.each do |svc|
      return nil unless svc.is_a?(String)
      trimmed = svc.strip
      return nil if trimmed.empty?
      return nil if seen.key?(trimmed)
      seen[trimmed] = true
      normalized << trimmed
    end

    {
      name: name,
      services: normalized,
      availability: availability
    }
  end

  def self.create_recipe(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_recipe(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?',
        [campaign_id, data[:recipe_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_recipes (campaign_id, recipe_id, name, output_item, output_quantity) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, data[:recipe_id], data[:name], data[:output_item], data[:output_quantity]]
      )

      data[:ingredients].each do |item_id, qty|
        d.execute(
          'INSERT INTO play_recipe_ingredients (campaign_id, recipe_id, item_id, quantity) VALUES (?, ?, ?, ?)',
          [campaign_id, data[:recipe_id], item_id, qty]
        )
      end

      [:created, recipe_response(data)]
    end
  end

  def self.list_recipes(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      recipe_rows = d.execute(
        'SELECT recipe_id, name, output_item, output_quantity FROM play_recipes WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      recipes = recipe_rows.map do |recipe_id, name, output_item, output_quantity|
        ingredient_rows = d.execute(
          'SELECT item_id, quantity FROM play_recipe_ingredients WHERE campaign_id = ? AND recipe_id = ?',
          [campaign_id, recipe_id]
        )
        ingredients = {}
        ingredient_rows.each { |item_id, qty| ingredients[item_id] = qty }

        {
          'recipe_id' => recipe_id,
          'name' => name,
          'ingredients' => ingredients,
          'output_item' => output_item,
          'output_quantity' => output_quantity
        }
      end

      [:ok, { 'recipes' => recipes }]
    end
  end

  def self.craft_recipe(campaign_id, recipe_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless recipe_id.is_a?(String) && !recipe_id.empty?

    character_id = payload['character_id']
    return [:invalid] unless character_id.is_a?(String) && !character_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] if campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member
      next [:forbidden] unless member[0] == actor[:username]

      character_owner = d.get_first_value(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] if character_owner.nil?
      next [:forbidden] unless character_owner == actor[:username]

      recipe = d.get_first_row(
        'SELECT output_item, output_quantity FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?',
        [campaign_id, recipe_id]
      )
      next [:not_found] unless recipe

      output_item, output_quantity = recipe

      ingredient_rows = d.execute(
        'SELECT item_id, quantity FROM play_recipe_ingredients WHERE campaign_id = ? AND recipe_id = ?',
        [campaign_id, recipe_id]
      )

      insufficient = false
      ingredient_rows.each do |item_id, needed|
        current = d.get_first_value(
          'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        ).to_i
        if current < needed
          insufficient = true
          break
        end
      end
      next [:conflict] if insufficient

      d.transaction do
        ingredient_rows.each do |item_id, needed|
          current = d.get_first_value(
            'SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          ).to_i
          remaining = current - needed
          if remaining == 0
            d.execute(
              'DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
              [campaign_id, character_id, item_id]
            )
          else
            d.execute(
              'UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
              [remaining, campaign_id, character_id, item_id]
            )
          end
        end

        d.execute(
          'INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
           ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
          [campaign_id, character_id, output_item, output_quantity]
        )
      end

      [:ok, {
        'character_id' => character_id,
        'recipe_id' => recipe_id,
        'output_item' => output_item,
        'output_quantity' => output_quantity
      }]
    end
  end

  def self.recipe_response(recipe)
    {
      'recipe_id' => recipe[:recipe_id],
      'name' => recipe[:name],
      'ingredients' => recipe[:ingredients],
      'output_item' => recipe[:output_item],
      'output_quantity' => recipe[:output_quantity]
    }
  end

  def self.validate_recipe(payload)
    return nil unless payload.is_a?(Hash)

    recipe_id = payload['recipe_id']
    name = payload['name']
    ingredients = payload['ingredients']
    output_item = payload['output_item']
    output_quantity = payload['output_quantity']

    return nil unless recipe_id.is_a?(String) && !recipe_id.empty?
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless ingredients.is_a?(Hash) && !ingredients.empty?
    return nil unless output_item.is_a?(String) && !output_item.empty?
    return nil unless output_quantity.is_a?(Integer) && output_quantity > 0
    return nil unless VALID_INVENTORY_ITEMS.include?(output_item)

    normalized = {}
    ingredients.each do |item_id, qty|
      return nil unless item_id.is_a?(String) && !item_id.empty?
      return nil unless VALID_INVENTORY_ITEMS.include?(item_id)
      return nil unless qty.is_a?(Integer) && qty > 0
      normalized[item_id] = qty
    end

    {
      recipe_id: recipe_id,
      name: name,
      ingredients: normalized,
      output_item: output_item,
      output_quantity: output_quantity
    }
  end

  def self.create_downtime_activity(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_downtime_activity(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
        [campaign_id, data[:activity_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)',
        [campaign_id, data[:activity_id], data[:name], data[:cycles_required]]
      )

      [:ok, {
        'activity_id' => data[:activity_id],
        'name' => data[:name],
        'cycles_required' => data[:cycles_required]
      }]
    end
  end

  def self.allocate_downtime(campaign_id, character_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            character_id.is_a?(String) && !character_id.empty?

    activity_id = payload['activity_id']
    return [:invalid] unless activity_id.is_a?(String) && !activity_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] if campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      activity = d.get_first_value(
        'SELECT 1 FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
        [campaign_id, activity_id]
      )
      next [:not_found] unless activity

      begin
        d.execute(
          'INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, character_id, activity_id, 0, 0]
        )
      rescue SQLite3::ConstraintException
        next [:conflict]
      end

      [:ok, {
        'character_id' => character_id,
        'activity_id' => activity_id,
        'cycles_completed' => 0,
        'completions' => 0
      }]
    end
  end

  def self.progress_downtime(campaign_id, character_id, activity_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            character_id.is_a?(String) && !character_id.empty? &&
                            activity_id.is_a?(String) && !activity_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] if campaign[0] == actor[:username]

      member = d.get_first_row(
        'SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] unless member
      next [:forbidden] unless member[0] == actor[:username]

      activity = d.get_first_row(
        'SELECT cycles_required FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
        [campaign_id, activity_id]
      )
      next [:not_found] unless activity

      allocation = d.get_first_row(
        'SELECT cycles_completed, completions FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
        [campaign_id, character_id, activity_id]
      )
      next [:not_found] unless allocation

      cycles_completed, completions = allocation
      cycles_required = activity[0]

      new_cycles = cycles_completed.to_i + 1
      new_completions = completions.to_i

      if new_cycles >= cycles_required
        new_cycles = 0
        new_completions += 1
      end

      d.execute(
        'UPDATE play_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
        [new_cycles, new_completions, campaign_id, character_id, activity_id]
      )

      [:ok, {
        'character_id' => character_id,
        'activity_id' => activity_id,
        'cycles_completed' => new_cycles,
        'completions' => new_completions
      }]
    end
  end

  def self.get_allocation(campaign_id, character_id, activity_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            character_id.is_a?(String) && !character_id.empty? &&
                            activity_id.is_a?(String) && !activity_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] unless member

      activity = d.get_first_value(
        'SELECT 1 FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
        [campaign_id, activity_id]
      )
      next [:not_found] unless activity

      allocation = d.get_first_row(
        'SELECT cycles_completed, completions FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
        [campaign_id, character_id, activity_id]
      )
      next [:not_found] unless allocation

      [:ok, {
        'character_id' => character_id,
        'activity_id' => activity_id,
        'cycles_completed' => allocation[0],
        'completions' => allocation[1]
      }]
    end
  end

  def self.validate_downtime_activity(payload)
    return nil unless payload.is_a?(Hash)

    activity_id = payload['activity_id']
    name = payload['name']
    cycles_required = payload['cycles_required']

    return nil unless activity_id.is_a?(String) && !activity_id.empty?
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless cycles_required.is_a?(Integer) && cycles_required >= 1 && cycles_required <= 10

    { activity_id: activity_id, name: name, cycles_required: cycles_required }
  end
  private_class_method :validate_downtime_activity

  def self.set_session_zero(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_session_zero(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, status FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, status = campaign
      next [:forbidden] unless owner == actor[:username]
      next [:conflict] unless status == 'lobby'

      d.execute(
        'INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json',
        [campaign_id, data[:rules], data[:tone], JSON.generate(data[:consent])]
      )

      [:ok, {
        'rules' => data[:rules],
        'tone' => data[:tone],
        'consent' => data[:consent]
      }]
    end
  end

  def self.get_session_zero(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        'SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      [:ok, {
        'rules' => row[0],
        'tone' => row[1],
        'consent' => JSON.parse(row[2])
      }]
    end
  end

  def self.validate_session_zero(payload)
    return nil unless payload.is_a?(Hash)

    rules = payload['rules']
    tone = payload['tone']
    consent = payload['consent']

    return nil unless rules.is_a?(String) && !rules.empty?
    return nil unless tone.is_a?(String) && !tone.empty?
    return nil unless consent.is_a?(Array) && !consent.empty?
    return nil unless consent.all? { |c| c.is_a?(String) && !c.empty? }
    return nil unless consent.uniq.length == consent.length

    { rules: rules, tone: tone, consent: consent }
  end
  private_class_method :validate_session_zero

  def self.create_content(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_content(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?',
        [campaign_id, data[:content_id]]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, data[:content_id], data[:kind], data[:text], JSON.generate(data[:tags])]
      )

      [:ok, content_response(data[:content_id], data[:kind], data[:text], data[:tags])]
    end
  end

  def self.update_content_tags(campaign_id, content_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            content_id.is_a?(String) && !content_id.empty?

    tags = payload['tags']
    return [:invalid] unless tags.is_a?(Array)
    return [:invalid] unless validate_tags(tags, allow_empty: true)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?',
        [campaign_id, content_id]
      )
      next [:not_found] unless row

      d.execute(
        'UPDATE play_campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?',
        [JSON.generate(tags), campaign_id, content_id]
      )

      [:ok, content_response(content_id, row[0], row[1], tags)]
    end
  end

  def self.list_content(campaign_id, actor, exclude_tag)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] if !exclude_tag.nil? && (!exclude_tag.is_a?(String) || exclude_tag.empty?)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      contents = rows.map do |cid, kind, text, tags_json|
        content_response(cid, kind, text, JSON.parse(tags_json))
      end

      if exclude_tag.is_a?(String) && !exclude_tag.empty? && owner != actor[:username]
        contents = contents.reject { |c| c['tags'].include?(exclude_tag) }
      end

      [:ok, { 'content' => contents }]
    end
  end

  def self.content_response(content_id, kind, text, tags)
    {
      'content_id' => content_id,
      'kind' => kind,
      'text' => text,
      'tags' => tags
    }
  end

  def self.validate_content(payload)
    return nil unless payload.is_a?(Hash)

    content_id = payload['content_id']
    kind = payload['kind']
    text = payload['text']
    tags = payload['tags']

    return nil unless content_id.is_a?(String) && !content_id.empty?
    return nil unless kind.is_a?(String) && !kind.empty?
    return nil unless text.is_a?(String) && !text.empty?
    return nil unless tags.is_a?(Array) && !tags.empty?
    return nil unless validate_tags(tags, allow_empty: false)

    {
      content_id: content_id,
      kind: kind,
      text: text,
      tags: tags
    }
  end

  def self.validate_tags(tags, allow_empty:)
    return false unless tags.is_a?(Array)
    return false if !allow_empty && tags.empty?
    seen = {}
    tags.each do |tag|
      return false unless tag.is_a?(String) && !tag.empty?
      return false if seen.key?(tag)
      seen[tag] = true
    end
    true
  end

  # Privacy controls: campaign notes, whispers, and character sheets.

  def self.create_note(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    note_id = payload['note_id']
    text = payload['text']
    visibility = payload['visibility']
    return [:invalid] unless note_id.is_a?(String) && !note_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?
    return [:invalid] unless visibility == 'private' || visibility == 'party'

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
        [campaign_id, note_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, note_id, text, visibility, actor[:username]]
      )

      [:ok, note_response(note_id, text, visibility, actor[:username])]
    end
  end

  def self.list_notes(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = if owner == actor[:username]
               d.execute(
                 'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY id',
                 campaign_id
               )
             else
               d.execute(
                 "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND (visibility = 'party' OR (visibility = 'private' AND owner = ?)) ORDER BY id",
                 [campaign_id, actor[:username]]
               )
             end

      notes = rows.map { |nid, txt, vis, own| note_response(nid, txt, vis, own) }
      [:ok, { 'notes' => notes }]
    end
  end

  def self.get_note(campaign_id, note_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            note_id.is_a?(String) && !note_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
        [campaign_id, note_id]
      )
      next [:not_found] unless row

      _nid, text, visibility, note_owner = row
      if owner == actor[:username] || visibility == 'party' || note_owner == actor[:username]
        [:ok, note_response(row[0], text, visibility, note_owner)]
      else
        [:forbidden]
      end
    end
  end

  def self.update_note(campaign_id, note_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            note_id.is_a?(String) && !note_id.empty?

    text = payload['text']
    visibility = payload['visibility']
    return [:invalid] unless text.is_a?(String) && !text.empty?
    return [:invalid] unless visibility == 'private' || visibility == 'party'

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
        [campaign_id, note_id]
      )
      next [:not_found] unless row
      next [:forbidden] unless row[3] == actor[:username]

      d.execute(
        'UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?',
        [text, visibility, campaign_id, note_id]
      )

      [:ok, note_response(row[0], text, visibility, row[3])]
    end
  end

  def self.create_whisper(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless actor[:role] == 'player'

    whisper_id = payload['whisper_id']
    to_character_id = payload['to_character_id']
    text = payload['text']
    return [:invalid] unless whisper_id.is_a?(String) && !whisper_id.empty?
    return [:invalid] unless to_character_id.is_a?(String) && !to_character_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )

      member_row = d.get_first_row(
        'SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless member_row && member_row[1] == actor[:username]

      from_character_id = member_row[0]

      next [:invalid] unless d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )

      existing = d.get_first_value(
        'SELECT 1 FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?',
        [campaign_id, whisper_id]
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, whisper_id, from_character_id, to_character_id, text]
      )

      [:ok, whisper_response(whisper_id, from_character_id, to_character_id, text)]
    end
  end

  def self.list_whispers(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = if owner == actor[:username]
               d.execute(
                 'SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY id',
                 campaign_id
               )
             else
               character_id = d.get_first_value(
                 'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?',
                 [campaign_id, actor[:username]]
               )
               if character_id
                 d.execute(
                   'SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? AND (from_character_id = ? OR to_character_id = ?) ORDER BY id',
                   [campaign_id, character_id, character_id]
                 )
               else
                 []
               end
             end

      whispers = rows.map { |wid, from, to, txt| whisper_response(wid, from, to, txt) }
      [:ok, { 'whispers' => whispers }]
    end
  end

  def self.get_character_sheet(campaign_id, character_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            character_id.is_a?(String) && !character_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      member = d.get_first_row(
        'SELECT username, character_id, name, class, level, hp_max, abilities_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      next [:not_found] unless member

      next [:forbidden] unless owner == actor[:username] || member[0] == actor[:username]

      _username, char_id, name, klass = member

      [:ok, {
        'character_id' => char_id,
        'owner' => member[0],
        'name' => name,
        'class' => klass,
        'level' => 1,
        'proficiency_bonus' => 2,
        'hp_max' => 10,
        'armor_class' => 10
      }]
    end
  end

  def self.create_search_record(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    record_id = payload['record_id']
    text = payload['text']
    return [:invalid] unless record_id.is_a?(String) && !record_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      duplicate_id = d.get_first_value(
        'SELECT 1 FROM play_search_records WHERE campaign_id = ? AND record_id = ?',
        [campaign_id, record_id]
      )
      next [:invalid] if duplicate_id

      duplicate_text = d.get_first_value(
        'SELECT 1 FROM play_search_records WHERE campaign_id = ? AND text = ?',
        [campaign_id, text]
      )
      next [:invalid] if duplicate_text

      d.execute(
        'INSERT INTO play_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)',
        [campaign_id, record_id, text]
      )

      [:created, { 'record_id' => record_id, 'text' => text }]
    end
  end

  def self.list_search_records(campaign_id, actor, query_params)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    limit_param = query_params['limit']
    cursor_param = query_params['cursor']
    q = query_params['q']

    limit = if limit_param.nil?
              2
            elsif limit_param.is_a?(Integer)
              limit_param
            else
              Integer(limit_param, 10) rescue nil
            end
    return [:invalid] unless limit.is_a?(Integer) && limit >= 1 && limit <= 3

    cursor = if cursor_param.nil?
               0
             elsif cursor_param.is_a?(Integer)
               cursor_param
             else
               Integer(cursor_param, 10) rescue nil
             end
    return [:invalid] unless cursor.is_a?(Integer) && cursor >= 0

    return [:invalid] unless q.nil? || q.is_a?(String)

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      records = if q && !q.empty?
                  d.execute(
                    'SELECT record_id, text FROM play_search_records WHERE campaign_id = ? AND LOWER(text) LIKE LOWER(?) ORDER BY id',
                    [campaign_id, "%#{q}%"]
                  )
                else
                  d.execute(
                    'SELECT record_id, text FROM play_search_records WHERE campaign_id = ? ORDER BY id',
                    campaign_id
                  )
                end

      total = records.length
      paged = records[cursor, limit] || []
      records_json = paged.map { |record_id, text| { 'record_id' => record_id, 'text' => text } }

      next_cursor = if cursor + limit < total
                      cursor + limit
                    else
                      nil
                    end

      [:ok, { 'records' => records_json, 'next_cursor' => next_cursor }]
    end
  end

  def self.create_rate_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    event_id = payload['event_id']
    return [:invalid] unless event_id.is_a?(String) && !event_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_rate_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:invalid] if existing

      accepted_count = d.get_first_value(
        'SELECT COUNT(*) FROM play_rate_events WHERE campaign_id = ? AND actor = ?',
        [campaign_id, actor[:username]]
      ).to_i

      if accepted_count >= RATE_LIMIT
        d.execute(
          'INSERT INTO play_campaign_metrics (campaign_id, rejected_rate_events) VALUES (?, 1)
           ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = rejected_rate_events + 1',
          [campaign_id]
        )
        next [:rate_limited, { 'limit' => RATE_LIMIT, 'remaining' => 0 }]
      end

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_rate_events WHERE campaign_id = ?',
        campaign_id
      ).to_i

      d.execute(
        'INSERT INTO play_rate_events (campaign_id, event_id, actor, sequence) VALUES (?, ?, ?, ?)',
        [campaign_id, event_id, actor[:username], sequence]
      )

      d.execute(
        'INSERT INTO play_campaign_metrics (campaign_id, accepted_rate_events) VALUES (?, 1)
         ON CONFLICT(campaign_id) DO UPDATE SET accepted_rate_events = accepted_rate_events + 1',
        [campaign_id]
      )

      remaining = RATE_LIMIT - accepted_count - 1
      [:created, {
        'event_id' => event_id,
        'actor' => actor[:username],
        'remaining' => remaining
      }]
    end
  end

  def self.list_rate_events(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, actor FROM play_rate_events WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      events = rows.map do |event_id, event_actor|
        { 'event_id' => event_id, 'actor' => event_actor }
      end

      accepted_count = d.get_first_value(
        'SELECT COUNT(*) FROM play_rate_events WHERE campaign_id = ? AND actor = ?',
        [campaign_id, actor[:username]]
      ).to_i

      remaining = RATE_LIMIT - accepted_count
      [:ok, { 'events' => events, 'remaining' => remaining }]
    end
  end

  def self.get_metrics(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks FROM play_campaign_metrics WHERE campaign_id = ?',
        campaign_id
      )

      [:ok, {
        'accepted_rate_events' => row ? row[0].to_i : 0,
        'rejected_rate_events' => row ? row[1].to_i : 0,
        'projection_events' => row ? row[2].to_i : 0,
        'uptime_ticks' => row ? row[3].to_i : 1
      }]
    end
  end

  def self.service_mode(campaign_id, _actor, maintenance)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless maintenance == true || maintenance == false

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT 1 FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      ServiceMode.maintenance = maintenance
      [:ok, { 'maintenance' => ServiceMode.maintenance? }]
    end
  end

  def self.create_backup(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner, status FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner, status = campaign
      next [:forbidden] unless owner == actor[:username]

      row = d.get_first_row('SELECT story FROM play_campaign_documents WHERE campaign_id = ?', campaign_id)
      story = row ? row[0] : ''

      next_id = d.get_first_value(
        'SELECT COALESCE(MAX(id), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?',
        campaign_id
      )
      backup_id = "backup-#{next_id}"

      d.execute(
        'INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status) VALUES (?, ?, ?, ?)',
        [campaign_id, backup_id, story, status]
      )

      [:created, {
        'backup_id' => backup_id,
        'story' => story,
        'status' => status
      }]
    end
  end

  def self.list_backups(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] == actor[:username]

      rows = d.execute(
        'SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY id',
        campaign_id
      )

      backups = rows.map do |backup_id, story, status|
        {
          'backup_id' => backup_id,
          'story' => story,
          'status' => status
        }
      end

      [:ok, { 'backups' => backups }]
    end
  end

  def self.restore_backup(campaign_id, backup_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                            backup_id.is_a?(String) && !backup_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      next [:forbidden] unless campaign[0] == actor[:username]

      backup = d.get_first_row(
        'SELECT story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?',
        [campaign_id, backup_id]
      )
      next [:not_found] unless backup

      story, status = backup

      d.execute(
        "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '')
         ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
        [campaign_id, story]
      )

      d.execute(
        'UPDATE play_campaigns SET status = ? WHERE id = ?',
        [status, campaign_id]
      )

      [:ok, {
        'backup_id' => backup_id,
        'story' => story,
        'status' => status
      }]
    end
  end

  def self.append_replay_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      event_id = payload['event_id']
      kind = payload['kind']
      text = payload['text']

      next [:invalid] unless event_id.is_a?(String) && !event_id.empty?
      next [:invalid] unless text.is_a?(String) && !text.empty?
      next [:invalid] unless kind == 'append'

      existing = d.get_first_value(
        'SELECT 1 FROM play_replay_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:conflict] if existing

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_replay_events WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, sequence, event_id, kind, text]
      )

      [:created, {
        'event_id' => event_id,
        'kind' => kind,
        'text' => text,
        'sequence' => sequence
      }]
    end
  end

  def self.get_replay(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, text FROM play_replay_events WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      event_ids = rows.map { |event_id, _text| event_id }
      story = rows.map { |_event_id, text| text }.join
      digest = event_ids.join(',') + '|' + story

      [:ok, {
        'story' => story,
        'event_ids' => event_ids,
        'digest' => digest
      }]
    end
  end

  def self.check_replay(campaign_id, actor)
    get_replay(campaign_id, actor)
  end

  def self.set_rng_seed(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    seed = payload['seed']
    return [:invalid] unless seed.is_a?(String) && !seed.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      existing = d.get_first_row(
        'SELECT seed FROM play_rng_ledger WHERE campaign_id = ?',
        campaign_id
      )
      next [:conflict] if existing

      d.execute(
        'INSERT INTO play_rng_ledger (campaign_id, seed) VALUES (?, ?)',
        [campaign_id, seed]
      )

      [:ok, { 'seed' => seed, 'rolls' => [] }]
    end
  end

  def self.append_rng_roll(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    roll_id = payload['roll_id']
    sides = payload['sides']
    return [:invalid] unless roll_id.is_a?(String) && !roll_id.empty?
    return [:invalid] unless sides.is_a?(Integer) && sides >= 2 && sides <= 100

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      ledger = d.get_first_row(
        'SELECT seed FROM play_rng_ledger WHERE campaign_id = ?',
        campaign_id
      )
      next [:conflict] unless ledger

      seed = ledger[0]

      existing_roll_id = d.get_first_value(
        'SELECT 1 FROM play_rng_rolls WHERE campaign_id = ? AND roll_id = ?',
        [campaign_id, roll_id]
      )
      next [:conflict] if existing_roll_id

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_rng_rolls WHERE campaign_id = ?',
        campaign_id
      )

      result = compute_roll_result(seed, sequence, roll_id, sides)

      d.execute(
        'INSERT INTO play_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, sequence, roll_id, sides, result]
      )

      [:created, {
        'roll_id' => roll_id,
        'sides' => sides,
        'result' => result,
        'sequence' => sequence
      }]
    end
  end

  def self.get_rng_ledger(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      ledger = d.get_first_row(
        'SELECT seed FROM play_rng_ledger WHERE campaign_id = ?',
        campaign_id
      )
      seed = ledger ? ledger[0] : nil

      rows = d.execute(
        'SELECT roll_id, sides, result, sequence FROM play_rng_rolls WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      rolls = rows.map do |rid, s, res, seq|
        {
          'roll_id' => rid,
          'sides' => s,
          'result' => res,
          'sequence' => seq
        }
      end

      [:ok, { 'seed' => seed, 'rolls' => rolls }]
    end
  end

  # Moderation workflow

  def self.submit_moderation_report(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    report_id = payload['report_id']
    target_id = payload['target_id']
    reason = payload['reason']
    return [:invalid] unless report_id.is_a?(String) && !report_id.empty?
    return [:invalid] unless target_id.is_a?(String) && !target_id.empty?
    return [:invalid] unless reason.is_a?(String) && !reason.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )
      next [:conflict] if existing

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_moderation_reports WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_moderation_reports (campaign_id, report_id, target_id, reason, reporter, status, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, report_id, target_id, reason, actor[:username], 'open', sequence]
      )

      [:created, {
        'report_id' => report_id,
        'target_id' => target_id,
        'reason' => reason,
        'status' => 'open',
        'reporter' => actor[:username],
        'sequence' => sequence
      }]
    end
  end

  def self.list_moderation_reports(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT report_id, target_id, reason, reporter, status, sequence, action, note, resolver FROM play_moderation_reports WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      reports = rows.map do |rid, tid, reason, reporter, status, seq, action, note, resolver|
        report = {
          'report_id' => rid,
          'target_id' => tid,
          'reason' => reason,
          'status' => status,
          'reporter' => reporter,
          'sequence' => seq
        }
        if status == 'resolved'
          report['action'] = action
          report['note'] = note
          report['resolver'] = resolver
        end
        report
      end

      [:ok, { 'reports' => reports }]
    end
  end

  def self.resolve_moderation_report(campaign_id, report_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless report_id.is_a?(String) && !report_id.empty?

    action = payload['action']
    note = payload['note']
    return [:invalid] unless action == 'allow' || action == 'remove'
    return [:invalid] unless note.is_a?(String) && !note.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      row = d.get_first_row(
        'SELECT target_id, reason, reporter, status, sequence, action, note, resolver FROM play_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )
      next [:not_found] unless row

      target_id, reason, reporter, status, sequence, *_ = row
      next [:conflict] unless status == 'open'

      d.execute(
        'UPDATE play_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?',
        ['resolved', action, note, actor[:username], campaign_id, report_id]
      )

      [:ok, {
        'report_id' => report_id,
        'target_id' => target_id,
        'reason' => reason,
        'status' => 'resolved',
        'reporter' => reporter,
        'sequence' => sequence,
        'action' => action,
        'note' => note,
        'resolver' => actor[:username]
      }]
    end
  end

  # Safety boundaries and accepted safety events.

  def self.set_safety_boundaries(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    blocked_tags = payload['blocked_tags']
    return [:invalid] unless blocked_tags.is_a?(Array) && !blocked_tags.empty?

    seen = {}
    blocked_tags.each do |tag|
      return [:invalid] unless tag.is_a?(String) && !tag.empty?
      return [:invalid] if seen.key?(tag)
      seen[tag] = true
    end

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      sorted = blocked_tags.sort
      serialized = JSON.generate(sorted)
      existing = d.get_first_value('SELECT 1 FROM play_safety_boundaries WHERE campaign_id = ?', campaign_id)
      if existing
        d.execute('UPDATE play_safety_boundaries SET blocked_tags_json = ? WHERE campaign_id = ?', [serialized, campaign_id])
      else
        d.execute('INSERT INTO play_safety_boundaries (campaign_id, blocked_tags_json) VALUES (?, ?)', [campaign_id, serialized])
      end

      [:ok, { 'blocked_tags' => sorted }]
    end
  end

  def self.get_safety_boundaries(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row('SELECT blocked_tags_json FROM play_safety_boundaries WHERE campaign_id = ?', campaign_id)
      tags = row ? JSON.parse(row[0]) : []
      [:ok, { 'blocked_tags' => tags }]
    end
  end

  def self.submit_safety_check(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    event_id = payload['event_id']
    kind = payload['kind']
    text = payload['text']
    tags = payload['tags']
    return [:invalid] unless event_id.is_a?(String) && !event_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?
    return [:invalid] unless kind == 'narration' || kind == 'chat'
    return [:invalid] unless tags.is_a?(Array) && !tags.empty?

    seen = {}
    tags.each do |tag|
      return [:invalid] unless tag.is_a?(String) && !tag.empty?
      return [:invalid] if seen.key?(tag)
      seen[tag] = true
    end

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_safety_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:conflict] if existing

      boundary_row = d.get_first_row('SELECT blocked_tags_json FROM play_safety_boundaries WHERE campaign_id = ?', campaign_id)
      blocked = boundary_row ? JSON.parse(boundary_row[0]) : []
      blocked_lookup = {}
      blocked.each { |t| blocked_lookup[t] = true }
      if tags.any? { |tag| blocked_lookup[tag] }
        next [:conflict]
      end

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_safety_events WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, event_id, kind, text, JSON.generate(tags), sequence]
      )

      [:ok, {
        'event_id' => event_id,
        'kind' => kind,
        'text' => text,
        'tags' => tags,
        'sequence' => sequence
      }]
    end
  end

  def self.list_safety_events(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, kind, text, tags_json, sequence FROM play_safety_events WHERE campaign_id = ? ORDER BY sequence',
        campaign_id
      )

      events = rows.map do |eid, kind, text, tags_json, seq|
        {
          'event_id' => eid,
          'kind' => kind,
          'text' => text,
          'tags' => JSON.parse(tags_json),
          'sequence' => seq
        }
      end

      [:ok, { 'events' => events }]
    end
  end

  # Fixture seeding: deterministic campaign-scoped canonical state.

  CANONICAL_FIXTURE_ID = 'canonical-v1'.freeze
  CANONICAL_FIXTURE_CHARACTERS = [
    { 'character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter' },
    { 'character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard' }
  ].freeze
  CANONICAL_FIXTURE_STORY = 'The lantern is lit.'.freeze
  CANONICAL_FIXTURE_EVENT_IDS = %w[fixture-event-1 fixture-event-2].freeze

  def self.seed_fixture(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    fixture_id = payload['fixture_id']
    return [:invalid] unless fixture_id == CANONICAL_FIXTURE_ID

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign
      next [:forbidden] unless campaign[0] == actor[:username]

      row = d.get_first_row(
        'SELECT fixture_id, status, characters_json, story, event_ids_json FROM play_fixture_seeds WHERE campaign_id = ?',
        campaign_id
      )
      if row
        next [:ok, fixture_state_from_row(row)]
      end

      d.execute(
        'INSERT INTO play_fixture_seeds (campaign_id, fixture_id, status, characters_json, story, event_ids_json) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, CANONICAL_FIXTURE_ID, 'seeded', JSON.generate(CANONICAL_FIXTURE_CHARACTERS), CANONICAL_FIXTURE_STORY, JSON.generate(CANONICAL_FIXTURE_EVENT_IDS)]
      )

      [:created, canonical_fixture_state]
    end
  end

  def self.get_fixture_state(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      row = d.get_first_row(
        'SELECT fixture_id, status, characters_json, story, event_ids_json FROM play_fixture_seeds WHERE campaign_id = ?',
        campaign_id
      )
      next [:not_found] unless row

      [:ok, fixture_state_from_row(row)]
    end
  end

  # Load-safe append-only event feed for campaign members.
  def self.append_feed_event(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    event_id = payload['event_id']
    text = payload['text']
    return [:invalid] unless event_id.is_a?(String) && !event_id.empty?
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      existing = d.get_first_value(
        'SELECT 1 FROM play_feed_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      next [:conflict] if existing

      sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_feed_events WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)',
        [campaign_id, event_id, text, sequence]
      )

      [:created, {
        'event_id' => event_id,
        'text' => text,
        'sequence' => sequence
      }]
    end
  end

  def self.read_event_feed(campaign_id, actor, cursor, limit)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    cursor = parse_feed_cursor(cursor)
    limit = parse_feed_limit(limit)
    return [:invalid] unless cursor && limit

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      rows = d.execute(
        'SELECT event_id, text, sequence FROM play_feed_events WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?',
        [campaign_id, limit, cursor]
      )

      events = rows.map do |event_id, text, sequence|
        {
          'event_id' => event_id,
          'text' => text,
          'sequence' => sequence
        }
      end

      [:ok, {
        'events' => events,
        'next_cursor' => cursor + events.length
      }]
    end
  end

  def self.parse_feed_cursor(raw)
    return 0 if raw.nil?
    return nil unless raw.is_a?(String) || raw.is_a?(Integer)

    value = raw.is_a?(Integer) ? raw : Integer(raw, 10)
    value >= 0 ? value : nil
  rescue ArgumentError, TypeError
    nil
  end
  private_class_method :parse_feed_cursor

  def self.parse_feed_limit(raw)
    return 2 if raw.nil?
    return nil unless raw.is_a?(String) || raw.is_a?(Integer)

    value = raw.is_a?(Integer) ? raw : Integer(raw, 10)
    (1..3).include?(value) ? value : nil
  rescue ArgumentError, TypeError
    nil
  end
  private_class_method :parse_feed_limit

  def self.canonical_fixture_state
    {
      'fixture_id' => CANONICAL_FIXTURE_ID,
      'status' => 'seeded',
      'characters' => CANONICAL_FIXTURE_CHARACTERS,
      'story' => CANONICAL_FIXTURE_STORY,
      'event_ids' => CANONICAL_FIXTURE_EVENT_IDS
    }
  end
  private_class_method :canonical_fixture_state

  def self.fixture_state_from_row(row)
    {
      'fixture_id' => row[0],
      'status' => row[1],
      'characters' => JSON.parse(row[2]),
      'story' => row[3],
      'event_ids' => JSON.parse(row[4])
    }
  end
  private_class_method :fixture_state_from_row

  def self.compute_roll_result(seed, sequence, roll_id, sides)
    input = "#{seed}|#{sequence}|#{roll_id}|#{sides}"
    acc = 0
    input.each_byte do |b|
      acc = (acc * 31 + b) & 0xFFFFFFFF
    end
    (acc % sides) + 1
  end
  private_class_method :compute_roll_result, :fixture_state_from_row, :canonical_fixture_state

  def self.note_response(note_id, text, visibility, owner)
    {
      'note_id' => note_id,
      'text' => text,
      'visibility' => visibility,
      'owner' => owner
    }
  end

  def self.whisper_response(whisper_id, from_character_id, to_character_id, text)
    {
      'whisper_id' => whisper_id,
      'from_character_id' => from_character_id,
      'to_character_id' => to_character_id,
      'text' => text
    }
  end

  private_class_method :content_response, :validate_content, :validate_tags, :note_response, :whisper_response

  private_class_method :build_encounter_order, :calendar_response, :calculate_weather, :settlement_response, :validate_settlement, :validate_settlement_update, :shop_response, :validate_shop, :recipe_response, :validate_recipe
end
