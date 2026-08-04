# Deterministic campaign quest records with prerequisite dependencies.
#
# Quests are created by the campaign DM and start in the `locked` state. They
# can be activated only when every prerequisite quest is completed, and can
# then be marked as completed. Players may list quests but cannot create or
# change them.
class PlayQuestsController < ApplicationController
  before_action :require_authentication

  VALID_STATES = %w[locked active completed].freeze

  # POST /v1/play/campaigns/:id/quests
  def create
    quest_id = @body['quest_id']
    title = @body['title']
    depends_on = @body['depends_on']

    unless valid_non_empty_string?(quest_id)
      bad_request('invalid quest_id')
      return
    end

    unless valid_non_empty_string?(title)
      bad_request('invalid title')
      return
    end

    unless depends_on.is_a?(Array) && depends_on.all? { |d| valid_non_empty_string?(d) }
      bad_request('invalid depends_on')
      return
    end

    unless depends_on.uniq.size == depends_on.size
      bad_request('invalid depends_on')
      return
    end

    if depends_on.include?(quest_id)
      bad_request('invalid depends_on')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      if depends_on.any? { |dep_id| !quest_exists?(campaign_id, dep_id) }
        bad_request('invalid depends_on')
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, quest_id, title, JSON.generate(depends_on), 'locked']
        )
        render json: {
          quest_id: quest_id,
          title: title,
          depends_on: depends_on,
          state: 'locked'
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'quest id taken' }, status: :conflict
      end
    end
  end

  # PUT /v1/play/campaigns/:id/quests/:quest_id/state
  def update_state
    new_state = @body['state']

    unless %w[active completed].include?(new_state)
      bad_request('invalid state')
      return
    end

    campaign_id = params[:id]
    quest_id = params[:quest_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      quest = find_play_quest(campaign_id, quest_id)
      return unless quest

      current_state = quest[3]
      depends_on = JSON.parse(quest[4] || '[]')

      allowed = case current_state
                when 'locked'
                  new_state == 'active' && dependencies_completed?(campaign_id, depends_on)
                when 'active'
                  new_state == 'completed'
                else
                  false
                end

      unless allowed
        render json: { error: 'invalid transition' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?',
        [new_state, campaign_id, quest_id]
      )

      render json: build_quest_response(
        quest[1],
        quest[2],
        depends_on,
        new_state,
        quest[5]
      ), status: :ok
    end
  end

  # GET /v1/play/campaigns/:id/quests
  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT quest_id, title, depends_on_json, state, rewards_json FROM play_campaign_quests WHERE campaign_id = ? ORDER BY id ASC',
        campaign_id
      )

      quests = rows.map do |row|
        build_quest_response(
          row[0],
          row[1],
          JSON.parse(row[2] || '[]'),
          row[3],
          row[4]
        )
      end

      render json: { quests: quests }, status: :ok
    end
  end

  # PUT /v1/play/campaigns/:id/quests/:quest_id/rewards
  def configure_rewards
    campaign_id = params[:id]
    quest_id = params[:quest_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      quest = find_play_quest(campaign_id, quest_id)
      return unless quest

      unless %w[locked active].include?(quest[3])
        render json: { error: 'quest already completed' }, status: :conflict
        return
      end

      xp = @body['xp']
      items = @body['items']

      unless xp.is_a?(Integer) && xp >= 0
        bad_request('invalid xp')
        return
      end

      unless items.is_a?(Hash)
        bad_request('invalid items')
        return
      end

      items.each do |item_id, quantity|
        unless valid_id?(item_id) && item_exists?(item_id) && quantity.is_a?(Integer) && quantity > 0
          bad_request('invalid items')
          return
        end
      end

      rewards = { 'xp' => xp, 'items' => items }
      GameStorage.db.execute(
        'UPDATE play_campaign_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?',
        [JSON.generate(rewards), campaign_id, quest_id]
      )

      render json: build_quest_response(
        quest_id,
        quest[2],
        JSON.parse(quest[4] || '[]'),
        quest[3],
        rewards
      ), status: :ok
    end
  end

  # POST /v1/play/campaigns/:id/quests/:quest_id/rewards/award
  def award
    campaign_id = params[:id]
    quest_id = params[:quest_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      quest = find_play_quest(campaign_id, quest_id)
      return unless quest

      unless quest[3] == 'completed'
        render json: { error: 'quest not completed' }, status: :conflict
        return
      end

      rewards_json = quest[5]
      if rewards_json.nil? || rewards_json.empty?
        render json: { error: 'rewards not configured' }, status: :conflict
        return
      end

      if quest_awarded?(campaign_id, quest_id)
        render json: { error: 'rewards already awarded' }, status: :conflict
        return
      end

      rewards = JSON.parse(rewards_json)
      GameStorage.db.execute(
        'INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, awarded) VALUES (?, ?, 1) ON CONFLICT(campaign_id, quest_id) DO UPDATE SET awarded = 1',
        [campaign_id, quest_id]
      )

      render json: {
        quest_id: quest_id,
        awarded: true,
        xp: rewards['xp'],
        items: rewards['items']
      }, status: :created
    end
  end

  # GET /v1/play/campaigns/:id/characters/:character_id/rewards
  def character_rewards
    campaign_id = params[:id]
    character_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      rows = GameStorage.db.execute(
        'SELECT q.rewards_json FROM play_campaign_quests q JOIN play_campaign_quest_rewards a ON q.campaign_id = a.campaign_id AND q.quest_id = a.quest_id WHERE q.campaign_id = ? AND a.awarded = 1',
        campaign_id
      )

      total_xp = 0
      total_items = {}
      rows.each do |row|
        rewards = JSON.parse(row[0] || '{}')
        total_xp += rewards['xp'].to_i
        (rewards['items'] || {}).each do |item_id, qty|
          total_items[item_id] = total_items.fetch(item_id, 0) + qty.to_i
        end
      end

      render json: {
        character_id: character_id,
        xp: total_xp,
        items: total_items
      }, status: :ok
    end
  end

  private

  # Look up a play campaign by id. Renders 404 and returns nil when missing.
  def find_play_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner, current_scene_id FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  # Look up a quest by campaign and quest id. Renders 404 and returns nil when missing.
  def find_play_quest(campaign_id, quest_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, quest_id, title, state, depends_on_json, rewards_json FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
      [campaign_id, quest_id]
    )
    if row.nil?
      render json: { error: 'quest not found' }, status: :not_found
      return nil
    end
    row
  end

  # True when a quest with the given id exists in the campaign.
  def quest_exists?(campaign_id, quest_id)
    !GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?',
      [campaign_id, quest_id]
    ).nil?
  end

  # True when every quest in +depends_on+ is completed in the campaign.
  def dependencies_completed?(campaign_id, depends_on)
    return true if depends_on.empty?

    rows = GameStorage.db.execute(
      "SELECT quest_id, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id IN (#{(['?'] * depends_on.length).join(',')})",
      [campaign_id, *depends_on]
    )

    return false if rows.length != depends_on.length

    rows.all? { |_, state| state == 'completed' }
  end

  # True when +username+ is the campaign owner or a member of the party.
  def campaign_member?(campaign_id, username, owner)
    return true if owner == username

    GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    )
  end

  # True when the item exists in the compendium catalog.
  def item_exists?(item_id)
    !GameStorage.db.get_first_value(
      'SELECT 1 FROM items WHERE slug = ?',
      item_id
    ).nil?
  end

  # True when the quest rewards have already been awarded.
  def quest_awarded?(campaign_id, quest_id)
    !GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ? AND awarded = 1',
      [campaign_id, quest_id]
    ).nil?
  end

  # Build a consistent quest record. +rewards+ may be a JSON string, a Hash,
  # or nil; it is included in the response only when present.
  def build_quest_response(quest_id, title, depends_on, state, rewards = nil)
    parsed_rewards = case rewards
                     when String then (rewards.empty? ? nil : JSON.parse(rewards))
                     when Hash then rewards
                     else nil
                     end

    response = {
      quest_id: quest_id,
      title: title,
      depends_on: depends_on,
      state: state
    }
    response[:rewards] = parsed_rewards if parsed_rewards
    response
  end
end
