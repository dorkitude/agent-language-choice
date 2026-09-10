# frozen_string_literal: true

# Route definitions for play-campaign quests with prerequisite dependencies.

# --- Create quest ---
post '/v1/play/campaigns/:id/quests' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_play_quest_body!(body)

  quest_id = body['quest_id']
  title = body['title']
  depends_on = body['depends_on']

  unless depends_on.all? { |dep| Storage.play_campaign_quest_exists?(campaign_id, dep) }
    json_error(400, 'invalid dependencies')
  end

  if Storage.play_campaign_quest_exists?(campaign_id, quest_id)
    json_error(409, 'quest already exists')
  end

  Storage.create_play_campaign_quest(campaign_id, quest_id, title, depends_on)

  status 201
  JSON.dump(
    quest_id: quest_id,
    title: title,
    depends_on: depends_on,
    state: 'locked'
  )
end

# --- Update quest state ---
put '/v1/play/campaigns/:id/quests/:quest_id/state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  quest = Storage.load_play_campaign_quest(campaign_id, params[:quest_id])
  json_error(404, 'quest not found') unless quest

  body = parse_json_body
  validate_play_quest_state_body!(body)

  new_state = body['state']
  current_state = quest[:state]

  valid_transition = case current_state
                     when 'locked'
                       new_state == 'active' && quest[:depends_on].all? do |dep_id|
                         dep = Storage.load_play_campaign_quest(campaign_id, dep_id)
                         dep && dep[:state] == 'completed'
                       end
                     when 'active'
                       new_state == 'completed'
                     else
                       false
                     end

  json_error(409, 'invalid state transition') unless valid_transition

  Storage.update_play_campaign_quest_state(campaign_id, quest[:quest_id], new_state)

  response = {
    quest_id: quest[:quest_id],
    title: quest[:title],
    depends_on: quest[:depends_on],
    state: new_state
  }
  response[:rewards] = quest[:rewards] if quest[:rewards]
  JSON.dump(response)
end

# --- Configure quest rewards ---
put '/v1/play/campaigns/:id/quests/:quest_id/rewards' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  quest = Storage.load_play_campaign_quest(campaign_id, params[:quest_id])
  json_error(404, 'quest not found') unless quest

  unless %w[locked active].include?(quest[:state])
    json_error(409, 'quest cannot be configured')
  end

  body = parse_json_body
  validate_play_quest_reward_body!(body)

  rewards = { 'xp' => body['xp'], 'items' => body['items'] }
  Storage.update_play_campaign_quest_rewards(campaign_id, quest[:quest_id], rewards)

  updated_quest = Storage.load_play_campaign_quest(campaign_id, quest[:quest_id])
  JSON.dump(
    quest_id: updated_quest[:quest_id],
    title: updated_quest[:title],
    depends_on: updated_quest[:depends_on],
    state: updated_quest[:state],
    rewards: updated_quest[:rewards]
  )
end

# --- Award quest rewards ---
post '/v1/play/campaigns/:id/quests/:quest_id/rewards/award' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  quest = Storage.load_play_campaign_quest(campaign_id, params[:quest_id])
  json_error(404, 'quest not found') unless quest

  json_error(409, 'rewards already awarded') if quest[:rewards_awarded]
  json_error(409, 'quest not completed') unless quest[:state] == 'completed'
  json_error(409, 'rewards not configured') unless quest[:rewards]

  rewards = quest[:rewards]
  xp = rewards['xp'] || rewards[:xp] || 0
  items = rewards['items'] || rewards[:items] || {}

  members = Storage.play_campaign_members(campaign_id)
  members.each do |member|
    Storage.increment_character_quest_rewards(campaign_id, member[:character_id], xp, items)
  end

  Storage.mark_play_campaign_quest_rewards_awarded(campaign_id, quest[:quest_id])

  status 201
  JSON.dump(
    quest_id: quest[:quest_id],
    awarded: true,
    xp: xp,
    items: items
  )
end

# --- List quests ---
get '/v1/play/campaigns/:id/quests' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  quests = Storage.load_play_campaign_quests(campaign_id)

  JSON.dump(quests: quests)
end

# --- Read cumulative quest rewards for a character ---
get '/v1/play/campaigns/:id/characters/:character_id/rewards' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  json_error(404, 'character not found') unless Storage.play_campaign_character_exists?(campaign_id, params[:character_id])

  rewards = Storage.load_character_quest_rewards(campaign_id, params[:character_id])

  JSON.dump(
    character_id: params[:character_id],
    xp: rewards[:xp],
    items: rewards[:items]
  )
end
