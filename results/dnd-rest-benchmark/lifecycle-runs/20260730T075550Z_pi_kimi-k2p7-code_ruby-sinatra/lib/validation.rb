# frozen_string_literal: true

# Input validation helpers for all HTTP endpoints.
#
# Methods in this module run inside the Sinatra request context and may halt the
# request with a JSON 400 response when the input is invalid. Callers are
# responsible for setting a successful response's content type.
module Validation
  def valid_positive_integer?(value)
    value.is_a?(Integer) && value.positive?
  end

  def validate_integer!(value, name, range)
    unless value.is_a?(Integer) && range.cover?(value)
      json_error(400, "invalid #{name}")
    end
  end

  def validate_username!(username)
    unless username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
      json_error(400, 'invalid username')
    end
  end

  def validate_password!(password)
    unless password.is_a?(String) && password.length >= 8
      json_error(400, 'invalid password')
    end
  end

  def validate_role!(role)
    unless role == 'dm' || role == 'player'
      json_error(400, 'invalid role')
    end
  end

  def validate_slug!(slug)
    unless slug.is_a?(String) && slug.match?(/\A[a-z0-9-]+\z/)
      json_error(400, 'invalid slug')
    end
  end

  def validate_campaign_id!(id)
    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid campaign id')
    end
  end

  def validate_monster_body!(body)
    slug = body['slug']
    name = body['name']
    cr = body['cr']
    armor_class = body['armor_class']
    hit_points = body['hit_points']
    tags = body['tags']

    validate_slug!(slug)
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless cr.is_a?(String) && cr.match?(/\A(\d+|1\/\d+)\z/)
      json_error(400, 'invalid cr')
    end
    unless armor_class.is_a?(Integer) && armor_class.positive?
      json_error(400, 'invalid armor_class')
    end
    unless hit_points.is_a?(Integer) && hit_points.positive?
      json_error(400, 'invalid hit_points')
    end
    unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
      json_error(400, 'invalid tags')
    end
  end

  def validate_item_body!(body)
    slug = body['slug']
    name = body['name']
    type = body['type']
    rarity = body['rarity']
    cost_gp = body['cost_gp']

    validate_slug!(slug)
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless type.is_a?(String) && type != ''
      json_error(400, 'invalid type')
    end
    unless rarity.is_a?(String) && rarity != ''
      json_error(400, 'invalid rarity')
    end
    unless cost_gp.is_a?(Integer) && cost_gp >= 0
      json_error(400, 'invalid cost_gp')
    end
  end

  def validate_campaign_body!(body)
    id = body['id']
    name = body['name']
    dm = body['dm']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless dm.is_a?(String) && dm != ''
      json_error(400, 'invalid dm')
    end
  end

  def validate_character_body!(body)
    id = body['id']
    name = body['name']
    level = body['level']
    class_name = body['class']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless level.is_a?(Integer) && level.positive?
      json_error(400, 'invalid level')
    end
    unless class_name.is_a?(String) && class_name != ''
      json_error(400, 'invalid class')
    end
  end

  def validate_event_body!(body)
    id = body['id']
    kind = body['kind']
    summary = body['summary']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless kind.is_a?(String) && kind != ''
      json_error(400, 'invalid kind')
    end
    unless summary.is_a?(String)
      json_error(400, 'invalid summary')
    end
  end

  def validate_quest_body!(body)
    id = body['id']
    title = body['title']
    status = body['status']
    milestones = body['milestones']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless title.is_a?(String) && title != ''
      json_error(400, 'invalid title')
    end
    unless %w[active completed blocked].include?(status)
      json_error(400, 'invalid status')
    end
    unless milestones.is_a?(Array) && milestones.all? { |m| m.is_a?(String) }
      json_error(400, 'invalid milestones')
    end
  end

  def validate_progress_body!(body)
    completed = body['completed']

    unless completed.is_a?(Array) && completed.all? { |m| m.is_a?(String) }
      json_error(400, 'invalid completed')
    end
  end

  def validate_faction_body!(body)
    id = body['id']
    name = body['name']
    stance = body['stance']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless stance.is_a?(String) && stance != ''
      json_error(400, 'invalid stance')
    end
  end

  def validate_npc_body!(body)
    id = body['id']
    name = body['name']
    faction_id = body['faction_id']
    disposition = body['disposition']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless faction_id.is_a?(String) && faction_id != ''
      json_error(400, 'invalid faction_id')
    end
    unless disposition.is_a?(Integer)
      json_error(400, 'invalid disposition')
    end
  end

  def validate_party!(party)
    unless party.is_a?(Array) && !party.empty?
      json_error(400, 'invalid party')
    end
    party.each do |member|
      unless member.is_a?(Hash) && member['level'].is_a?(Integer) && member['level'].positive?
        json_error(400, 'invalid party member')
      end
    end
  end

  def validate_monster_slugs!(slugs)
    unless slugs.is_a?(Array) && !slugs.empty?
      json_error(400, 'invalid monster_slugs')
    end
    slugs.each { |slug| validate_slug!(slug) }
  end

  def validate_inventory_item_body!(body)
    item_slug = body['item_slug']
    quantity = body['quantity']
    owner = body['owner']

    validate_slug!(item_slug)
    unless valid_positive_integer?(quantity)
      json_error(400, 'invalid quantity')
    end
    unless owner.is_a?(String) && owner != ''
      json_error(400, 'invalid owner')
    end
  end

  def validate_equipment_assignment_body!(body)
    item_slug = body['item_slug']
    quantity = body['quantity']

    validate_slug!(item_slug)
    unless valid_positive_integer?(quantity)
      json_error(400, 'invalid quantity')
    end
  end

  def validate_crafting_project_body!(body)
    id = body['id']
    character_id = body['character_id']
    item_slug = body['item_slug']
    days_required = body['days_required']
    cost_gp = body['cost_gp']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
    validate_slug!(item_slug)
    unless valid_positive_integer?(days_required)
      json_error(400, 'invalid days_required')
    end
    unless cost_gp.is_a?(Integer) && cost_gp >= 0
      json_error(400, 'invalid cost_gp')
    end
  end

  def validate_crafting_advance_body!(body)
    days = body['days']
    unless valid_positive_integer?(days)
      json_error(400, 'invalid days')
    end
  end

  def validate_session_body!(body)
    id = body['id']
    starts_at = body['starts_at']
    duration_minutes = body['duration_minutes']
    agenda = body['agenda']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless starts_at.is_a?(String) && starts_at.match?(/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\z/)
      json_error(400, 'invalid starts_at')
    end
    unless valid_positive_integer?(duration_minutes)
      json_error(400, 'invalid duration_minutes')
    end
    unless agenda.is_a?(Array) && agenda.all? { |item| item.is_a?(String) }
      json_error(400, 'invalid agenda')
    end
  end

  def validate_attendance_body!(body)
    present = body['present']
    absent = body['absent']

    unless present.is_a?(Array) && present.all? { |id| id.is_a?(String) }
      json_error(400, 'invalid present')
    end
    unless absent.is_a?(Array) && absent.all? { |id| id.is_a?(String) }
      json_error(400, 'invalid absent')
    end
  end

  def validate_play_campaign_body!(body)
    id = body['id']
    name = body['name']
    max_players = body['max_players']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless valid_positive_integer?(max_players)
      json_error(400, 'invalid max_players')
    end
  end

  def validate_membership_body!(body)
    character_id = body['character_id']
    name = body['name']
    class_name = body['class']

    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless class_name.is_a?(String) && class_name != ''
      json_error(400, 'invalid class')
    end
  end

  def validate_narration_body!(body)
    text = body['text']

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_action_body!(body)
    type = body['type']
    text = body['text']

    unless type.is_a?(String) && type != ''
      json_error(400, 'invalid type')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_nudge_body!(body)
    message = body['message']

    unless message.is_a?(String) && message != ''
      json_error(400, 'invalid message')
    end
  end

  def validate_document_body!(body)
    story = body['story']
    dm_notes = body['dm_notes']

    unless story.is_a?(String)
      json_error(400, 'invalid story')
    end
    unless dm_notes.is_a?(String)
      json_error(400, 'invalid dm_notes')
    end
  end

  def validate_import_snapshot!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid import snapshot')
    end

    version = body['version']
    story = body['story']
    status = body['status']

    unless version.is_a?(Integer) && version == 1
      json_error(400, 'invalid version')
    end
    unless story.is_a?(String) && story != ''
      json_error(400, 'invalid story')
    end
    unless status.is_a?(String) && %w[lobby started].include?(status)
      json_error(400, 'invalid status')
    end
  end

  def validate_migration_snapshot!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid migration snapshot')
    end

    schema_version = body['schema_version']
    story = body['story']

    unless schema_version.is_a?(Integer) && schema_version == 1
      json_error(400, 'invalid schema_version')
    end
    unless story.is_a?(String) && story != ''
      json_error(400, 'invalid story')
    end
  end

  def validate_scene_body!(body)
    id = body['id']
    name = body['name']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
  end

  def validate_location_body!(body)
    id = body['id']
    name = body['name']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
  end

  def validate_connection_body!(body)
    to_id = body['to_id']
    travel_turns = body['travel_turns']

    unless to_id.is_a?(String) && to_id != ''
      json_error(400, 'invalid to_id')
    end
    unless valid_positive_integer?(travel_turns)
      json_error(400, 'invalid travel_turns')
    end
  end

  def validate_travel_body!(body)
    destination_id = body['destination_id']

    unless destination_id.is_a?(String) && destination_id != ''
      json_error(400, 'invalid destination_id')
    end
  end

  def validate_rest_body!(body)
    type = body['type']

    unless type == 'long' || type == 'short'
      json_error(400, 'invalid type')
    end
  end

  def validate_encounter_body!(body)
    id = body['id']
    name = body['name']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
  end

  def validate_monster_roster_body!(body)
    monster_id = body['monster_id']
    name = body['name']
    hp_max = body['hp_max']
    initiative = body['initiative']

    unless monster_id.is_a?(String) && monster_id != ''
      json_error(400, 'invalid monster_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless valid_positive_integer?(hp_max)
      json_error(400, 'invalid hp_max')
    end
    unless initiative.is_a?(Integer)
      json_error(400, 'invalid initiative')
    end
  end

  def validate_party_combatant_body!(body)
    member = body['member']
    initiative = body['initiative']

    unless member.is_a?(String) && member != ''
      json_error(400, 'invalid member')
    end
    unless initiative.is_a?(Integer)
      json_error(400, 'invalid initiative')
    end
  end

  VALID_COMBAT_ACTION_TYPES = %w[attack help dodge ready].freeze

  def validate_combat_action_body!(body)
    type = body['type']
    target = body['target']
    text = body['text']

    unless VALID_COMBAT_ACTION_TYPES.include?(type)
      json_error(400, 'invalid type')
    end
    unless target.is_a?(String) && target != ''
      json_error(400, 'invalid target')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_hp_change_body!(body)
    target = body['target']
    amount = body['amount']

    unless target.is_a?(String) && target != ''
      json_error(400, 'invalid target')
    end
    unless amount.is_a?(Integer) && amount.positive?
      json_error(400, 'invalid amount')
    end
  end

  def validate_character_damage_body!(body)
    amount = body['amount']

    unless amount.is_a?(Integer) && amount.positive?
      json_error(400, 'invalid amount')
    end
  end

  def validate_death_save_body!(body)
    outcome = body['outcome']

    unless outcome == 'success' || outcome == 'failure'
      json_error(400, 'invalid outcome')
    end
  end

  def validate_condition_body!(body)
    target = body['target']
    condition = body['condition']
    duration_rounds = body['duration_rounds']

    unless target.is_a?(String) && target != ''
      json_error(400, 'invalid target')
    end
    unless condition.is_a?(String) && condition != ''
      json_error(400, 'invalid condition')
    end
    unless valid_positive_integer?(duration_rounds)
      json_error(400, 'invalid duration_rounds')
    end
  end

  def validate_ready_body!(body)
    trigger = body['trigger']

    unless trigger.is_a?(String) && trigger != ''
      json_error(400, 'invalid trigger')
    end
  end

  def validate_reward_body!(body)
    xp = body['xp']
    loot = body['loot']

    unless xp.is_a?(Integer) && xp.positive?
      json_error(400, 'invalid xp')
    end
    unless loot.is_a?(Array) && loot.all? do |entry|
      next false unless entry.is_a?(Hash)
      validate_slug!(entry['slug'])
      valid_positive_integer?(entry['quantity'])
    end
      json_error(400, 'invalid loot')
    end
  end

  def validate_build_body!(body)
    race = body['race']
    class_name = body['class']
    background = body['background']
    abilities = body['abilities']

    unless race.is_a?(String) && GameLogic::VALID_RACES.include?(race)
      json_error(400, 'invalid race')
    end
    unless class_name.is_a?(String) && GameLogic::VALID_CLASSES.include?(class_name)
      json_error(400, 'invalid class')
    end
    unless background.is_a?(String) && GameLogic::VALID_BACKGROUNDS.include?(background)
      json_error(400, 'invalid background')
    end
    unless abilities.is_a?(Hash)
      json_error(400, 'invalid abilities')
    end
    GameLogic::ABILITY_SCORES.each do |ability|
      score = abilities[ability]
      unless score.is_a?(Integer) && (1..30).cover?(score)
        json_error(400, 'invalid ability scores')
      end
    end
  end

  def validate_level_up_body!(body)
    level = body['level']
    unless level.is_a?(Integer) && (1..20).cover?(level)
      json_error(400, 'invalid level')
    end
  end

  def validate_skill_check_body!(body)
    skill = body['skill']
    ability = body['ability']
    proficient = body['proficient']
    roll = body['roll']

    unless skill.is_a?(String) && GameLogic::VALID_SKILLS.include?(skill)
      json_error(400, 'invalid skill')
    end
    unless ability.is_a?(String) && GameLogic::ABILITY_SCORES.include?(ability)
      json_error(400, 'invalid ability')
    end
    unless proficient == true || proficient == false
      json_error(400, 'invalid proficient')
    end
    unless roll.is_a?(Integer)
      json_error(400, 'invalid roll')
    end
  end

  def validate_spell_body!(body)
    spell_id = body['spell_id']
    name = body['name']
    level = body['level']

    unless spell_id.is_a?(String) && spell_id != '' && spell_id.match?(/\A[a-z0-9-]+\z/)
      json_error(400, 'invalid spell_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless level.is_a?(Integer) && (0..9).cover?(level)
      json_error(400, 'invalid level')
    end
  end

  def validate_prepared_spells_body!(body)
    spell_ids = body['spell_ids']

    unless spell_ids.is_a?(Array)
      json_error(400, 'invalid spell_ids')
    end

    spell_ids.each do |spell_id|
      unless spell_id.is_a?(String) && spell_id != '' && spell_id.match?(/\A[a-z0-9-]+\z/)
        json_error(400, 'invalid spell_id')
      end
    end
  end

  def validate_cast_body!(body)
    spell_id = body['spell_id']
    target = body['target']

    unless spell_id.is_a?(String) && spell_id != '' && spell_id.match?(/\A[a-z0-9-]+\z/)
      json_error(400, 'invalid spell_id')
    end
    unless target.is_a?(String) && target != ''
      json_error(400, 'invalid target')
    end
  end

  def validate_concentration_body!(body)
    spell_id = body['spell_id']
    target = body['target']
    duration_turns = body['duration_turns']

    unless spell_id.is_a?(String) && spell_id != '' && spell_id.match?(/\A[a-z0-9-]+\z/)
      json_error(400, 'invalid spell_id')
    end
    unless target.is_a?(String) && target != ''
      json_error(400, 'invalid target')
    end
    unless duration_turns.is_a?(Integer) && duration_turns >= 1
      json_error(400, 'invalid duration_turns')
    end
  end

  VALID_INVENTORY_ITEM_IDS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze
  VALID_CONSUMABLE_ITEM_IDS = %w[healing-potion].freeze

  EQUIPMENT_SLOTS = %w[armor accessory].freeze
  EQUIPMENT_ITEM_SLOTS = {
    'leather-armor' => 'armor',
    'ring-of-protection' => 'accessory',
    'amulet-of-health' => 'accessory'
  }.freeze
  ATTUNABLE_ITEM_IDS = %w[ring-of-protection amulet-of-health].freeze

  def validate_equipment_slot!(slot)
    unless EQUIPMENT_SLOTS.include?(slot)
      json_error(400, 'invalid slot')
    end
  end

  def validate_inventory_stack_body!(body)
    item_id = body['item_id']
    quantity = body['quantity']

    unless item_id.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(item_id)
      json_error(400, 'invalid item_id')
    end
    unless quantity.is_a?(Integer) && quantity.positive?
      json_error(400, 'invalid quantity')
    end
  end

  def validate_transfer_body!(body)
    to_character_id = body['to_character_id']
    gold = body['gold']

    unless to_character_id.is_a?(String) && to_character_id != ''
      json_error(400, 'invalid to_character_id')
    end
    unless gold.is_a?(Integer) && gold.positive?
      json_error(400, 'invalid gold')
    end
  end

  def validate_transactional_transfer_body!(body)
    from_character_id = body['from_character_id']
    to_character_id = body['to_character_id']
    amount = body['amount']
    simulate_failure = body['simulate_failure']

    unless from_character_id.is_a?(String) && from_character_id != ''
      json_error(400, 'invalid from_character_id')
    end
    unless to_character_id.is_a?(String) && to_character_id != ''
      json_error(400, 'invalid to_character_id')
    end
    unless amount.is_a?(Integer) && amount.positive?
      json_error(400, 'invalid amount')
    end
    unless simulate_failure == true || simulate_failure == false
      json_error(400, 'invalid simulate_failure')
    end
  end

  def validate_loot_body!(body)
    loot_id = body['loot_id']
    item_id = body['item_id']
    quantity = body['quantity']

    validate_slug!(loot_id)
    validate_slug!(item_id)
    unless quantity.is_a?(Integer) && quantity.positive?
      json_error(400, 'invalid quantity')
    end
  end

  def validate_play_npc_body!(body)
    npc_id = body['npc_id']
    name = body['name']
    agenda = body['agenda']
    public_status = body['public_status']

    unless npc_id.is_a?(String) && npc_id != ''
      json_error(400, 'invalid npc_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless agenda.is_a?(String) && agenda != ''
      json_error(400, 'invalid agenda')
    end
    unless public_status.is_a?(String) && public_status != ''
      json_error(400, 'invalid public_status')
    end
  end

  def validate_play_npc_agenda_body!(body)
    agenda = body['agenda']
    public_status = body['public_status']

    unless agenda.is_a?(String) && agenda != ''
      json_error(400, 'invalid agenda')
    end
    unless public_status.is_a?(String) && public_status != ''
      json_error(400, 'invalid public_status')
    end
  end

  def validate_loot_vote_body!(body)
    recipient = body['recipient_character_id']

    unless recipient.is_a?(String) && recipient != ''
      json_error(400, 'invalid recipient_character_id')
    end
  end

  def validate_play_faction_body!(body)
    faction_id = body['faction_id']
    name = body['name']

    unless faction_id.is_a?(String) && faction_id != ''
      json_error(400, 'invalid faction_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
  end

  def validate_reputation_body!(body)
    character_id = body['character_id']
    delta = body['delta']
    reason = body['reason']

    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
    unless delta.is_a?(Integer) && delta != 0 && (-25..25).cover?(delta)
      json_error(400, 'invalid delta')
    end
    unless reason.is_a?(String) && reason != ''
      json_error(400, 'invalid reason')
    end
  end

  def validate_play_npc_dialogue_body!(body)
    dialogue_id = body['dialogue_id']
    speaker = body['speaker']
    text = body['text']
    visibility = body['visibility']

    unless dialogue_id.is_a?(String) && dialogue_id != ''
      json_error(400, 'invalid dialogue_id')
    end
    unless speaker.is_a?(String) && speaker != ''
      json_error(400, 'invalid speaker')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
    unless visibility == 'public' || visibility == 'private'
      json_error(400, 'invalid visibility')
    end
  end

  def validate_relationship_body!(body)
    source_id = body['source_id']
    target_id = body['target_id']
    kind = body['kind']
    score = body['score']

    unless source_id.is_a?(String) && source_id != ''
      json_error(400, 'invalid source_id')
    end
    unless target_id.is_a?(String) && target_id != ''
      json_error(400, 'invalid target_id')
    end
    unless kind.is_a?(String) && kind != ''
      json_error(400, 'invalid kind')
    end
    unless score.is_a?(Integer) && (-100..100).cover?(score)
      json_error(400, 'invalid score')
    end
  end

  VALID_CLUE_AUDIENCES = %w[character party hidden].freeze

  def validate_clue_body!(body)
    clue_id = body['clue_id']
    text = body['text']
    audience = body['audience']

    unless clue_id.is_a?(String) && clue_id != ''
      json_error(400, 'invalid clue_id')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
    unless VALID_CLUE_AUDIENCES.include?(audience)
      json_error(400, 'invalid audience')
    end

    character_id = body['character_id']
    if audience == 'character'
      unless character_id.is_a?(String) && character_id != ''
        json_error(400, 'invalid character_id')
      end
    elsif body.key?('character_id')
      json_error(400, 'invalid character_id')
    end
  end

  def validate_play_quest_body!(body)
    quest_id = body['quest_id']
    title = body['title']
    depends_on = body['depends_on']

    unless quest_id.is_a?(String) && quest_id != ''
      json_error(400, 'invalid quest_id')
    end
    unless title.is_a?(String) && title != ''
      json_error(400, 'invalid title')
    end
    unless depends_on.is_a?(Array) && depends_on.all? { |dep| dep.is_a?(String) && dep != '' }
      json_error(400, 'invalid depends_on')
    end
    if depends_on.uniq.length != depends_on.length
      json_error(400, 'invalid depends_on')
    end
    if depends_on.include?(quest_id)
      json_error(400, 'invalid depends_on')
    end
  end

  def validate_play_quest_state_body!(body)
    state = body['state']
    unless state == 'active' || state == 'completed'
      json_error(400, 'invalid state')
    end
  end

  def validate_play_quest_reward_body!(body)
    xp = body['xp']
    items = body['items']

    unless xp.is_a?(Integer) && xp >= 0
      json_error(400, 'invalid xp')
    end
    unless items.is_a?(Hash)
      json_error(400, 'invalid items')
    end
    items.each do |item_id, quantity|
      unless item_id.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
        json_error(400, 'invalid items')
      end
    end
  end

  def validate_world_event_body!(body)
    event_id = body['event_id']
    turn_number = body['turn_number']
    title = body['title']
    text = body['text']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end
    unless turn_number.is_a?(Integer)
      json_error(400, 'invalid turn_number')
    end
    unless title.is_a?(String) && title != ''
      json_error(400, 'invalid title')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_world_event_resolution_body!(body)
    text = body['text']

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  VALID_SEASONS = %w[spring summer autumn winter].freeze

  def validate_calendar_body!(body)
    day = body['day']
    season = body['season']

    unless day.is_a?(Integer) && day >= 1
      json_error(400, 'invalid day')
    end
    unless VALID_SEASONS.include?(season)
      json_error(400, 'invalid season')
    end
  end

  def validate_calendar_advance_body!(body)
    days = body['days']

    unless days.is_a?(Integer) && (1..30).cover?(days)
      json_error(400, 'invalid days')
    end
  end

  def validate_settlement_id!(settlement_id)
    unless settlement_id.is_a?(String) && settlement_id != ''
      json_error(400, 'invalid settlement_id')
    end
  end

  def validate_and_normalize_settlement_services!(services)
    unless services.is_a?(Array) && !services.empty?
      json_error(400, 'invalid services')
    end

    normalized = []
    services.each do |service|
      unless service.is_a?(String)
        json_error(400, 'invalid services')
      end

      trimmed = service.strip
      json_error(400, 'invalid services') if trimmed.empty?
      normalized << trimmed
    end

    if normalized.uniq.length != normalized.length
      json_error(400, 'invalid services')
    end

    normalized
  end

  def validate_and_normalize_settlement_body!(body)
    name = body['name']
    services = body['services']
    availability = body['availability']

    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end

    normalized_services = validate_and_normalize_settlement_services!(services)

    unless %w[open limited closed].include?(availability)
      json_error(400, 'invalid availability')
    end

    [name, normalized_services, availability]
  end

  def validate_shop_body!(body)
    shop_id = body['shop_id']
    name = body['name']
    stock = body['stock']
    buy_price = body['buy_price']
    sell_price = body['sell_price']

    unless shop_id.is_a?(String) && shop_id != ''
      json_error(400, 'invalid shop_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless stock.is_a?(Hash) && !stock.empty?
      json_error(400, 'invalid stock')
    end
    stock.each do |item_id, quantity|
      unless item_id.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(item_id)
        json_error(400, 'invalid stock')
      end
      unless quantity.is_a?(Integer) && quantity.positive?
        json_error(400, 'invalid stock')
      end
    end
    unless buy_price.is_a?(Integer) && buy_price.positive?
      json_error(400, 'invalid buy_price')
    end
    unless sell_price.is_a?(Integer) && sell_price >= 0
      json_error(400, 'invalid sell_price')
    end
  end

  def validate_shop_transaction_body!(body)
    character_id = body['character_id']
    item_id = body['item_id']
    quantity = body['quantity']

    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
    unless item_id.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(item_id)
      json_error(400, 'invalid item_id')
    end
    unless quantity.is_a?(Integer) && quantity.positive?
      json_error(400, 'invalid quantity')
    end
  end

  def validate_recipe_body!(body)
    recipe_id = body['recipe_id']
    name = body['name']
    ingredients = body['ingredients']
    output_item = body['output_item']
    output_quantity = body['output_quantity']

    unless recipe_id.is_a?(String) && recipe_id != ''
      json_error(400, 'invalid recipe_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless ingredients.is_a?(Hash) && !ingredients.empty?
      json_error(400, 'invalid ingredients')
    end
    ingredients.each do |item_id, quantity|
      unless item_id.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(item_id)
        json_error(400, 'invalid ingredients')
      end
      unless quantity.is_a?(Integer) && quantity.positive?
        json_error(400, 'invalid ingredients')
      end
    end
    unless output_item.is_a?(String) && VALID_INVENTORY_ITEM_IDS.include?(output_item)
      json_error(400, 'invalid output_item')
    end
    unless output_quantity.is_a?(Integer) && output_quantity.positive?
      json_error(400, 'invalid output_quantity')
    end
  end

  def validate_craft_body!(body)
    character_id = body['character_id']

    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
  end

  def validate_downtime_activity_body!(body)
    activity_id = body['activity_id']
    name = body['name']
    cycles_required = body['cycles_required']

    unless activity_id.is_a?(String) && activity_id != ''
      json_error(400, 'invalid activity_id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless cycles_required.is_a?(Integer) && (1..10).cover?(cycles_required)
      json_error(400, 'invalid cycles_required')
    end
  end

  def validate_downtime_allocation_body!(body)
    activity_id = body['activity_id']

    unless activity_id.is_a?(String) && activity_id != ''
      json_error(400, 'invalid activity_id')
    end
  end

  def validate_session_zero_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid session zero settings')
    end

    allowed_keys = %w[rules tone consent]
    unless body.keys.all? { |k| allowed_keys.include?(k) }
      json_error(400, 'invalid session zero settings')
    end

    rules = body['rules']
    tone = body['tone']
    consent = body['consent']

    unless rules.is_a?(String) && rules != ''
      json_error(400, 'invalid rules')
    end
    unless tone.is_a?(String) && tone != ''
      json_error(400, 'invalid tone')
    end
    unless consent.is_a?(Array) && !consent.empty?
      json_error(400, 'invalid consent')
    end
    consent.each do |entry|
      unless entry.is_a?(String) && entry != ''
        json_error(400, 'invalid consent')
      end
    end
    unless consent.uniq.length == consent.length
      json_error(400, 'invalid consent')
    end
  end

  def validate_content_tags!(tags, allow_empty:)
    unless tags.is_a?(Array)
      json_error(400, 'invalid tags')
    end
    unless allow_empty || !tags.empty?
      json_error(400, 'invalid tags')
    end

    seen = {}
    tags.each do |tag|
      unless tag.is_a?(String) && tag != ''
        json_error(400, 'invalid tags')
      end
      if seen.key?(tag)
        json_error(400, 'invalid tags')
      end
      seen[tag] = true
    end
  end

  def validate_content_body!(body)
    content_id = body['content_id']
    kind = body['kind']
    text = body['text']
    tags = body['tags']

    unless content_id.is_a?(String) && content_id != ''
      json_error(400, 'invalid content_id')
    end
    unless kind.is_a?(String) && kind != ''
      json_error(400, 'invalid kind')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
    validate_content_tags!(tags, allow_empty: false)
  end

  def validate_note_body!(body)
    note_id = body['note_id']
    text = body['text']
    visibility = body['visibility']

    unless note_id.is_a?(String) && note_id != ''
      json_error(400, 'invalid note_id')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
    unless visibility == 'private' || visibility == 'party'
      json_error(400, 'invalid visibility')
    end
  end

  def validate_note_update_body!(body)
    text = body['text']
    visibility = body['visibility']

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
    unless visibility == 'private' || visibility == 'party'
      json_error(400, 'invalid visibility')
    end
  end

  def validate_whisper_body!(body)
    whisper_id = body['whisper_id']
    to_character_id = body['to_character_id']
    text = body['text']

    unless whisper_id.is_a?(String) && whisper_id != ''
      json_error(400, 'invalid whisper_id')
    end
    unless to_character_id.is_a?(String) && to_character_id != ''
      json_error(400, 'invalid to_character_id')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_message_body!(body)
    text = body['text']
    text = body['message'] if text.nil? || (text.is_a?(String) && text == '')

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_invitation_id!(invitation_id)
    unless invitation_id.is_a?(String) && invitation_id != ''
      json_error(400, 'invalid invitation_id')
    end
  end

  def validate_invitation_body!(body)
    invitation_id = body['invitation_id']
    username = body['username']
    character_id = body['character_id']

    unless invitation_id.is_a?(String) && invitation_id != ''
      json_error(400, 'invalid invitation_id')
    end
    unless username.is_a?(String) && username != ''
      json_error(400, 'invalid username')
    end
    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
  end

  def validate_delegation_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid delegation')
    end

    username = body['username']
    powers = body['powers']

    unless username.is_a?(String) && username != ''
      json_error(400, 'invalid username')
    end

    unless powers.is_a?(Array) && !powers.empty?
      json_error(400, 'invalid powers')
    end

    if powers.uniq.length != powers.length
      json_error(400, 'invalid powers')
    end

    powers.each do |power|
      unless power == 'narrate'
        json_error(400, 'invalid powers')
      end
    end
  end

  def validate_audit_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid audit event')
    end

    kind = body['kind']
    correlation_id = body['correlation_id']

    unless kind.is_a?(String) && kind != ''
      json_error(400, 'invalid kind')
    end

    unless correlation_id.is_a?(String) && correlation_id != ''
      json_error(400, 'invalid correlation_id')
    end
  end

  def validate_projection_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid projection event')
    end

    event_id = body['event_id']
    kind = body['kind']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end

    unless kind == 'set-story' || kind == 'increment-danger'
      json_error(400, 'invalid kind')
    end

    if kind == 'set-story'
      value = body['value']
      unless value.is_a?(String) && value != ''
        json_error(400, 'invalid value')
      end
    elsif body.key?('value')
      json_error(400, 'invalid value')
    end
  end

  def validate_idempotent_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid idempotent event')
    end

    event_id = body['event_id']
    value = body['value']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end

    unless value.is_a?(String) && value != ''
      json_error(400, 'invalid value')
    end
  end

  def validate_rate_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid rate event')
    end

    event_id = body['event_id']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end
  end

  def validate_replay_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid replay event')
    end

    event_id = body['event_id']
    kind = body['kind']
    text = body['text']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end

    unless kind == 'append'
      json_error(400, 'invalid kind')
    end

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_rng_seed_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid seed')
    end

    seed = body['seed']
    unless seed.is_a?(String) && seed != ''
      json_error(400, 'invalid seed')
    end
  end

  def validate_rng_roll_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid roll')
    end

    roll_id = body['roll_id']
    sides = body['sides']

    unless roll_id.is_a?(String) && roll_id != ''
      json_error(400, 'invalid roll_id')
    end

    unless sides.is_a?(Integer) && (2..100).cover?(sides)
      json_error(400, 'invalid sides')
    end
  end

  def validate_safe_turn_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid safe turn')
    end

    submission_id = body['submission_id']
    action = body['action']
    expected_turn = body['expected_turn']

    unless submission_id.is_a?(String) && submission_id != ''
      json_error(400, 'invalid submission_id')
    end

    unless action.is_a?(String) && action != ''
      json_error(400, 'invalid action')
    end

    unless expected_turn.is_a?(Integer) && expected_turn.positive?
      json_error(400, 'invalid expected_turn')
    end
  end

  def validate_search_record_body!(body)
    record_id = body['record_id']
    text = body['text']

    unless record_id.is_a?(String) && record_id != ''
      json_error(400, 'invalid record_id')
    end
    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  # Validates search-record list query parameters. Returns [q, limit, cursor].
  def validate_search_query!(params)
    q = params['q']
    unless q.nil? || q.is_a?(String)
      json_error(400, 'invalid q')
    end

    limit = params['limit']
    if limit.nil?
      limit = 2
    else
      unless limit.is_a?(String) && limit.match?(/\A[1-9]\z/) && (1..3).cover?(limit.to_i)
        json_error(400, 'invalid limit')
      end
      limit = limit.to_i
    end

    cursor = params['cursor']
    if cursor.nil?
      cursor = 0
    else
      unless cursor.is_a?(String) && cursor.match?(/\A\d+\z/)
        json_error(400, 'invalid cursor')
      end
      cursor = cursor.to_i
    end

    [q, limit, cursor]
  end

  def validate_moderation_report_body!(body)
    report_id = body['report_id']
    target_id = body['target_id']
    reason = body['reason']

    unless report_id.is_a?(String) && report_id != ''
      json_error(400, 'invalid report_id')
    end
    unless target_id.is_a?(String) && target_id != ''
      json_error(400, 'invalid target_id')
    end
    unless reason.is_a?(String) && reason != ''
      json_error(400, 'invalid reason')
    end
  end

  VALID_MODERATION_ACTIONS = %w[allow remove].freeze

  def validate_moderation_resolution_body!(body)
    action = body['action']
    note = body['note']

    unless VALID_MODERATION_ACTIONS.include?(action)
      json_error(400, 'invalid action')
    end
    unless note.is_a?(String) && note != ''
      json_error(400, 'invalid note')
    end
  end

  def validate_safety_boundary_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid body')
    end

    validate_non_empty_unique_string_array!(body['blocked_tags'], 'blocked_tags')
  end

  def validate_safety_check_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid body')
    end

    event_id = body['event_id']
    kind = body['kind']
    text = body['text']
    tags = body['tags']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end

    unless %w[narration chat].include?(kind)
      json_error(400, 'invalid kind')
    end

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end

    validate_non_empty_unique_string_array!(tags, 'tags')
  end

  def validate_fixture_seed_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid fixture_id')
    end

    fixture_id = body['fixture_id']
    unless fixture_id.is_a?(String) && fixture_id == 'canonical-v1'
      json_error(400, 'invalid fixture_id')
    end
  end

  def validate_spectator_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid spectator')
    end

    spectator_id = body['spectator_id']
    unless spectator_id.is_a?(String) && spectator_id != ''
      json_error(400, 'invalid spectator_id')
    end
  end

  def validate_feed_event_body!(body)
    unless body.is_a?(Hash)
      json_error(400, 'invalid feed event')
    end

    event_id = body['event_id']
    text = body['text']

    unless event_id.is_a?(String) && event_id != ''
      json_error(400, 'invalid event_id')
    end

    unless text.is_a?(String) && text != ''
      json_error(400, 'invalid text')
    end
  end

  def validate_feed_cursor!(value)
    if value.nil?
      0
    else
      unless value.is_a?(String) && value.match?(/\A\d+\z/)
        json_error(400, 'invalid cursor')
      end
      value.to_i
    end
  end

  def validate_feed_limit!(value)
    if value.nil?
      2
    else
      unless value.is_a?(String) && value.match?(/\A[1-3]\z/)
        json_error(400, 'invalid limit')
      end
      value.to_i
    end
  end

  def validate_non_empty_unique_string_array!(value, name)
    unless value.is_a?(Array) && !value.empty?
      json_error(400, "invalid #{name}")
    end

    seen = {}
    value.each do |item|
      unless item.is_a?(String) && !item.strip.empty?
        json_error(400, "invalid #{name}")
      end
      if seen.key?(item)
        json_error(400, "invalid #{name}")
      end
      seen[item] = true
    end
  end
end
