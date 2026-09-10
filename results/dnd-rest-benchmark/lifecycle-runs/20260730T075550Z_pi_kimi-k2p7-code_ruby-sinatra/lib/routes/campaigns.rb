# frozen_string_literal: true

# Route definitions for campaigns endpoints.

# --- Campaigns ---

post '/v1/campaigns' do
  content_type :json
  body = parse_json_body

  validate_campaign_body!(body)

  json_error(409, 'campaign already exists') if Storage.campaign_exists?(body['id'])

  Storage.create_campaign(body['id'], body['name'], body['dm'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    dm: body['dm']
  )
end

post '/v1/campaigns/:id/characters' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  validate_character_body!(body)

  json_error(409, 'character already exists') if Storage.character_exists?(campaign_id, body['id'])

  Storage.create_character(campaign_id, body['id'], body['name'], body['level'], body['class'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    level: body['level'],
    class: body['class']
  )
end

post '/v1/campaigns/:id/events' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  validate_event_body!(body)

  json_error(409, 'event already exists') if Storage.event_exists?(campaign_id, body['id'])

  Storage.create_event(campaign_id, body['id'], body['kind'], body['summary'])

  status 201
  JSON.dump(
    id: body['id'],
    kind: body['kind']
  )
end

get '/v1/campaigns/:id/state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  json_error(404, 'campaign not found') unless campaign

  JSON.dump(
    id: campaign[:id],
    name: campaign[:name],
    dm: campaign[:dm],
    characters: Storage.campaign_characters(campaign_id),
    log_count: Storage.campaign_log_count(campaign_id)
  )
end

# --- Quests ---

post '/v1/campaigns/:id/quests' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  validate_quest_body!(body)

  json_error(409, 'quest already exists') if Storage.quest_exists?(campaign_id, body['id'])

  quest = {
    campaign_id: campaign_id,
    id: body['id'],
    title: body['title'],
    status: body['status'],
    milestones: body['milestones'],
    completed_milestones: []
  }

  Storage.create_quest(quest)

  status 201
  JSON.dump(
    id: quest[:id],
    title: quest[:title],
    status: quest[:status],
    milestones_total: quest[:milestones].length,
    milestones_done: 0
  )
end

get '/v1/campaigns/:id/quests/summary' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  quests = Storage.campaign_quests(campaign_id)
  summary = { active: 0, completed: 0, blocked: 0 }
  quests.each do |q|
    summary[q[:status].to_sym] += 1 if summary.key?(q[:status].to_sym)
  end

  JSON.dump(
    campaign_id: campaign_id,
    active: summary[:active],
    completed: summary[:completed],
    blocked: summary[:blocked]
  )
end

post '/v1/campaigns/:id/quests/:quest_id/progress' do
  content_type :json
  campaign_id = params[:id]
  quest_id = params[:quest_id]
  require_campaign_exists!(campaign_id)

  quest = Storage.load_quest(campaign_id, quest_id)
  json_error(404, 'quest not found') unless quest

  body = parse_json_body
  validate_progress_body!(body)

  completed = body['completed']
  quest[:completed_milestones] = (quest[:completed_milestones] + completed).select { |m| quest[:milestones].include?(m) }.uniq

  if quest[:milestones].length.positive? && quest[:completed_milestones].length == quest[:milestones].length
    quest[:status] = 'completed'
  end

  Storage.save_quest(quest)

  JSON.dump(
    id: quest[:id],
    status: quest[:status],
    milestones_total: quest[:milestones].length,
    milestones_done: quest[:completed_milestones].length
  )
end

# --- Factions and NPCs ---

post '/v1/campaigns/:id/factions' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  validate_faction_body!(body)

  json_error(409, 'faction already exists') if Storage.faction_exists?(campaign_id, body['id'])

  Storage.create_faction(campaign_id, body['id'], body['name'], body['stance'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    stance: body['stance']
  )
end

post '/v1/campaigns/:id/npcs' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  validate_npc_body!(body)

  json_error(404, 'faction not found') unless Storage.faction_exists?(campaign_id, body['faction_id'])

  json_error(409, 'npc already exists') if Storage.npc_exists?(campaign_id, body['id'])

  Storage.create_npc(campaign_id, body['id'], body['name'], body['faction_id'], body['disposition'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    faction_id: body['faction_id'],
    disposition: body['disposition']
  )
end

get '/v1/campaigns/:id/relationships' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  JSON.dump(
    campaign_id: campaign_id,
    factions: Storage.campaign_factions_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    friendly_npcs: Storage.campaign_friendly_npcs_count(campaign_id)
  )
end

# --- Inventory and equipment ---

post '/v1/campaigns/:id/inventory' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  body = parse_json_body
  validate_inventory_item_body!(body)

  Storage.add_inventory_item(campaign_id, body['item_slug'], body['owner'], body['quantity'])

  status 201
  JSON.dump(
    item_slug: body['item_slug'],
    quantity: body['quantity'],
    owner: body['owner']
  )
end

post '/v1/campaigns/:id/characters/:character_id/equipment' do
  content_type :json
  campaign_id = params[:id]
  character_id = params[:character_id]
  require_campaign_exists!(campaign_id)

  json_error(404, 'character not found') unless Storage.character_exists?(campaign_id, character_id)

  body = parse_json_body
  validate_equipment_assignment_body!(body)

  json_error(400, 'insufficient quantity') unless Storage.assign_equipment(campaign_id, character_id, body['item_slug'], body['quantity'])

  status 200
  JSON.dump(
    character_id: character_id,
    item_slug: body['item_slug'],
    quantity: body['quantity']
  )
end

get '/v1/campaigns/:id/inventory/summary' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  summary = Storage.inventory_summary(campaign_id)
  JSON.dump(
    campaign_id: campaign_id,
    party_items: summary[:party_items],
    assigned_items: summary[:assigned_items],
    healing_potions_available: summary[:healing_potions_available]
  )
end

