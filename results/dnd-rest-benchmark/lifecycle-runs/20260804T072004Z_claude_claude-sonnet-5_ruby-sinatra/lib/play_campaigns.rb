# Shared lookups for the /v1/play campaign-play surface (routes/play/*.rb).
# Extracted because nearly every route there needs the same campaign fetch,
# membership check, and event-append sequence.

def find_play_campaign!(id)
  campaign = db.execute('SELECT * FROM play_campaigns WHERE id = ?', [id]).first
  halt 404, { error: 'campaign not found' }.to_json unless campaign
  campaign
end

def play_campaign_member?(campaign, username)
  !db.execute(
    'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign['id'], username]
  ).first.nil?
end

# Owner (DM) or a joined player — the two identities allowed to read/act on
# most play routes. Halts 403 with the caller's own error copy otherwise.
def require_play_participant!(campaign, user, error_message)
  is_owner = campaign['owner'] == user['username']
  is_member = is_owner || play_campaign_member?(campaign, user['username'])
  halt 403, { error: error_message }.to_json unless is_member
  is_owner
end

# DM-only routes (creating scenes/locations/encounters, dealing damage,
# etc.) all gate on "caller is this campaign's owner" with the same error
# body — pulled out so each route states its intent in one line.
def require_play_owner!(campaign, user)
  halt 403, { error: 'forbidden' }.to_json unless campaign['owner'] == user['username']
end

def find_play_encounter!(campaign_id, encounter_id)
  encounter = db.execute(
    'SELECT * FROM play_encounters WHERE campaign_id = ? AND id = ?',
    [campaign_id, encounter_id]
  ).first
  halt 404, { error: 'encounter not found' }.to_json unless encounter
  encounter
end

def play_member_usernames(campaign_id)
  db.execute(
    'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC',
    [campaign_id]
  ).map { |row| row['username'] }
end

def find_play_member_by_character!(campaign_id, character_id)
  member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
    [campaign_id, character_id]
  ).first
  halt 404, { error: 'character not found' }.to_json unless member
  member
end

# The current owner of a campaign character. Falls back to the joining
# member's username when no explicit ownership row exists yet (e.g. a
# character created before this table was introduced).
def play_character_owner(campaign_id, character_id, member)
  row = db.execute(
    'SELECT owner FROM play_character_owners WHERE campaign_id = ? AND character_id = ?',
    [campaign_id, character_id]
  ).first
  return row['owner'] if row
  member['username']
end

def next_play_event_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_campaign_events WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

# Inserts the next event for a campaign and returns its assigned sequence.
def insert_play_event(campaign_id, kind:, actor:, text:, type: nil, target: nil)
  sequence = next_play_event_sequence(campaign_id)
  db.execute(
    'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign_id, sequence, kind, actor, type, target, text]
  )
  sequence
end

# Deterministic initiative order for an encounter's combatants. Monsters
# and bound party members share one combatants_json array; sort by
# initiative desc, name asc as a tiebreak (mirrors order_combatants) unless
# a delay has recorded an explicit turn_order_json override, in which case
# that order is honored (with any combatant missing from it — e.g. newly
# added after the delay — appended in natural sort order).
def encounter_combat_order(encounter)
  combatants = JSON.parse(encounter['combatants_json'])
  natural = ->(list) { list.sort_by { |c| [-c['initiative'], c['name']] } }

  override = encounter['turn_order_json']
  return natural.call(combatants) if override.nil?

  keys = JSON.parse(override)
  by_key = combatants.each_with_object({}) { |c, acc| acc[encounter_combatant_target_key(c)] = c }
  ordered = keys.map { |k| by_key[k] }.compact
  leftover = combatants.reject { |c| keys.include?(encounter_combatant_target_key(c)) }

  ordered + natural.call(leftover)
end

def encounter_combatant_kind(combatant)
  combatant.key?('monster_id') ? 'monster' : 'player'
end

def encounter_combatant_payload(combatant)
  { name: combatant['name'], kind: encounter_combatant_kind(combatant), initiative: combatant['initiative'] }
end

# Applies a signed HP delta (positive = healing, negative = damage) to an
# encounter combatant, clamped to [0, hp_max]. The target may be a monster
# (matched by monster_id in combatants_json) or a bound party member
# (matched by member/username, whose HP lives on play_campaign_members).
# Returns [hp_before, hp_after].
def apply_encounter_hp_delta!(campaign_id, encounter, enc_id, target, delta)
  combatants = JSON.parse(encounter['combatants_json'])
  monster = combatants.find { |c| c['monster_id'] == target }

  if monster
    hp_before = monster['hp_current']
    hp_after = [[hp_before + delta, 0].max, monster['hp_max']].min
    monster['hp_current'] = hp_after

    db.execute(
      'UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
      [combatants.to_json, campaign_id, enc_id]
    )

    return [hp_before, hp_after]
  end

  member = combatants.find { |c| c['member'] == target }
  halt 400, { error: 'invalid target' }.to_json unless member

  party_member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign_id, target]
  ).first
  halt 400, { error: 'invalid target' }.to_json unless party_member

  hp_before = party_member['hp_current']
  hp_after = [[hp_before + delta, 0].max, party_member['hp_max']].min

  db.execute(
    'UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?',
    [hp_after, campaign_id, target]
  )

  [hp_before, hp_after]
end

# The identifier a target= parameter refers to: a monster's monster_id, or
# a bound party member's username. Conditions and turn-order matching both
# key off this value.
def encounter_combatant_target_key(combatant)
  combatant['monster_id'] || combatant['member']
end

def encounter_conditions_map(encounter)
  conditions = JSON.parse(encounter['conditions_json'] || '{}')
  conditions.each_with_object({}) do |(target, conds), acc|
    next if conds.empty?

    acc[target] = conds.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
  end
end

# Decrements remaining_rounds for every condition on the combatant whose
# turn is starting, dropping any that hit zero, and persists the result.
def tick_encounter_conditions!(campaign_id, enc_id, encounter, target_key)
  conditions = JSON.parse(encounter['conditions_json'] || '{}')
  list = conditions[target_key]
  return if list.nil? || list.empty?

  list.each { |c| c['remaining_rounds'] -= 1 }
  list.reject! { |c| c['remaining_rounds'] <= 0 }
  conditions[target_key] = list

  db.execute(
    'UPDATE play_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?',
    [conditions.to_json, campaign_id, enc_id]
  )
end

# True when username holds an active campaign delegation that includes
# the given power (e.g. 'narrate').
def play_active_delegate_power?(campaign_id, username, power)
  row = db.execute(
    'SELECT powers_json FROM play_delegations WHERE campaign_id = ? AND username = ? AND active = 1',
    [campaign_id, username]
  ).first
  return false unless row

  JSON.parse(row['powers_json']).include?(power)
end

def recent_play_events(campaign_id, limit: 10)
  db.execute(
    'SELECT sequence, kind, actor, text FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?',
    [campaign_id, limit]
  ).reverse.map do |event|
    { sequence: event['sequence'], kind: event['kind'], actor: event['actor'], text: event['text'] }
  end
end
