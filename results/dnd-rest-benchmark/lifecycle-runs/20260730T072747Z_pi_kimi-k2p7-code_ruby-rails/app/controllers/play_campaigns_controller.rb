# Turn-based play surface for D&D campaigns.
#
# The play surface is authenticated via `Authorization: Bearer session-<username>`.
# Only the reserved username 'dm' is treated as a DM; all other authenticated
# users are players. The DM owns a campaign, players join with a character, and
# once started the turn queue alternates player -> DM -> next player.
class PlayCampaignsController < ApplicationController
  before_action :require_authentication
  before_action :require_dm, only: [:create, :start, :nudge, :create_scene, :enter_scene, :close_scene, :create_location, :create_connection, :create_encounter, :add_monster, :remove_monster, :bind_member, :unbind_member, :damage, :heal, :character_damage, :add_condition, :rewards, :close_encounter, :end_encounter, :create_loot, :assign_loot, :create_npc, :update_npc_agenda, :create_dialogue, :create_faction, :create_reputation, :create_relationship, :update_relationship, :create_clue, :create_content, :update_content_tags, :create_export, :list_exports, :read_export, :create_import, :import_state, :create_backup, :list_backups, :restore_backup]
  before_action :require_player, only: [:add_member, :my_turn, :death_saves, :vote_loot]
  skip_before_action :require_authentication, only: [:create_spectator, :spectator_view]

  ABILITY_NAMES = %w[str dex con int wis cha].freeze
  VALID_RACES = %w[dwarf elf halfling human dragonborn gnome half-elf half-orc tiefling].freeze
  VALID_CLASSES = %w[barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard].freeze
  VALID_BACKGROUNDS = %w[acolyte charlatan criminal entertainer folk_hero guild_artisan hermit noble outlander sage sailor soldier urchin].freeze
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

  VALID_SKILLS = %w[
    athletics
    acrobatics
    sleight_of_hand
    stealth
    arcana
    history
    investigation
    nature
    religion
    animal_handling
    insight
    medicine
    perception
    survival
    deception
    intimidation
    performance
    persuasion
  ].freeze

  WIZARD_SPELLS = %w[
    acid-splash blade-ward chill-touch dancing-lights fire-bolt friends light
    mage-hand mending message minor-illusion poison-spray prestidigitation
    ray-of-frost shocking-grasp true-strike
    alarm burning-hands charm-person chromatic-orb color-spray
    comprehend-languages detect-magic disguise-self expeditious-retreat
    false-life feather-fall find-familiar fog-cloud grease identify jump
    longstrider mage-armor magic-missile protection-from-evil-and-good
    ray-of-sickness shield silent-image sleep tashas-hideous-laughter
    tensers-floating-disk thunderwave unseen-servant witch-bolt
    alter-self arcane-lock blindness-deafness blur cloud-of-daggers
    continual-flame crown-of-madness darkness darkvision detect-thoughts
    enlarge-reduce flaming-sphere gentle-repose gust-of-wind hold-person
    invisibility knock levitate locate-object magic-mouth magic-weapon
    mirror-image misty-step nystuls-magic-aura phantasmal-force
    ray-of-enfeeblement rope-trick scorching-ray see-invisibility shatter
    spider-climb suggestion web
    animate-dead bestow-curse blink clairvoyance counterspell dispel-magic
    fear feign-death fireball fly gaseous-form glyph-of-warding haste
    hypnotic-pattern leomunds-tiny-hut lightning-bolt magic-circle major-image
    phantom-steed protection-from-energy remove-curse sending sleet-storm
    slow stinking-cloud tongues vampiric-touch water-breathing
  ].freeze

  VALID_INVENTORY_ITEMS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze
  CONSUMABLE_ITEMS = %w[healing-potion].freeze
  EQUIPMENT_ITEMS = %w[leather-armor ring-of-protection amulet-of-health].freeze
  ITEM_SLOTS = {
    'leather-armor' => 'armor',
    'ring-of-protection' => 'accessory',
    'amulet-of-health' => 'accessory'
  }.freeze
  VALID_EQUIPMENT_SLOTS = %w[armor accessory].freeze
  ATTUNABLE_ITEMS = %w[ring-of-protection amulet-of-health].freeze

  CANONICAL_FIXTURE = {
    fixture_id: 'canonical-v1',
    status: 'seeded',
    characters: [
      { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
      { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' }
    ],
    story: 'The lantern is lit.',
    event_ids: ['fixture-event-1', 'fixture-event-2']
  }.freeze

  def create
    id = @body['id']
    name = @body['name']
    max_players = @body['max_players']

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless name.is_a?(String) && !name.empty?
      bad_request('invalid name')
      return
    end

    unless max_players.is_a?(Integer)
      bad_request('invalid max_players')
      return
    end

    owner = @current_user[:username]
    status = 'lobby'

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
          [id, name, owner, status, max_players]
        )
        render json: {
          id: id,
          name: name,
          owner: owner,
          status: status,
          max_players: max_players
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'play campaign id taken' }, status: :conflict
      end
    end
  end

  def create_spectator
    spectator_id = @body['spectator_id']

    unless valid_non_empty_string?(spectator_id)
      bad_request('invalid spectator_id')
      return
    end

    auth_header = request.authorization
    unless auth_header.to_s.start_with?('Bearer ')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    token = auth_header.to_s.sub('Bearer ', '').strip
    unless token.start_with?('session-')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    username = token.sub('session-', '').force_encoding(Encoding::UTF_8)
    if username.empty?
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    campaign_id = params[:id]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless campaign[1] == username && username == 'dm'
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_spectators WHERE spectator_id = ?',
        spectator_id
      )

      if existing
        render json: { error: 'spectator id taken' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_spectators (campaign_id, spectator_id) VALUES (?, ?)',
        [campaign_id, spectator_id]
      )

      render json: {
        spectator_id: spectator_id,
        token: "spectator-#{spectator_id}"
      }, status: :created
    end
  end

  def spectator_view
    auth_header = request.authorization
    unless auth_header.to_s.start_with?('Bearer ')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    token = auth_header.to_s.sub('Bearer ', '').strip

    if token.start_with?('session-')
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    unless token.start_with?('spectator-')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    spectator_id = token.sub('spectator-', '').force_encoding(Encoding::UTF_8)
    if spectator_id.empty?
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    campaign_id = params[:id]

    GameStorage.with_lock do
      spectator = GameStorage.db.get_first_row(
        'SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?',
        spectator_id
      )

      unless spectator
        render json: { error: 'unauthorized' }, status: :unauthorized
        return
      end

      campaign = GameStorage.db.get_first_row(
        'SELECT id, name, status FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless spectator[0] == campaign_id
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      party_size = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?',
        campaign_id
      )

      story = GameStorage.db.get_first_value(
        'SELECT story FROM play_campaign_documents WHERE campaign_id = ?',
        campaign_id
      ) || ''

      render json: {
        campaign_id: campaign[0],
        name: campaign[1],
        status: campaign[2],
        party_size: party_size,
        story: story
      }, status: :ok
    end
  end

  def add_member
    character_id = @body['character_id']
    name = @body['name']
    class_name = @body['class']

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless name.is_a?(String) && !name.empty?
      bad_request('invalid name')
      return
    end

    unless class_name.is_a?(String) && !class_name.empty?
      bad_request('invalid class')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, status, max_players FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless campaign[1] == 'lobby'
        render json: { error: 'campaign is not in lobby' }, status: :conflict
        return
      end

      current_count = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?',
        campaign_id
      )

      if current_count >= campaign[2]
        render json: { error: 'party is full' }, status: :conflict
        return
      end

      existing_member = GameStorage.db.get_first_row(
        'SELECT username, character_id FROM play_campaign_members WHERE campaign_id = ? AND (username = ? OR character_id = ?)',
        [campaign_id, username, character_id]
      )

      if existing_member
        if existing_member[0] == username
          render json: { error: 'already a member' }, status: :conflict
        else
          render json: { error: 'character id taken' }, status: :conflict
        end
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, username, character_id, name, class_name, username, 10]
      )

      render json: {
        username: username,
        character_id: character_id,
        name: name,
        class: class_name,
        owner: username
      }, status: :created
    end
  end

  def onboarding
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      is_owner = owner == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      if is_owner
        render json: {
          role: 'dm',
          next_steps: ['configure-safety', 'invite-players', 'start-campaign'],
          can_mutate: true
        }, status: :ok
      else
        render json: {
          role: 'player',
          next_steps: ['review-party', 'take-turn', 'submit-action'],
          can_mutate: true
        }, status: :ok
      end
    end
  end

  def start
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, status FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      if campaign[1] == 'active'
        render json: { error: 'campaign already active' }, status: :conflict
        return
      end

      member_count = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?',
        campaign_id
      )

      if member_count < 2
        render json: { error: 'campaign requires at least two party members' }, status: :conflict
        return
      end

      current_actor = GameStorage.db.get_first_value(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY ROWID LIMIT 1',
        campaign_id
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, nudge_count = 0, turn_deadline = ? WHERE id = ?',
        ['active', current_actor, 1, 2, campaign_id]
      )

      render json: {
        id: campaign_id,
        status: 'active',
        current_actor: current_actor,
        turn_number: 1
      }, status: :ok
    end
  end

  def narration
    text = @body['text']

    unless text.is_a?(String) && !text.empty?
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless can_narrate?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'narration', username, text]
      )

      render json: {
        sequence: next_sequence,
        kind: 'narration',
        actor: username,
        text: text
      }, status: :created
    end
  end

  def create_message
    text = @body['text']

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'chat', username, text]
      )

      render json: {
        kind: 'chat',
        actor: username,
        text: text
      }, status: :created
    end
  end

  def turn
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, turn_number, nudge_count, turn_deadline, phase FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      phase = if campaign[2] == 'active'
                stored_phase = campaign[7] || 'exploration'
                if stored_phase == 'combat'
                  'combat'
                elsif campaign[3] == 'dm'
                  'exploration'
                else
                  'player'
                end
              else
                'setup'
              end

      members = party_usernames(campaign_id)
      queue = members.flat_map { |username| [username, 'dm'] }

      render json: {
        campaign_id: campaign[0],
        current_actor: campaign[3],
        phase: phase,
        turn_number: campaign[4],
        overdue: false,
        logical_deadline: campaign[4] + 1,
        queue: queue
      }, status: :ok
    end
  end

  def nudge
    message = @body['message']

    unless message.is_a?(String) && !message.empty?
      bad_request('invalid message')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, nudge_count, turn_deadline FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless campaign[2] == 'active'
        render json: { error: 'campaign is not active' }, status: :conflict
        return
      end

      new_count = campaign[4] + 1
      GameStorage.db.execute(
        'UPDATE play_campaigns SET nudge_count = ? WHERE id = ?',
        [new_count, campaign_id]
      )

      nudge_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, nudge_sequence, 'nudge', username, message]
      )

      render json: {
        actor: username,
        target: campaign[3],
        message: message,
        nudge_count: new_count
      }, status: :created
    end
  end

  def my_turn
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      current_actor = campaign[1]
      is_my_turn = current_actor == username

      render json: {
        is_my_turn: is_my_turn,
        current_actor: current_actor,
        character: { id: member[0], name: member[1] },
        recent_events: recent_events(campaign_id)
      }, status: :ok
    end
  end

  def gm_status
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      owner = campaign[1]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      current_actor = campaign[2]
      needs_attention = current_actor == owner

      party = GameStorage.db.execute(
        'SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY ROWID',
        campaign_id
      ).map do |row|
        { username: row[0], character_id: row[1], name: row[2], class: row[3] }
      end

      render json: {
        needs_attention: needs_attention,
        current_actor: current_actor,
        party: party,
        recent_events: recent_events(campaign_id)
      }, status: :ok
    end
  end

  def action
    type = @body['type']
    text = @body['text']

    unless type.is_a?(String) && !type.empty?
      bad_request('invalid type')
      return
    end

    unless text.is_a?(String) && !text.empty?
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      if username == campaign[1] || campaign[2] != 'active' || campaign[3] != username
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, type, next_actor) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'action', username, text, type, 'dm']
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_actor = ?, turn_deadline = ? WHERE id = ?',
        ['dm', campaign[4] + 1, campaign_id]
      )

      render json: {
        sequence: next_sequence,
        kind: 'action',
        actor: username,
        type: type,
        text: text,
        next_actor: 'dm'
      }, status: :created
    end
  end

  def resolution
    text = @body['text']

    unless text.is_a?(String) && !text.empty?
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      owner = campaign[1]

      unless username == owner && campaign[2] == 'active' && campaign[3] == owner
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      members = party_usernames(campaign_id)

      last_player_event = GameStorage.db.get_first_row(
        'SELECT actor FROM play_campaign_events WHERE campaign_id = ? AND kind IN (?, ?) ORDER BY sequence DESC LIMIT 1',
        [campaign_id, 'action', 'travel']
      )

      next_index = if last_player_event
                     index = members.index(last_player_event[0])
                     index ? (index + 1) % members.length : 0
                   else
                     0
                   end

      next_actor = members[next_index]
      new_turn_number = campaign[4] + 1

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, next_actor) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'resolution', owner, text, next_actor]
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_actor = ?, turn_number = ?, turn_deadline = ? WHERE id = ?',
        [next_actor, new_turn_number, new_turn_number + 1, campaign_id]
      )

      render json: {
        sequence: next_sequence,
        kind: 'resolution',
        actor: owner,
        text: text,
        next_actor: next_actor,
        turn_number: new_turn_number
      }, status: :created
    end
  end

  def create_scene
    scene_id = @body['id']
    name = @body['name']

    unless valid_id?(scene_id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
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

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)',
          [campaign_id, scene_id, name, 'open']
        )

        scene_sequence = GameStorage.db.get_first_value(
          'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
          campaign_id
        )
        GameStorage.db.execute(
          'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, scene_sequence, 'scene', username, scene_id]
        )

        render json: { id: scene_id, name: name, status: 'open' }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'scene id taken' }, status: :conflict
      end
    end
  end

  def enter_scene
    scene_id = params[:scene_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      scene = find_scene(campaign_id, scene_id)
      return unless scene

      unless scene[2] == 'open'
        render json: { error: 'scene is closed' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?',
        [scene_id, campaign_id]
      )

      render json: { current_scene_id: scene_id, name: scene[1] }, status: :ok
    end
  end

  def close_scene
    scene_id = params[:scene_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      scene = find_scene(campaign_id, scene_id)
      return unless scene

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_scene_id = CASE WHEN current_scene_id = ? THEN NULL ELSE current_scene_id END WHERE id = ?',
        [scene_id, campaign_id]
      )

      GameStorage.db.execute(
        'UPDATE play_campaign_scenes SET status = ? WHERE campaign_id = ? AND id = ?',
        ['closed', campaign_id, scene_id]
      )

      render json: { id: scene_id, status: 'closed' }, status: :ok
    end
  end

  def current_scene
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      current_scene_id = campaign[2]
      unless current_scene_id
        render json: { error: 'no current scene' }, status: :not_found
        return
      end

      scene = GameStorage.db.get_first_row(
        'SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?',
        [campaign_id, current_scene_id]
      )

      unless scene
        render json: { error: 'no current scene' }, status: :not_found
        return
      end

      render json: { id: scene[0], name: scene[1], status: scene[2] }, status: :ok
    end
  end

  def create_location
    location_id = @body['id']
    name = @body['name']

    unless valid_id?(location_id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
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

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)',
          [campaign_id, location_id, name]
        )
        render json: { id: location_id, name: name }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'location id taken' }, status: :conflict
      end
    end
  end

  def create_connection
    from_id = params[:from_id]
    to_id = @body['to_id']
    travel_turns = @body['travel_turns']

    unless valid_id?(from_id)
      bad_request('invalid from_id')
      return
    end

    unless valid_id?(to_id)
      bad_request('invalid to_id')
      return
    end

    unless travel_turns.is_a?(Integer)
      bad_request('invalid travel_turns')
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

      from_exists = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?',
        [campaign_id, from_id]
      )
      to_exists = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?',
        [campaign_id, to_id]
      )

      unless from_exists && to_exists
        bad_request('missing location')
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
        [campaign_id, from_id, to_id]
      )

      if existing
        bad_request('already connected')
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)',
        [campaign_id, from_id, to_id, travel_turns]
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_location_id = COALESCE(current_location_id, ?) WHERE id = ?',
        [from_id, campaign_id]
      )

      render json: { from_id: from_id, to_id: to_id, travel_turns: travel_turns }, status: :created
    end
  end

  def travel_turn
    destination_id = @body['destination_id']

    unless valid_id?(destination_id)
      bad_request('invalid destination_id')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, turn_number, current_location_id FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      if username == campaign[1] || campaign[2] != 'active' || campaign[3] != username
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT username FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      current_location_id = campaign[5]

      connection = GameStorage.db.get_first_row(
        'SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
        [campaign_id, current_location_id, destination_id]
      )

      unless connection
        render json: { error: 'invalid destination' }, status: :conflict
        return
      end

      travel_turns = connection[0]
      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, destination_id, travel_turns, next_actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'travel', username, '', destination_id, travel_turns, 'dm']
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_actor = ?, turn_deadline = ?, current_location_id = ? WHERE id = ?',
        ['dm', campaign[4] + 1, destination_id, campaign_id]
      )

      render json: {
        sequence: next_sequence,
        kind: 'travel',
        actor: username,
        destination_id: destination_id,
        travel_turns: travel_turns,
        next_actor: 'dm'
      }, status: :created
    end
  end

  def rest
    type = @body['type']

    unless type.is_a?(String) && %w[short long].include?(type)
      bad_request('invalid type')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      if username == campaign[1] || campaign[2] != 'active' || campaign[3] != username
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT username, hp_current, hp_max, status, death_save_successes, death_save_failures, class, level FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      hp_current = member[1] || 20
      hp_max = member[2] || 20
      status = member[3] || 'conscious'
      successes = member[4] || 0
      failures = member[5] || 0
      class_name = member[6]
      level = member[7] || 1

      if type == 'long'
        hp_current = hp_max
        new_status = (hp_current > 0 && status != 'conscious') ? 'conscious' : status
        new_successes = (new_status == 'conscious' && (successes > 0 || failures > 0)) ? 0 : successes
        new_failures = (new_status == 'conscious' && (successes > 0 || failures > 0)) ? 0 : failures
        GameStorage.db.execute(
          'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
          [hp_current, new_status, new_successes, new_failures, campaign_id, username]
        )

        if spellcasting_class?(class_name)
          slots = full_spell_slots(class_name, level)
          GameStorage.db.execute(
            'UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND username = ?',
            [JSON.generate(slots), campaign_id, username]
          )
        end
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, type, next_actor, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'rest', username, '', type, 'dm', hp_current, hp_max]
      )

      GameStorage.db.execute(
        'UPDATE play_campaigns SET current_actor = ?, turn_deadline = ? WHERE id = ?',
        ['dm', campaign[4] + 1, campaign_id]
      )

      render json: {
        sequence: next_sequence,
        kind: 'rest',
        actor: username,
        type: type,
        hp_current: hp_current,
        hp_max: hp_max,
        next_actor: 'dm'
      }, status: :created
    end
  end

  def create_encounter
    encounter_id = @body['id']
    name = @body['name']

    unless valid_id?(encounter_id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
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

      duplicate_id = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?',
        [campaign_id, encounter_id]
      )

      if duplicate_id
        render json: { error: 'duplicate encounter id' }, status: :conflict
        return
      end

      in_combat = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = ?',
        [campaign_id, 'active']
      )

      if in_combat
        render json: { error: 'campaign already in combat' }, status: :conflict
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_encounters (campaign_id, id, name, status, combatants_json, round, turn_index, order_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, encounter_id, name, 'active', '[]', 1, 0, '[]']
        )

        GameStorage.db.execute(
          'UPDATE play_campaigns SET phase = ?, saved_actor = current_actor WHERE id = ?',
          ['combat', campaign_id]
        )

        render json: {
          id: encounter_id,
          name: name,
          status: 'active',
          combatants: []
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'duplicate encounter id' }, status: :conflict
      end
    end
  end

  def add_monster
    monster_id = @body['monster_id']
    name = @body['name']
    hp_max = @body['hp_max']
    initiative = @body['initiative']

    unless valid_id?(monster_id)
      bad_request('invalid monster_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless hp_max.is_a?(Integer)
      bad_request('invalid hp_max')
      return
    end

    unless initiative.is_a?(Integer)
      bad_request('invalid initiative')
      return
    end

    encounter_id = params[:enc_id]
    unless valid_id?(encounter_id)
      bad_request('invalid encounter id')
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

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      if combatants.any? { |c| c['monster_id'] == monster_id }
        render json: { error: 'duplicate monster id' }, status: :conflict
        return
      end

      monster = {
        'monster_id' => monster_id,
        'name' => name,
        'hp_max' => hp_max,
        'initiative' => initiative,
        'hp_current' => hp_max
      }
      combatants << monster

      order_json = encounter[7]
      if order_json && !order_json.empty? && order_json != '[]'
        keys = JSON.parse(order_json)
        keys << monster_id
        order_json = JSON.generate(keys)
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(combatants), order_json, campaign_id, encounter_id]
      )

      render json: monster, status: :created
    end
  end

  def remove_monster
    encounter_id = params[:enc_id]
    monster_id = params[:monster_id]

    unless valid_id?(encounter_id)
      bad_request('invalid encounter id')
      return
    end

    unless valid_id?(monster_id)
      bad_request('invalid monster_id')
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

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      index = combatants.index { |c| c['monster_id'] == monster_id }
      unless index
        render json: { error: 'monster not found' }, status: :not_found
        return
      end

      combatants.delete_at(index)
      conditions = JSON.parse(encounter[6] || '{}')
      conditions.delete(monster_id)
      new_turn_index = clamp_turn_index(encounter[5] || 0, combatants.length)
      order_json = encounter[7]
      if order_json && !order_json.empty? && order_json != '[]'
        keys = JSON.parse(order_json)
        keys.delete(monster_id)
        order_json = JSON.generate(keys)
      end
      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ?, turn_index = ?, conditions_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(combatants), new_turn_index, JSON.generate(conditions), order_json, campaign_id, encounter_id]
      )

      render json: { removed: monster_id }, status: :ok
    end
  end

  def travel
    loc_id = params[:loc_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    unless valid_id?(loc_id)
      bad_request('invalid location id')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      loc_exists = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?',
        [campaign_id, loc_id]
      )

      unless loc_exists
        render json: { error: 'location not found' }, status: :not_found
        return
      end

      destinations = GameStorage.db.execute(
        'SELECT c.to_id, l.name, c.travel_turns FROM play_campaign_location_connections c JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.id WHERE c.campaign_id = ? AND c.from_id = ? ORDER BY c.to_id',
        [campaign_id, loc_id]
      ).map do |row|
        { id: row[0], name: row[1], travel_turns: row[2] }
      end

      render json: { destinations: destinations }, status: :ok
    end
  end

  def document
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      owner = campaign[1]
      is_owner = owner == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      doc = GameStorage.db.get_first_row(
        'SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?',
        campaign_id
      ) || ['', '']

      response = { story: doc[0] }
      response[:dm_notes] = doc[1] if is_owner
      render json: response, status: :ok
    end
  end

  def update_document
    story = @body['story']
    dm_notes = @body['dm_notes']

    unless story.is_a?(String)
      bad_request('invalid story')
      return
    end

    unless dm_notes.is_a?(String)
      bad_request('invalid dm_notes')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id, owner FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes',
        [campaign_id, story, dm_notes]
      )

      render json: { story: story, dm_notes: dm_notes }, status: :ok
    end
  end

  def bind_member
    member_username = @body['member']
    initiative = @body['initiative']

    unless valid_id?(member_username)
      bad_request('invalid member')
      return
    end

    unless initiative.is_a?(Integer)
      bad_request('invalid initiative')
      return
    end

    encounter_id = params[:enc_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, member_username]
      )

      unless member
        bad_request('member not found')
        return
      end

      combatants = JSON.parse(encounter[3] || '[]')
      if combatants.any? { |c| c['member'] == member_username }
        render json: { error: 'member already bound' }, status: :conflict
        return
      end

      combatant = {
        'member' => member_username,
        'character_id' => member[1],
        'name' => member[2],
        'initiative' => initiative
      }
      combatants << combatant

      order_json = encounter[7]
      if order_json && !order_json.empty? && order_json != '[]'
        keys = JSON.parse(order_json)
        keys << member_username
        order_json = JSON.generate(keys)
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(combatants), order_json, campaign_id, encounter_id]
      )

      render json: combatant, status: :created
    end
  end

  def unbind_member
    member_username = params[:member]
    encounter_id = params[:enc_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      index = combatants.index { |c| c['member'] == member_username }
      unless index
        render json: { error: 'member not found' }, status: :not_found
        return
      end

      combatants.delete_at(index)
      conditions = JSON.parse(encounter[6] || '{}')
      conditions.delete(member_username)
      new_turn_index = clamp_turn_index(encounter[5] || 0, combatants.length)
      order_json = encounter[7]
      if order_json && !order_json.empty? && order_json != '[]'
        keys = JSON.parse(order_json)
        keys.delete(member_username)
        order_json = JSON.generate(keys)
      end
      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET combatants_json = ?, turn_index = ?, conditions_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(combatants), new_turn_index, JSON.generate(conditions), order_json, campaign_id, encounter_id]
      )

      render json: { removed: member_username }, status: :ok
    end
  end

  def encounter_turn
    campaign_id = params[:id]
    enc_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, enc_id)
      return unless encounter

      round, turn_index, active = current_encounter_state(encounter)
      render json: {
        round: round,
        turn_index: turn_index,
        active: active ? serialize_active_combatant(active) : nil
      }, status: :ok
    end
  end

  def turn_delay
    campaign_id = params[:id]
    enc_id = params[:enc_id]
    username = @current_user[:username]

    target_index = parse_optional_index(@body['index'] || @body['position'])
    if target_index == :invalid
      bad_request('invalid index')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, enc_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      ordered = encounter_turn_order(combatants, encounter[7])
      count = ordered.length

      if count == 0
        render json: { error: 'no combatants' }, status: :conflict
        return
      end

      turn_index = clamp_turn_index(encounter[5] || 0, count)
      active = ordered[turn_index]

      is_owner = campaign[1] == username
      is_current = active && active['member'].is_a?(String) && active['member'] == username
      unless is_owner || is_current
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      target_index = count - 1 if target_index.nil?

      if target_index <= turn_index || target_index >= count
        bad_request('illegal index')
        return
      end

      ordered.delete_at(turn_index)
      ordered.insert(target_index, active)

      new_order_keys = ordered.map { |c| combatant_key(c) }
      # The delayed combatant remains the current actor but now occupies the
      # later position in the order; the next advance will move past them.
      new_turn_index = target_index

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET order_json = ?, turn_index = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(new_order_keys), new_turn_index, campaign_id, enc_id]
      )

      render json: {
        order: ordered.map { |c| serialize_active_combatant(c) }
      }, status: :ok
    end
  end

  def turn_ready
    campaign_id = params[:id]
    enc_id = params[:enc_id]
    username = @current_user[:username]

    trigger = @body['trigger']
    unless valid_non_empty_string?(trigger)
      bad_request('invalid trigger')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, enc_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      ordered = encounter_turn_order(combatants, encounter[7])
      count = ordered.length

      if count == 0
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      turn_index = clamp_turn_index(encounter[5] || 0, count)
      active = ordered[turn_index]

      unless active && active['member'].is_a?(String) && active['member'] == username
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )
      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'ready', username, trigger]
      )

      render json: {
        actor: username,
        trigger: trigger
      }, status: :created
    end
  end

  def encounter_advance
    campaign_id = params[:id]
    enc_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, enc_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      ordered = encounter_turn_order(combatants, encounter[7])
      count = ordered.length

      if count == 0
        render json: { error: 'no combatants' }, status: :conflict
        return
      end

      round = encounter[4] || 1
      turn_index = clamp_turn_index(encounter[5] || 0, count)
      active = ordered[turn_index]

      is_current_player = active && active['member'].is_a?(String) && active['member'] == username
      unless is_owner || is_current_player
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      new_turn_index = (turn_index + 1) % count
      new_round = new_turn_index == 0 ? round + 1 : round
      new_active = ordered[new_turn_index]

      conditions = JSON.parse(encounter[6] || '{}')
      target_key = combatant_key(new_active)
      if conditions[target_key]
        conditions[target_key].each do |cond|
          cond['remaining_rounds'] -= 1
        end
        conditions[target_key].reject! { |cond| cond['remaining_rounds'] <= 0 }
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET round = ?, turn_index = ?, conditions_json = ? WHERE campaign_id = ? AND id = ?',
        [new_round, new_turn_index, JSON.generate(conditions), campaign_id, enc_id]
      )

      render json: {
        round: new_round,
        turn_index: new_turn_index,
        active: serialize_active_combatant(new_active)
      }, status: :ok
    end
  end

  def combat_action
    type = @body['type']
    target = @body['target']
    text = @body['text']

    unless type.is_a?(String) && %w[attack help dodge ready].include?(type)
      bad_request('invalid type')
      return
    end

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    encounter_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      unless encounter[2] == 'active'
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      combatants = JSON.parse(encounter[3] || '[]')
      ordered = encounter_turn_order(combatants, encounter[7])
      count = ordered.length

      if count == 0
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      turn_index = clamp_turn_index(encounter[5] || 0, count)
      active = ordered[turn_index]

      unless active && active['member'].is_a?(String) && active['member'] == username
        render json: { error: 'not your turn' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, type, target) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'combat_action', username, text, type, target]
      )

      render json: {
        sequence: next_sequence,
        kind: 'combat_action',
        actor: username,
        type: type,
        target: target,
        text: text
      }, status: :created
    end
  end

  def damage
    target = @body['target']
    amount = @body['amount']

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    unless amount.is_a?(Integer) && amount >= 0
      bad_request('invalid amount')
      return
    end

    apply_hp_change(target, amount, 'damage')
  end

  def heal
    target = @body['target']
    amount = @body['amount']

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    unless amount.is_a?(Integer) && amount >= 0
      bad_request('invalid amount')
      return
    end

    apply_hp_change(target, amount, 'heal')
  end

  def add_condition
    target = @body['target']
    condition = @body['condition']
    duration_rounds = @body['duration_rounds']

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    unless valid_non_empty_string?(condition)
      bad_request('invalid condition')
      return
    end

    unless duration_rounds.is_a?(Integer) && duration_rounds > 0
      bad_request('invalid duration_rounds')
      return
    end

    campaign_id = params[:id]
    encounter_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      unless combatant_exists?(combatants, target)
        render json: { error: 'target not found' }, status: :not_found
        return
      end

      conditions = JSON.parse(encounter[6] || '{}')
      conditions[target] ||= []
      conditions[target] << { 'condition' => condition, 'remaining_rounds' => duration_rounds }

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?',
        [JSON.generate(conditions), campaign_id, encounter_id]
      )

      render json: {
        target: target,
        conditions: conditions[target].map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
      }, status: :created
    end
  end

  def encounter_status
    campaign_id = params[:id]
    enc_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, enc_id)
      return unless encounter

      round, turn_index, active = current_encounter_state(encounter)
      combatants = JSON.parse(encounter[3] || '[]')
      ordered = encounter_turn_order(combatants, encounter[7])
      conditions = JSON.parse(encounter[6] || '{}')

      existing_keys = ordered.map { |c| combatant_key(c) }.to_set
      conditions_map = {}
      conditions.each do |key, list|
        next unless existing_keys.include?(key)
        conditions_map[key] = list.map { |cond| { condition: cond['condition'], remaining_rounds: cond['remaining_rounds'] } }
      end

      render json: {
        round: round,
        turn_index: turn_index,
        active: active ? serialize_active_combatant(active) : nil,
        order: ordered.map { |c| serialize_active_combatant(c) },
        conditions: conditions_map
      }, status: :ok
    end
  end

  def rewards
    xp = @body['xp']
    loot = @body['loot']

    unless xp.is_a?(Integer)
      bad_request('invalid xp')
      return
    end

    unless loot.is_a?(Array)
      bad_request('invalid loot')
      return
    end

    loot.each do |item|
      unless item.is_a?(Hash) && valid_id?(item['slug']) && item['quantity'].is_a?(Integer) && item['quantity'] > 0
        bad_request('invalid loot')
        return
      end
    end

    encounter_id = params[:enc_id]
    unless valid_id?(encounter_id)
      bad_request('invalid encounter id')
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

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      if !encounter[8].nil? || (encounter[9] && encounter[9] != '[]')
        render json: { error: 'rewards already awarded' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET xp_awarded = ?, loot_json = ? WHERE campaign_id = ? AND id = ?',
        [xp, JSON.generate(loot), campaign_id, encounter_id]
      )

      render json: {
        id: encounter_id,
        xp: xp,
        loot: loot
      }, status: :ok
    end
  end

  def close_encounter
    encounter_id = params[:enc_id]
    unless valid_id?(encounter_id)
      bad_request('invalid encounter id')
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

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      GameStorage.db.execute(
        'UPDATE play_campaign_encounters SET status = ? WHERE campaign_id = ? AND id = ?',
        ['closed', campaign_id, encounter_id]
      )

      xp_awarded = encounter[8] || 0

      render json: {
        id: encounter_id,
        status: 'closed',
        xp_awarded: xp_awarded
      }, status: :ok
    end
  end

  def end_encounter
    encounter_id = params[:enc_id]
    unless valid_id?(encounter_id)
      bad_request('invalid encounter id')
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

      campaign_state = GameStorage.db.get_first_row(
        'SELECT phase, saved_actor, current_actor FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      phase = campaign_state[0] || 'exploration'

      if phase != 'combat'
        render json: { error: 'campaign is not in combat' }, status: :conflict
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      if encounter[2] == 'active'
        GameStorage.db.execute(
          'UPDATE play_campaign_encounters SET status = ? WHERE campaign_id = ? AND id = ?',
          ['closed', campaign_id, encounter_id]
        )
      end

      restored_actor = 'dm'
      GameStorage.db.execute(
        'UPDATE play_campaigns SET phase = ?, current_actor = ? WHERE id = ?',
        ['exploration', restored_actor, campaign_id]
      )

      render json: {
        campaign_id: campaign_id,
        status: 'active',
        phase: 'exploration',
        current_actor: restored_actor
      }, status: :ok
    end
  end

  def character_damage
    amount = @body['amount']

    unless amount.is_a?(Integer) && amount >= 0
      bad_request('invalid amount')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT username, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'target not found' }, status: :not_found
        return
      end

      hp_current = member[1] || 20
      hp_max = member[2] || 20
      status = member[3] || 'conscious'
      successes = member[4] || 0
      failures = member[5] || 0

      new_hp = [hp_current - amount, 0].max
      new_status = status
      new_successes = successes
      new_failures = failures

      if new_hp == 0 && status != 'dead'
        new_status = 'unconscious'
        new_successes = 0
        new_failures = 0
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
        [new_hp, new_status, new_successes, new_failures, campaign_id, char_id]
      )

      render json: { target: char_id, hp_before: hp_current, hp_after: new_hp, damage: amount }, status: :ok
    end
  end

  def death_saves
    outcome = @body['outcome']

    unless outcome.is_a?(String) && %w[success failure].include?(outcome)
      bad_request('invalid outcome')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'target not found' }, status: :not_found
        return
      end

      unless member[0] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      status = member[1] || 'conscious'
      successes = member[2] || 0
      failures = member[3] || 0

      unless status == 'unconscious'
        render json: { error: 'character is not unconscious' }, status: :conflict
        return
      end

      new_successes = successes
      new_failures = failures
      new_status = status

      if outcome == 'success'
        new_successes = [successes + 1, 3].min
        new_status = 'stable' if new_successes >= 3
      else
        new_failures = [failures + 1, 3].min
        new_status = 'dead' if new_failures >= 3
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
        [new_status, new_successes, new_failures, campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        successes: new_successes,
        failures: new_failures,
        status: new_status
      }, status: :created
    end
  end

  def character_status
    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'target not found' }, status: :not_found
        return
      end

      render json: {
        character_id: member[0],
        hp_current: member[1] || 20,
        hp_max: member[2] || 20,
        status: member[3] || 'conscious'
      }, status: :ok
    end
  end

  def owner
    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      render json: { character_id: member[0], owner: member[1] }, status: :ok
    end
  end

  def claim
    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      if member[2] && member[2] != username
        render json: { error: 'character already owned' }, status: :conflict
        return
      end

      if member[2].nil?
        GameStorage.db.execute(
          'UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
          [username, campaign_id, char_id]
        )
        render json: { character_id: char_id, owner: username }, status: :created
      else
        render json: { character_id: char_id, owner: username }, status: :ok
      end
    end
  end

  def transfer
    new_owner = @body['new_owner']

    unless valid_id?(new_owner)
      bad_request('invalid new_owner')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      new_owner_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, new_owner]
      )

      unless new_owner_member
        render json: { error: 'new owner is not a member' }, status: :bad_request
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
        [new_owner, campaign_id, char_id]
      )

      render json: { character_id: char_id, owner: new_owner }, status: :ok
    end
  end

  def build
    race = @body['race']
    class_name = @body['class']
    background = @body['background']
    abilities = @body['abilities']

    unless VALID_RACES.include?(race)
      bad_request('invalid race')
      return
    end

    unless VALID_CLASSES.include?(class_name)
      bad_request('invalid class')
      return
    end

    unless VALID_BACKGROUNDS.include?(background)
      bad_request('invalid background')
      return
    end

    unless abilities.is_a?(Hash)
      bad_request('invalid abilities')
      return
    end

    modifiers = {}
    ABILITY_NAMES.each do |name|
      score = abilities[name]
      unless score.is_a?(Integer) && score >= 1 && score <= 30
        bad_request('invalid ability score')
        return
      end
      modifiers[name] = modifier_for(score)
    end

    level = 1
    hp_max = HIT_DICE[class_name] + modifiers['con']
    proficiency_bonus = proficiency_bonus(level)

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      owner = member[2]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      slots = full_spell_slots(class_name, level)
      GameStorage.db.execute(
        'UPDATE play_campaign_members SET race = ?, class = ?, background = ?, hp_max = ?, hp_current = ?, abilities_json = ?, spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?',
        [race, class_name, background, hp_max, hp_max, JSON.generate(abilities), JSON.generate(slots), campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        race: race,
        class: class_name,
        background: background,
        level: level,
        hp_max: hp_max,
        proficiency_bonus: proficiency_bonus
      }, status: :ok
    end
  end

  def level_up
    level = @body['level']

    unless level.is_a?(Integer)
      bad_request('invalid level')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, level, hp_max, class, abilities_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      owner = member[2]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      current_level = member[3] || 1
      unless level == current_level + 1 && level <= 20
        bad_request('invalid level')
        return
      end

      class_name = member[5]
      hit_die = HIT_DICE[class_name]
      unless hit_die
        bad_request('invalid class')
        return
      end

      abilities = JSON.parse(member[6] || '{}')
      con_score = abilities['con']
      unless con_score.is_a?(Integer) && con_score >= 1 && con_score <= 30
        bad_request('missing abilities')
        return
      end

      con_mod = modifier_for(con_score)
      hp_increase = average_die(hit_die) + con_mod
      new_hp_max = (member[4] || 0) + hp_increase

      slots = full_spell_slots(class_name, level)
      GameStorage.db.execute(
        'UPDATE play_campaign_members SET level = ?, hp_max = ?, spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?',
        [level, new_hp_max, JSON.generate(slots), campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        level: level,
        hp_max: new_hp_max,
        hit_dice: "1d#{hit_die}",
        proficiency_bonus: proficiency_bonus(level)
      }, status: :ok
    end
  end

  def skill_check
    skill = @body['skill']
    ability = @body['ability']
    proficient = @body['proficient']
    roll = @body['roll']

    unless VALID_SKILLS.include?(skill)
      bad_request('invalid skill')
      return
    end

    unless ABILITY_NAMES.include?(ability)
      bad_request('invalid ability')
      return
    end

    unless proficient == true || proficient == false
      bad_request('invalid proficient')
      return
    end

    unless roll.is_a?(Integer)
      bad_request('invalid roll')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, level, abilities_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      owner = member[2]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      abilities = JSON.parse(member[4] || '{}')
      score = abilities[ability]
      unless score.is_a?(Integer) && score >= 1 && score <= 30
        bad_request('invalid ability score')
        return
      end

      level = member[3] || 1
      modifier = modifier_for(score) + (proficient ? proficiency_bonus(level) : 0)
      total = roll + modifier

      render json: {
        character_id: char_id,
        skill: skill,
        ability: ability,
        modifier: modifier,
        total: total
      }, status: :ok
    end
  end

  def add_spell
    spell_id = @body['spell_id']
    name = @body['name']
    level = @body['level']

    unless valid_id?(spell_id)
      bad_request('invalid spell_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless level.is_a?(Integer)
      bad_request('invalid level')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless spell_valid_for_class?(spell_id, member[3])
        render json: { error: 'invalid class/spell combination' }, status: :bad_request
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, char_id, spell_id, name, level]
        )
        render json: { spell_id: spell_id, name: name, level: level }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'duplicate spell' }, status: :conflict
      end
    end
  end

  def list_spells
    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      spells = GameStorage.db.execute(
        'SELECT spell_id, name, level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? ORDER BY level, spell_id',
        [campaign_id, char_id]
      ).map do |row|
        { spell_id: row[0], name: row[1], level: row[2] }
      end

      render json: { spells: spells }, status: :ok
    end
  end

  def prepare_spells
    spell_ids = @body['spell_ids']

    unless spell_ids.is_a?(Array)
      bad_request('invalid spell_ids')
      return
    end

    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless spellcasting_class?(member[3])
        bad_request('character cannot prepare spells')
        return
      end

      known = GameStorage.db.execute(
        'SELECT spell_id FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      ).map(&:first).to_set

      unless spell_ids.all? { |id| known.include?(id) }
        bad_request('unknown spell')
        return
      end

      max_prepared = member[4] || 1
      unless spell_ids.length <= max_prepared
        bad_request('too many prepared spells')
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET prepared_spells_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.generate(spell_ids), campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        prepared_spells: spell_ids,
        max_prepared: max_prepared
      }, status: :ok
    end
  end

  def get_prepared_spells
    campaign_id = params[:id]
    char_id = params[:char_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, level, prepared_spells_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      prepared = JSON.parse(member[2] || '[]')
      max_prepared = member[1] || 1

      render json: {
        character_id: char_id,
        prepared_spells: prepared,
        max_prepared: max_prepared
      }, status: :ok
    end
  end

  def cast_spell
    spell_id = @body['spell_id']
    target = @body['target']

    unless valid_id?(spell_id)
      bad_request('invalid spell_id')
      return
    end

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, class, level, prepared_spells_json, spell_slots_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      class_name = member[3]
      unless spellcasting_class?(class_name)
        bad_request('character is not a spellcaster')
        return
      end

      spell = GameStorage.db.get_first_row(
        'SELECT spell_id, level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )

      unless spell
        bad_request('spell not prepared')
        return
      end

      prepared = JSON.parse(member[5] || '[]')
      unless prepared.include?(spell_id)
        bad_request('spell not prepared')
        return
      end

      spell_level = spell[1]
      level = member[4] || 1
      full_slots = full_spell_slots(class_name, level)
      slots = JSON.parse(member[6] || '{}')
      slots = full_slots.transform_keys(&:to_s) if slots.nil? || slots.empty?

      slots_remaining = (slots[spell_level.to_s] || 0).to_i
      if slots_remaining <= 0
        render json: { error: 'no remaining spell slots' }, status: :conflict
        return
      end

      slots[spell_level.to_s] = slots_remaining - 1

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_casts WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, char_id, spell_id, target, spell_level, slots[spell_level.to_s], next_sequence]
      )

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.generate(slots), campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        spell_id: spell_id,
        target: target,
        slot_level: spell_level,
        slots_remaining: slots[spell_level.to_s],
        sequence: next_sequence
      }, status: :created
    end
  end

  def list_casts
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      casts = GameStorage.db.execute(
        'SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence',
        [campaign_id, char_id]
      ).map do |row|
        {
          character_id: char_id,
          spell_id: row[0],
          target: row[1],
          slot_level: row[2],
          slots_remaining: row[3],
          sequence: row[4]
        }
      end

      render json: { casts: casts }, status: :ok
    end
  end

  def set_concentration
    spell_id = @body['spell_id']
    target = @body['target']
    duration_turns = @body['duration_turns']

    unless valid_id?(spell_id)
      bad_request('invalid spell_id')
      return
    end

    unless valid_non_empty_string?(target)
      bad_request('invalid target')
      return
    end

    unless duration_turns.is_a?(Integer) && duration_turns >= 1
      bad_request('invalid duration_turns')
      return
    end

    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, class, prepared_spells_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      class_name = member[3]
      unless spellcasting_class?(class_name)
        bad_request('character is not a spellcaster')
        return
      end

      spell = GameStorage.db.get_first_row(
        'SELECT spell_id FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
        [campaign_id, char_id, spell_id]
      )

      unless spell
        bad_request('unknown spell')
        return
      end

      prepared = JSON.parse(member[4] || '[]')
      unless prepared.include?(spell_id)
        bad_request('spell not prepared')
        return
      end

      concentration = { spell_id: spell_id, target: target, remaining_turns: duration_turns }

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET concentration_json = ? WHERE campaign_id = ? AND character_id = ?',
        [JSON.generate(concentration), campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        concentration: concentration
      }, status: :ok
    end
  end

  def get_concentration
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, concentration_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      render json: {
        character_id: char_id,
        concentration: parse_concentration(member[1])
      }, status: :ok
    end
  end

  def advance_concentration
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, concentration_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      concentration = parse_concentration(member[1])

      if concentration
        concentration['remaining_turns'] -= 1
        if concentration['remaining_turns'] <= 0
          concentration = nil
        end
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET concentration_json = ? WHERE campaign_id = ? AND character_id = ?',
        [concentration ? JSON.generate(concentration) : nil, campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        concentration: concentration
      }, status: :ok
    end
  end

  def clear_concentration
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET concentration_json = NULL WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      render json: {
        character_id: char_id,
        concentration: nil
      }, status: :ok
    end
  end

  def add_inventory_item
    item_id = @body['item_id']
    quantity = @body['quantity']

    unless VALID_INVENTORY_ITEMS.include?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )

      if existing
        GameStorage.db.execute(
          'UPDATE play_campaign_inventory_items SET quantity = quantity + ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [quantity, campaign_id, char_id, item_id]
        )
      else
        GameStorage.db.execute(
          'INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
          [campaign_id, char_id, item_id, quantity]
        )
      end

      render json: {
        character_id: char_id,
        item_id: item_id,
        quantity: quantity,
        total_quantity: (existing || 0) + quantity
      }, status: :created
    end
  end

  def list_inventory_items
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = find_play_member(campaign_id, char_id)
      return unless member

      items = GameStorage.db.execute(
        'SELECT item_id, quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id',
        [campaign_id, char_id]
      ).map do |row|
        { item_id: row[0], quantity: row[1] }
      end

      render json: {
        character_id: char_id,
        items: items
      }, status: :ok
    end
  end

  def remove_inventory_item
    item_id = params[:item_id]
    quantity = @body['quantity']

    unless VALID_INVENTORY_ITEMS.include?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )

      unless row && row[0] >= quantity
        render json: { error: 'not enough items' }, status: :conflict
        return
      end

      new_total = row[0] - quantity
      if new_total == 0
        GameStorage.db.execute(
          'DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, char_id, item_id]
        )
      else
        GameStorage.db.execute(
          'UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [new_total, campaign_id, char_id, item_id]
        )
      end

      render json: {
        character_id: char_id,
        item_id: item_id,
        quantity: quantity,
        total_quantity: new_total
      }, status: :ok
    end
  end

  def consume
    item_id = params[:item_id]
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    unless CONSUMABLE_ITEMS.include?(item_id)
      if VALID_INVENTORY_ITEMS.include?(item_id)
        bad_request('not consumable')
      else
        bad_request('unknown item')
      end
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )

      unless row && row[0] > 0
        render json: { error: 'no items to consume' }, status: :conflict
        return
      end

      new_total = row[0] - 1
      if new_total == 0
        GameStorage.db.execute(
          'DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, char_id, item_id]
        )
      else
        GameStorage.db.execute(
          'UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [new_total, campaign_id, char_id, item_id]
        )
      end

      render json: {
        character_id: char_id,
        item_id: item_id,
        quantity_consumed: 1,
        total_quantity: new_total,
        effect: { type: 'healing', hp_restored: 5 }
      }, status: :ok
    end
  end

  def equip
    campaign_id = params[:id]
    char_id = params[:character_id]
    slot = params[:slot]
    item_id = @body['item_id']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(char_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_id?(slot) && VALID_EQUIPMENT_SLOTS.include?(slot)
      bad_request('invalid slot')
      return
    end

    unless valid_id?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless EQUIPMENT_ITEMS.include?(item_id)
      bad_request('unknown item')
      return
    end

    unless ITEM_SLOTS[item_id] == slot
      bad_request('slot mismatch')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      username = @current_user[:username]
      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      held = GameStorage.db.get_first_value(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, char_id, item_id]
      )

      unless held && held > 0
        bad_request('item not held')
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0',
        [campaign_id, char_id, slot, item_id, 0]
      )

      render json: {
        character_id: char_id,
        slot: slot,
        item_id: item_id,
        attuned: false
      }, status: :ok
    end
  end

  def get_equipment
    campaign_id = params[:id]
    char_id = params[:character_id]
    slot = params[:slot]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(char_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_id?(slot) && VALID_EQUIPMENT_SLOTS.include?(slot)
      bad_request('invalid slot')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      username = @current_user[:username]
      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT item_id, attuned FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, char_id, slot]
      )

      if row
        render json: {
          character_id: char_id,
          slot: slot,
          item_id: row[0],
          attuned: row[1] == 1
        }, status: :ok
      else
        render json: {
          character_id: char_id,
          slot: slot,
          item_id: '',
          attuned: false
        }, status: :ok
      end
    end
  end

  def attune
    campaign_id = params[:id]
    char_id = params[:character_id]
    slot = params[:slot]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(char_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_id?(slot) && VALID_EQUIPMENT_SLOTS.include?(slot)
      bad_request('invalid slot')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      member = find_play_member(campaign_id, char_id)
      return unless member

      username = @current_user[:username]
      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT item_id, attuned FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, char_id, slot]
      )

      unless row && ATTUNABLE_ITEMS.include?(row[0])
        bad_request('not attunable')
        return
      end

      item_id = row[0]

      attuned_count = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1',
        [campaign_id, char_id]
      )

      if attuned_count > 0
        render json: { error: 'already attuned' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?',
        [campaign_id, char_id, slot]
      )

      render json: {
        character_id: char_id,
        slot: slot,
        item_id: item_id,
        attuned: true,
        attunement_count: 1,
        max_attunements: 1
      }, status: :ok
    end
  end

  def currency
    campaign_id = params[:id]
    char_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, char_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      render json: {
        character_id: member[0],
        gold: member[1] || 10
      }, status: :ok
    end
  end

  def transfer_currency
    to_character_id = @body['to_character_id']
    gold = @body['gold']

    unless valid_id?(to_character_id)
      bad_request('invalid to_character_id')
      return
    end

    unless gold.is_a?(Integer) && gold > 0
      bad_request('invalid gold')
      return
    end

    campaign_id = params[:id]
    from_char_id = params[:character_id]
    username = @current_user[:username]

    if to_character_id == from_char_id
      bad_request('same character')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      from_member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, from_char_id]
      )

      unless from_member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      unless from_member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      to_member = GameStorage.db.get_first_row(
        'SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )

      unless to_member
        render json: { error: 'target not found' }, status: :bad_request
        return
      end

      from_gold = from_member[3] || 10
      if from_gold < gold
        render json: { error: 'insufficient gold' }, status: :conflict
        return
      end

      to_gold = to_member[1] || 10
      new_from_gold = from_gold - gold
      new_to_gold = to_gold + gold

      transfer_id = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_campaign_currency_transfers WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_from_gold, campaign_id, from_char_id]
      )
      GameStorage.db.execute(
        'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_to_gold, campaign_id, to_character_id]
      )
      GameStorage.db.execute(
        'INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, transfer_id, from_char_id, to_character_id, gold]
      )

      render json: {
        from_character_id: from_char_id,
        to_character_id: to_character_id,
        gold: gold,
        from_gold: new_from_gold,
        to_gold: new_to_gold,
        transfer_id: transfer_id
      }, status: :created
    end
  end

  # Loot distribution
  def create_loot
    loot_id = @body['loot_id']
    item_id = @body['item_id']
    quantity = @body['quantity']

    unless valid_id?(loot_id)
      bad_request('invalid loot_id')
      return
    end

    unless VALID_INVENTORY_ITEMS.include?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
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

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, loot_id, item_id, quantity, 'open']
        )
        render json: {
          loot_id: loot_id,
          item_id: item_id,
          quantity: quantity,
          status: 'open'
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'loot id taken' }, status: :conflict
      end
    end
  end

  def vote_loot
    recipient_character_id = @body['recipient_character_id']

    unless valid_id?(recipient_character_id)
      bad_request('invalid recipient_character_id')
      return
    end

    campaign_id = params[:id]
    loot_id = params[:loot_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      # Only players who are members of the campaign may vote.
      if username == campaign[1]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      loot = find_play_loot(campaign_id, loot_id)
      return unless loot

      unless loot[3] == 'open'
        render json: { error: 'loot is not open' }, status: :conflict
        return
      end

      recipient_exists = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, recipient_character_id]
      )

      unless recipient_exists
        render json: { error: 'recipient not found' }, status: :bad_request
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)',
          [campaign_id, loot_id, username, recipient_character_id]
        )
      rescue SQLite3::ConstraintException
        render json: { error: 'already voted' }, status: :conflict
        return
      end

      votes_for_recipient = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?',
        [campaign_id, loot_id, recipient_character_id]
      )

      render json: {
        loot_id: loot_id,
        voter: username,
        recipient_character_id: recipient_character_id,
        votes_for_recipient: votes_for_recipient
      }, status: :created
    end
  end

  def assign_loot
    campaign_id = params[:id]
    loot_id = params[:loot_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      loot = find_play_loot(campaign_id, loot_id)
      return unless loot

      unless loot[3] == 'open'
        render json: { error: 'loot is not open' }, status: :conflict
        return
      end

      vote_rows = GameStorage.db.execute(
        'SELECT recipient_character_id, COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
        [campaign_id, loot_id]
      )

      if vote_rows.empty?
        render json: { error: 'no votes' }, status: :conflict
        return
      end

      max_votes = vote_rows.map { |r| r[1] }.max
      winners = vote_rows.select { |r| r[1] == max_votes }

      if winners.length > 1
        render json: { error: 'tie' }, status: :conflict
        return
      end

      winner_id = winners[0][0]
      winner_votes = winners[0][1]

      item_id = loot[1]
      quantity = loot[2]

      GameStorage.db.execute(
        'INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, winner_id, item_id, quantity]
      )

      GameStorage.db.execute(
        'UPDATE play_campaign_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?',
        ['assigned', winner_id, campaign_id, loot_id]
      )

      render json: {
        loot_id: loot_id,
        recipient_character_id: winner_id,
        item_id: item_id,
        quantity: quantity,
        votes: winner_votes,
        status: 'assigned'
      }, status: :ok
    end
  end

  def get_loot
    campaign_id = params[:id]
    loot_id = params[:loot_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      loot = find_play_loot(campaign_id, loot_id)
      return unless loot

      vote_rows = GameStorage.db.execute(
        'SELECT recipient_character_id, COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
        [campaign_id, loot_id]
      )

      votes = {}
      vote_rows.each { |r| votes[r[0]] = r[1] }

      render json: {
        loot_id: loot[0],
        item_id: loot[1],
        quantity: loot[2],
        status: loot[3],
        recipient_character_id: loot[4],
        votes: votes
      }, status: :ok
    end
  end

  # NPC agendas
  def create_npc
    npc_id = @body['npc_id']
    name = @body['name']
    agenda = @body['agenda']
    public_status = @body['public_status']

    unless valid_non_empty_string?(npc_id)
      bad_request('invalid npc_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless valid_non_empty_string?(agenda)
      bad_request('invalid agenda')
      return
    end

    unless valid_non_empty_string?(public_status)
      bad_request('invalid public_status')
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

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, npc_id, name, agenda, public_status]
        )
        render json: {
          npc_id: npc_id,
          name: name,
          agenda: agenda,
          public_status: public_status
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'npc id taken' }, status: :conflict
      end
    end
  end

  def update_npc_agenda
    agenda = @body['agenda']
    public_status = @body['public_status']

    unless valid_non_empty_string?(agenda)
      bad_request('invalid agenda')
      return
    end

    unless valid_non_empty_string?(public_status)
      bad_request('invalid public_status')
      return
    end

    campaign_id = params[:id]
    npc_id = params[:npc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      npc = find_play_npc(campaign_id, npc_id)
      return unless npc

      GameStorage.db.execute(
        'UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?',
        [agenda, public_status, campaign_id, npc_id]
      )

      render json: {
        npc_id: npc_id,
        name: npc[2],
        agenda: agenda,
        public_status: public_status
      }, status: :ok
    end
  end

  def get_npc
    campaign_id = params[:id]
    npc_id = params[:npc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      npc = find_play_npc(campaign_id, npc_id)
      return unless npc

      response = {
        npc_id: npc[1],
        name: npc[2],
        public_status: npc[4]
      }
      response[:agenda] = npc[3] if campaign[1] == username
      render json: response, status: :ok
    end
  end

  # NPC dialogue
  def create_dialogue
    dialogue_id = @body['dialogue_id']
    speaker = @body['speaker']
    text = @body['text']
    visibility = @body['visibility']

    unless valid_non_empty_string?(dialogue_id)
      bad_request('invalid dialogue_id')
      return
    end

    unless valid_non_empty_string?(speaker)
      bad_request('invalid speaker')
      return
    end

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    unless visibility == 'public' || visibility == 'private'
      bad_request('invalid visibility')
      return
    end

    campaign_id = params[:id]
    npc_id = params[:npc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      npc = find_play_npc(campaign_id, npc_id)
      return unless npc

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)',
          [campaign_id, npc_id, dialogue_id, speaker, text, visibility]
        )
        render json: {
          dialogue_id: dialogue_id,
          speaker: speaker,
          text: text,
          visibility: visibility
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'dialogue id taken' }, status: :conflict
      end
    end
  end

  def list_dialogue
    campaign_id = params[:id]
    npc_id = params[:npc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      npc = find_play_npc(campaign_id, npc_id)
      return unless npc

      is_dm = campaign[1] == username

      rows = if is_dm
               GameStorage.db.execute(
                 'SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY id ASC',
                 [campaign_id, npc_id]
               )
             else
               GameStorage.db.execute(
                 'SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND visibility = ? ORDER BY id ASC',
                 [campaign_id, npc_id, 'public']
               )
             end

      entries = rows.map do |row|
        {
          dialogue_id: row[0],
          speaker: row[1],
          text: row[2],
          visibility: row[3]
        }
      end

      render json: { npc_id: npc_id, entries: entries }, status: :ok
    end
  end

  # Faction reputation
  def create_faction
    campaign_id = params[:id]
    faction_id = @body['faction_id']
    name = @body['name']
    username = @current_user[:username]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(faction_id)
      bad_request('invalid faction_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)',
          [campaign_id, faction_id, name]
        )
        render json: { faction_id: faction_id, name: name }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'faction id taken' }, status: :conflict
      end
    end
  end

  def create_reputation
    campaign_id = params[:id]
    faction_id = params[:faction_id]
    character_id = @body['character_id']
    delta = @body['delta']
    reason = @body['reason']
    username = @current_user[:username]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(faction_id)
      bad_request('invalid faction_id')
      return
    end

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless delta.is_a?(Integer) && delta != 0 && delta.between?(-25, 25)
      bad_request('invalid delta')
      return
    end

    unless valid_non_empty_string?(reason)
      bad_request('invalid reason')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      faction = find_play_faction(campaign_id, faction_id)
      return unless faction

      member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )
      if member.nil?
        render json: { error: 'character not a campaign member' }, status: :bad_request
        return
      end

      current = GameStorage.db.get_first_value(
        'SELECT reputation FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id DESC LIMIT 1',
        [campaign_id, faction_id, character_id]
      ) || 0

      new_reputation = [[current + delta, 100].min, -100].max

      GameStorage.db.execute(
        'INSERT INTO play_campaign_reputation (campaign_id, faction_id, character_id, delta, reputation, reason) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, faction_id, character_id, delta, new_reputation, reason]
      )

      render json: {
        faction_id: faction_id,
        character_id: character_id,
        reputation: new_reputation,
        delta: delta,
        reason: reason
      }, status: :created
    end
  end

  def get_reputation
    campaign_id = params[:id]
    faction_id = params[:faction_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      faction = find_play_faction(campaign_id, faction_id)
      return unless faction

      rows = if campaign[1] == username
               GameStorage.db.execute(
                 'SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? ORDER BY id ASC',
                 [campaign_id, faction_id]
               )
             else
               member = GameStorage.db.get_first_row(
                 'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
                 [campaign_id, username]
               )
               unless member
                 render json: { error: 'forbidden' }, status: :forbidden
                 return
               end
               GameStorage.db.execute(
                 'SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id ASC',
                 [campaign_id, faction_id, member[0]]
               )
             end

      entries = rows.map do |row|
        {
          faction_id: row[0],
          character_id: row[1],
          reputation: row[2],
          delta: row[3],
          reason: row[4]
        }
      end

      render json: { faction_id: faction_id, entries: entries }, status: :ok
    end
  end

  # Relationship graph
  def create_relationship
    source_id = @body['source_id']
    target_id = @body['target_id']
    kind = @body['kind']
    score = @body['score']

    unless source_id.is_a?(String) && target_id.is_a?(String)
      bad_request('invalid source_id or target_id')
      return
    end

    if source_id == target_id
      bad_request('self-edge')
      return
    end

    unless kind.is_a?(String) && !kind.empty?
      bad_request('invalid kind')
      return
    end

    unless score.is_a?(Integer) && score.between?(-100, 100)
      bad_request('invalid score')
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

      unless entity_exists?(campaign_id, source_id)
        render json: { error: 'source not found' }, status: :not_found
        return
      end

      unless entity_exists?(campaign_id, target_id)
        render json: { error: 'target not found' }, status: :not_found
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, source_id, target_id, kind, score]
        )
        render json: {
          source_id: source_id,
          target_id: target_id,
          kind: kind,
          score: score
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'relationship already exists' }, status: :conflict
      end
    end
  end

  def update_relationship
    score = @body['score']

    unless score.is_a?(Integer) && score.between?(-100, 100)
      bad_request('invalid score')
      return
    end

    campaign_id = params[:id]
    source_id = params[:source_id]
    target_id = params[:target_id]
    kind = params[:kind]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_row(
        'SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [campaign_id, source_id, target_id, kind]
      )

      unless existing
        render json: { error: 'relationship not found' }, status: :not_found
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
        [score, campaign_id, source_id, target_id, kind]
      )

      render json: {
        source_id: source_id,
        target_id: target_id,
        kind: kind,
        score: score
      }, status: :ok
    end
  end

  def list_relationships
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
        'SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY id ASC',
        campaign_id
      )

      edges = rows.map do |row|
        {
          source_id: row[0],
          target_id: row[1],
          kind: row[2],
          score: row[3]
        }
      end

      render json: { edges: edges }, status: :ok
    end
  end

  # Secrets and clues
  def create_clue
    clue_id = @body['clue_id']
    text = @body['text']
    audience = @body['audience']
    character_id = @body['character_id']

    unless valid_non_empty_string?(clue_id)
      bad_request('invalid clue_id')
      return
    end

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    unless %w[character party hidden].include?(audience)
      bad_request('invalid audience')
      return
    end

    if audience == 'character'
      unless valid_non_empty_string?(character_id)
        bad_request('invalid character_id')
        return
      end
    else
      unless character_id.nil?
        bad_request('character_id must be omitted')
        return
      end
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

      if audience == 'character'
        member_exists = GameStorage.db.get_first_value(
          'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
          [campaign_id, character_id]
        )
        unless member_exists
          bad_request('character not found')
          return
        end
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, clue_id, text, audience, audience == 'character' ? character_id : nil]
        )

        response = { clue_id: clue_id, text: text, audience: audience }
        response[:character_id] = character_id if audience == 'character'
        render json: response, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'clue id taken' }, status: :conflict
      end
    end
  end

  def list_clues
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      if is_owner
        rows = GameStorage.db.execute(
          'SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY id ASC',
          campaign_id
        )
      else
        member = GameStorage.db.get_first_row(
          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, username]
        )
        my_character_id = member[0]
        rows = GameStorage.db.execute(
          'SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? AND (audience = ? OR (audience = ? AND character_id = ?)) ORDER BY id ASC',
          [campaign_id, 'party', 'character', my_character_id]
        )
      end

      clues = rows.map do |row|
        clue = { clue_id: row[0], text: row[1], audience: row[2] }
        clue[:character_id] = row[3] if row[2] == 'character'
        clue
      end

      render json: { clues: clues }, status: :ok
    end
  end

  # Content tags
  def create_content
    content_id = @body['content_id']
    kind = @body['kind']
    text = @body['text']
    tags = @body['tags']

    unless valid_content_fields?(content_id, kind, text, tags)
      bad_request('invalid content')
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

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, content_id, kind, text, JSON.generate(tags)]
        )
        render json: serialize_content(content_id, kind, text, tags), status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'duplicate content_id' }, status: :conflict
      end
    end
  end

  def update_content_tags
    tags = @body['tags']

    unless tags.is_a?(Array)
      bad_request('invalid tags')
      return
    end

    unless tags.all? { |t| t.is_a?(String) && !t.empty? }
      bad_request('invalid tag')
      return
    end

    unless tags.uniq.length == tags.length
      bad_request('duplicate tags')
      return
    end

    campaign_id = params[:id]
    content_id = params[:content_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      content = find_content(campaign_id, content_id)
      return unless content

      GameStorage.db.execute(
        'UPDATE play_campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?',
        [JSON.generate(tags), campaign_id, content_id]
      )

      render json: serialize_content(content_id, content[3], content[4], tags), status: :ok
    end
  end

  def list_content
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      exclude_tag = params[:exclude_tag]
      if exclude_tag && (!exclude_tag.is_a?(String) || exclude_tag.empty?)
        bad_request('invalid exclude_tag')
        return
      end

      rows = GameStorage.db.execute(
        'SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? ORDER BY id ASC',
        campaign_id
      )

      content = rows.map do |row|
        tags = JSON.parse(row[3])
        {
          content_id: row[0],
          kind: row[1],
          text: row[2],
          tags: tags
        }
      end

      if exclude_tag && !is_owner
        content = content.reject { |c| c[:tags].include?(exclude_tag) }
      end

      render json: { content: content }, status: :ok
    end
  end

  # Privacy controls: notes
  def create_note
    note_id = @body['note_id']
    text = @body['text']
    visibility = @body['visibility']

    unless valid_non_empty_string?(note_id) && valid_note_fields?(text, visibility)
      bad_request('invalid note')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, note_id, text, visibility, username]
        )
        render json: {
          note_id: note_id,
          text: text,
          visibility: visibility,
          owner: username
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'note id taken' }, status: :conflict
      end
    end
  end

  def list_notes
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = if is_owner
               GameStorage.db.execute(
                 'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY id ASC',
                 campaign_id
               )
             else
               GameStorage.db.execute(
                 'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND (visibility = ? OR (visibility = ? AND owner = ?)) ORDER BY id ASC',
                 [campaign_id, 'party', 'private', username]
               )
             end

      notes = rows.map do |row|
        {
          note_id: row[0],
          text: row[1],
          visibility: row[2],
          owner: row[3]
        }
      end

      render json: { notes: notes }, status: :ok
    end
  end

  def show_note
    campaign_id = params[:id]
    note_id = params[:note_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      note = find_note(campaign_id, note_id)
      return unless note

      if note[2] == 'private' && !is_owner && note[3] != username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      render json: {
        note_id: note[0],
        text: note[1],
        visibility: note[2],
        owner: note[3]
      }, status: :ok
    end
  end

  def update_note
    text = @body['text']
    visibility = @body['visibility']

    unless valid_note_fields?(text, visibility)
      bad_request('invalid note')
      return
    end

    campaign_id = params[:id]
    note_id = params[:note_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      note = find_note(campaign_id, note_id)
      return unless note

      unless note[3] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?',
        [text, visibility, campaign_id, note_id]
      )

      render json: {
        note_id: note[0],
        text: text,
        visibility: visibility,
        owner: note[3]
      }, status: :ok
    end
  end

  # Privacy controls: whispers
  def create_whisper
    whisper_id = @body['whisper_id']
    to_character_id = @body['to_character_id']
    text = @body['text']

    unless valid_non_empty_string?(whisper_id) &&
           valid_non_empty_string?(to_character_id) &&
           valid_non_empty_string?(text)
      bad_request('invalid whisper')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      if username == campaign[1]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      sender = GameStorage.db.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ? AND owner = ?',
        [campaign_id, username, username]
      )

      unless sender
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      from_character_id = sender[0]

      recipient_exists = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )

      unless recipient_exists
        bad_request('recipient not found')
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, whisper_id, from_character_id, to_character_id, text]
        )
        render json: {
          whisper_id: whisper_id,
          from_character_id: from_character_id,
          to_character_id: to_character_id,
          text: text
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'whisper id taken' }, status: :conflict
      end
    end
  end

  def list_whispers
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = if is_owner
               GameStorage.db.execute(
                 'SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY id ASC',
                 campaign_id
               )
             else
               my_character_id = GameStorage.db.get_first_value(
                 'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ? AND owner = ?',
                 [campaign_id, username, username]
               )
               if my_character_id
                 GameStorage.db.execute(
                   'SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? AND (from_character_id = ? OR to_character_id = ?) ORDER BY id ASC',
                   [campaign_id, my_character_id, my_character_id]
                 )
               else
                 []
               end
             end

      whispers = rows.map do |row|
        {
          whisper_id: row[0],
          from_character_id: row[1],
          to_character_id: row[2],
          text: row[3]
        }
      end

      render json: { whispers: whispers }, status: :ok
    end
  end

  # Privacy controls: character sheet
  def character_sheet
    campaign_id = params[:id]
    character_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id, owner, name, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, character_id]
      )

      unless member
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      is_character_owner = member[1] == username

      unless is_owner || is_character_owner
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      # The basic sheet is deterministic and independent of dynamic
      # progression, equipment, or hit-point adjustments.
      render json: {
        character_id: member[0],
        owner: member[1],
        name: member[2],
        class: member[3],
        level: 1,
        proficiency_bonus: 2,
        hp_max: 10,
        armor_class: 10
      }, status: :ok
    end
  end

  # Campaign invitations
  def create_invitation
    invitation_id = @body['invitation_id']
    username = @body['username']
    character_id = @body['character_id']

    unless valid_non_empty_string?(invitation_id)
      bad_request('invalid invitation_id')
      return
    end

    unless valid_non_empty_string?(username)
      bad_request('invalid username')
      return
    end

    unless valid_non_empty_string?(character_id)
      bad_request('invalid character_id')
      return
    end

    campaign_id = params[:id]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == current_username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      target = GameStorage.db.get_first_row(
        'SELECT username, role FROM users WHERE username = ?',
        username
      )

      unless target && target[1] == 'player'
        bad_request('target is not a registered player')
        return
      end

      existing_id = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?',
        [campaign_id, invitation_id]
      )

      if existing_id
        render json: { error: 'duplicate invitation id' }, status: :conflict
        return
      end

      existing_pending = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = ?',
        [campaign_id, username, 'pending']
      )

      if existing_pending
        render json: { error: 'pending invitation already exists for user' }, status: :conflict
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)',
          [campaign_id, invitation_id, username, character_id, 'pending']
        )

        render json: {
          invitation_id: invitation_id,
          username: username,
          character_id: character_id,
          status: 'pending'
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'duplicate invitation id' }, status: :conflict
      end
    end
  end

  def accept_invitation
    campaign_id = params[:id]
    invitation_id = params[:invitation_id]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      invitation = GameStorage.db.get_first_row(
        'SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?',
        [campaign_id, invitation_id]
      )

      unless invitation
        render json: { error: 'invitation not found' }, status: :not_found
        return
      end

      unless invitation[1] == current_username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless invitation[3] == 'pending'
        render json: { error: 'invitation already accepted' }, status: :conflict
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, current_username, invitation[2], invitation[2], 'fighter', current_username, 10]
        )
      rescue SQLite3::ConstraintException
        render json: { error: 'already a member' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ?',
        ['accepted', campaign_id, invitation_id]
      )

      render json: {
        invitation_id: invitation_id,
        username: current_username,
        character_id: invitation[2],
        status: 'accepted'
      }, status: :ok
    end
  end

  def list_invitations
    campaign_id = params[:id]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == current_username

      if is_owner
        rows = GameStorage.db.execute(
          'SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY id ASC',
          campaign_id
        )
      else
        is_target = GameStorage.db.get_first_value(
          'SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ?',
          [campaign_id, current_username]
        )

        if is_target
          rows = GameStorage.db.execute(
            'SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY id ASC',
            [campaign_id, current_username]
          )
        else
          is_member = GameStorage.db.get_first_value(
            'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
            [campaign_id, current_username]
          )

          unless is_member
            render json: { error: 'forbidden' }, status: :forbidden
            return
          end

          rows = []
        end
      end

      invitations = rows.map do |row|
        {
          invitation_id: row[0],
          username: row[1],
          character_id: row[2],
          status: row[3]
        }
      end

      render json: { invitations: invitations }, status: :ok
    end
  end

  # GM delegation
  def grant_delegation
    target_username = @body['username']
    powers = @body['powers']

    unless valid_non_empty_string?(target_username)
      bad_request('invalid username')
      return
    end

    unless valid_delegation_powers?(powers)
      bad_request('invalid powers')
      return
    end

    campaign_id = params[:id]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == current_username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, target_username]
      )

      unless is_member
        bad_request('target is not a member')
        return
      end

      existing = GameStorage.db.get_first_row(
        'SELECT username, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?',
        [campaign_id, target_username]
      )

      if existing && existing[1] == 1
        render json: { error: 'duplicate active delegation' }, status: :conflict
        return
      end

      powers_json = JSON.generate(powers)

      if existing
        GameStorage.db.execute(
          'UPDATE play_campaign_delegations SET powers_json = ?, active = 1 WHERE campaign_id = ? AND username = ?',
          [powers_json, campaign_id, target_username]
        )
      else
        GameStorage.db.execute(
          'INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)',
          [campaign_id, target_username, powers_json]
        )
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)',
        [campaign_id, target_username, 'granted', powers_json]
      )

      render json: {
        username: target_username,
        powers: powers,
        active: true
      }, status: :created
    end
  end

  def revoke_delegation
    campaign_id = params[:id]
    target_username = params[:username]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == current_username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_row(
        'SELECT username, powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?',
        [campaign_id, target_username]
      )

      unless existing
        render json: { error: 'delegation not found' }, status: :not_found
        return
      end

      powers = JSON.parse(existing[1])

      if existing[2] == 1
        GameStorage.db.execute(
          'UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?',
          [campaign_id, target_username]
        )

        GameStorage.db.execute(
          'INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)',
          [campaign_id, target_username, 'revoked', existing[1]]
        )
      end

      render json: {
        username: target_username,
        powers: powers,
        active: false
      }, status: :ok
    end
  end

  def delegation_audit
    campaign_id = params[:id]
    current_username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == current_username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY id ASC',
        campaign_id
      )

      entries = rows.map do |row|
        {
          username: row[0],
          action: row[1],
          powers: JSON.parse(row[2])
        }
      end

      render json: { entries: entries }, status: :ok
    end
  end

  # Transactional transfers
  def create_transactional_transfer
    from_character_id = @body['from_character_id']
    to_character_id = @body['to_character_id']
    amount = @body['amount']
    simulate_failure = @body['simulate_failure']

    unless valid_id?(from_character_id)
      bad_request('invalid from_character_id')
      return
    end

    unless valid_id?(to_character_id)
      bad_request('invalid to_character_id')
      return
    end

    if from_character_id == to_character_id
      bad_request('same character')
      return
    end

    unless amount.is_a?(Integer) && amount.positive?
      bad_request('invalid amount')
      return
    end

    unless simulate_failure == true || simulate_failure == false
      bad_request('invalid simulate_failure')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      from_member = GameStorage.db.get_first_row(
        'SELECT username, character_id, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, from_character_id]
      )

      unless from_member
        bad_request('invalid from_character_id')
        return
      end

      unless from_member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      to_member = GameStorage.db.get_first_row(
        'SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
        [campaign_id, to_character_id]
      )

      unless to_member
        bad_request('invalid to_character_id')
        return
      end

      from_gold = from_member[3] || 10
      if from_gold < amount
        render json: { error: 'insufficient balance' }, status: :conflict
        return
      end

      if simulate_failure
        render json: { error: 'simulated failure' }, status: :internal_server_error
        return
      end

      to_gold = to_member[1] || 10
      new_from_gold = from_gold - amount
      new_to_gold = to_gold + amount

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.transaction(:immediate) do |db|
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_from_gold, campaign_id, from_character_id]
        )
        db.execute(
          'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
          [new_to_gold, campaign_id, to_character_id]
        )
        db.execute(
          'INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [campaign_id, next_sequence, from_character_id, to_character_id, amount, new_from_gold, new_to_gold]
        )
      end

      render json: {
        from_character_id: from_character_id,
        to_character_id: to_character_id,
        amount: amount,
        from_gold: new_from_gold,
        to_gold: new_to_gold,
        sequence: next_sequence
      }, status: :created
    end
  end

  def transactional_transfers
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
        'SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      transfers = rows.map do |row|
        {
          from_character_id: row[0],
          to_character_id: row[1],
          amount: row[2],
          from_gold: row[3],
          to_gold: row[4],
          sequence: row[5]
        }
      end

      render json: { transfers: transfers }, status: :ok
    end
  end

  # Deterministic replay stream for campaign members. Append-only ordered
  # text events build a public replay state that can be read back exactly.
  def append_replay_event
    event_id = @body['event_id']
    kind = @body['kind']
    text = @body['text']

    unless event_id.is_a?(String) && !event_id.empty?
      bad_request('invalid event_id')
      return
    end

    unless text.is_a?(String) && !text.empty?
      bad_request('invalid text')
      return
    end

    unless kind == 'append'
      bad_request('invalid kind')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )

      if existing
        render json: { error: 'duplicate event_id' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, event_id, kind, text]
      )

      render json: {
        event_id: event_id,
        kind: kind,
        text: text,
        sequence: next_sequence
      }, status: :created
    end
  end

  def replay
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      render json: build_replay_state(campaign_id), status: :ok
    end
  end

  def replay_check
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      render json: build_replay_state(campaign_id), status: :ok
    end
  end

  # Versioned campaign exports (DM-only). Snapshots the current public story
  # and campaign status into an immutable, sequential version.
  def create_export
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      status_row = GameStorage.db.get_first_row(
        'SELECT status FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      status = status_row ? status_row[0] : ''

      doc_row = GameStorage.db.get_first_row(
        'SELECT story FROM play_campaign_documents WHERE campaign_id = ?',
        campaign_id
      )
      story = doc_row ? doc_row[0] : ''

      next_version = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_exports WHERE campaign_id = ?',
        campaign_id
      ).to_i + 1

      GameStorage.db.execute(
        'INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)',
        [campaign_id, next_version, story, status]
      )

      render json: { version: next_version, story: story, status: status }, status: :created
    end
  end

  def list_exports
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC',
        campaign_id
      )

      exports = rows.map do |row|
        { version: row[0], story: row[1], status: row[2] }
      end

      render json: { exports: exports }, status: :ok
    end
  end

  def read_export
    campaign_id = params[:id]
    version_param = params[:version]

    begin
      version = Integer(version_param)
    rescue ArgumentError, TypeError
      render json: { error: 'export not found' }, status: :not_found
      return
    end

    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?',
        [campaign_id, version]
      )

      unless row
        render json: { error: 'export not found' }, status: :not_found
        return
      end

      render json: { version: row[0], story: row[1], status: row[2] }, status: :ok
    end
  end

  # DM-only campaign imports. Accepts only compatible version 1 snapshots and
  # applies the imported story and status atomically.
  def create_import
    campaign_id = params[:id]
    username = @current_user[:username]
    body = @body

    unless body.is_a?(Hash) &&
           body['version'].is_a?(Integer) && body['version'] == 1 &&
           valid_non_empty_string?(body['story']) &&
           body['status'].is_a?(String) && %w[lobby started].include?(body['status'])
      bad_request('invalid import')
      return
    end

    story = body['story']
    status = body['status']

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      GameStorage.db.transaction(:immediate) do |db|
        db.execute(
          'UPDATE play_campaigns SET status = ? WHERE id = ?',
          [status, campaign_id]
        )
        db.execute(
          'INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ' \
          'ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story',
          [campaign_id, story, '']
        )
        db.execute(
          'INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ' \
          'ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status',
          [campaign_id, 1, story, status]
        )
      end

      render json: { version: 1, story: story, status: status }, status: :ok
    end
  end

  def import_state
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?',
        campaign_id
      )

      unless row
        render json: { error: 'import not found' }, status: :not_found
        return
      end

      render json: { version: row[0], story: row[1], status: row[2] }, status: :ok
    end
  end

  # Owner-only campaign backups that snapshot the current public story and
  # status. Backups are immutable and restore without mutating the snapshot.
  def create_backup
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      status_row = GameStorage.db.get_first_row(
        'SELECT status FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      status = status_row ? status_row[0] : ''

      doc_row = GameStorage.db.get_first_row(
        'SELECT story FROM play_campaign_documents WHERE campaign_id = ?',
        campaign_id
      )
      story = doc_row ? doc_row[0] : ''

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?',
        campaign_id
      )
      backup_id = "backup-#{next_sequence}"

      GameStorage.db.execute(
        'INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status, sequence) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, backup_id, story, status, next_sequence]
      )

      render json: { backup_id: backup_id, story: story, status: status }, status: :created
    end
  end

  def list_backups
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      backups = rows.map do |row|
        { backup_id: row[0], story: row[1], status: row[2] }
      end

      render json: { backups: backups }, status: :ok
    end
  end

  def restore_backup
    backup_id = params[:backup_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      backup = GameStorage.db.get_first_row(
        'SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?',
        [campaign_id, backup_id]
      )

      unless backup
        render json: { error: 'backup not found' }, status: :not_found
        return
      end

      story = backup[1]
      status = backup[2]

      GameStorage.db.execute(
        'UPDATE play_campaigns SET status = ? WHERE id = ?',
        [status, campaign_id]
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ' \
        'ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story',
        [campaign_id, story, '']
      )

      render json: { backup_id: backup_id, story: story, status: status }, status: :ok
    end
  end

  def create_migration
    campaign_id = params[:id]
    username = @current_user[:username]
    body = @body

    unless body.is_a?(Hash) &&
           body['schema_version'].is_a?(Integer) && body['schema_version'] == 1 &&
           valid_non_empty_string?(body['story'])
      bad_request('invalid migration')
      return
    end

    story = body['story']

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      campaign_name = GameStorage.db.get_first_value(
        'SELECT name FROM play_campaigns WHERE id = ?',
        campaign_id
      )

      existing = GameStorage.db.get_first_row(
        'SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?',
        campaign_id
      )

      if existing && existing[1] == story
        render json: { schema_version: 2, story: story, campaign_name: campaign_name }, status: :ok
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) ' \
        'ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name',
        [campaign_id, 2, story, campaign_name]
      )

      render json: { schema_version: 2, story: story, campaign_name: campaign_name }, status: :created
    end
  end

  def migration_state
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?',
        campaign_id
      )

      unless row
        render json: { error: 'migration not found' }, status: :not_found
        return
      end

      render json: { schema_version: row[0], story: row[1], campaign_name: row[2] }, status: :ok
    end
  end

  # Deterministic RNG ledger
  def rng_seed
    seed = @body['seed']

    unless valid_non_empty_string?(seed)
      bad_request('invalid seed')
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

      existing = GameStorage.db.get_first_row(
        'SELECT seed FROM play_campaign_rng_state WHERE campaign_id = ?',
        campaign_id
      )

      if existing && existing[0]
        render json: { error: 'seed already configured' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_rng_state (campaign_id, seed, next_sequence) VALUES (?, ?, 1) ' \
        'ON CONFLICT(campaign_id) DO UPDATE SET seed = excluded.seed, next_sequence = 1',
        [campaign_id, seed]
      )

      render json: { seed: seed, rolls: [] }, status: :ok
    end
  end

  def rng_roll
    roll_id = @body['roll_id']
    sides = @body['sides']

    unless valid_non_empty_string?(roll_id)
      bad_request('invalid roll_id')
      return
    end

    unless sides.is_a?(Integer) && sides >= 2 && sides <= 100
      bad_request('invalid sides')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      state = GameStorage.db.get_first_row(
        'SELECT seed, next_sequence FROM play_campaign_rng_state WHERE campaign_id = ?',
        campaign_id
      )

      unless state && state[0]
        render json: { error: 'seed not configured' }, status: :conflict
        return
      end

      seed = state[0]
      sequence = state[1] || 1

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?',
        [campaign_id, roll_id]
      )

      if duplicate
        render json: { error: 'duplicate roll_id' }, status: :conflict
        return
      end

      result = compute_roll(seed, sequence, roll_id, sides)

      GameStorage.db.execute(
        'INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, sequence, roll_id, sides, result]
      )

      GameStorage.db.execute(
        'UPDATE play_campaign_rng_state SET next_sequence = ? WHERE campaign_id = ?',
        [sequence + 1, campaign_id]
      )

      render json: {
        roll_id: roll_id,
        sides: sides,
        result: result,
        sequence: sequence
      }, status: :created
    end
  end

  def rng_ledger
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      state = GameStorage.db.get_first_row(
        'SELECT seed FROM play_campaign_rng_state WHERE campaign_id = ?',
        campaign_id
      )
      seed = state ? state[0] : nil

      rows = GameStorage.db.execute(
        'SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      rolls = rows.map do |row|
        {
          roll_id: row[0],
          sides: row[1],
          result: row[2],
          sequence: row[3]
        }
      end

      render json: { seed: seed, rolls: rolls }, status: :ok
    end
  end

  # Moderation reports
  def create_moderation_report
    report_id = @body['report_id']
    target_id = @body['target_id']
    reason = @body['reason']

    unless valid_non_empty_string?(report_id) && valid_non_empty_string?(target_id) && valid_non_empty_string?(reason)
      bad_request('invalid report fields')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )
      if existing
        render json: { error: 'report id taken' }, status: :conflict
        return
      end

      sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, report_id, target_id, reason, 'open', username, sequence]
      )

      render json: {
        report_id: report_id,
        target_id: target_id,
        reason: reason,
        status: 'open',
        reporter: username,
        sequence: sequence
      }, status: :created
    end
  end

  def list_moderation_reports
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
        'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      reports = rows.map do |row|
        report = {
          report_id: row[0],
          target_id: row[1],
          reason: row[2],
          status: row[3],
          reporter: row[4],
          sequence: row[5]
        }
        if row[3] == 'resolved'
          report[:action] = row[6]
          report[:note] = row[7]
          report[:resolver] = row[8]
        end
        report
      end

      render json: { reports: reports }, status: :ok
    end
  end

  def resolve_moderation_report
    report_id = params[:report_id]
    action = @body['action']
    note = @body['note']

    unless valid_non_empty_string?(report_id)
      bad_request('invalid report_id')
      return
    end

    unless %w[allow remove].include?(action)
      bad_request('invalid action')
      return
    end

    unless valid_non_empty_string?(note)
      bad_request('invalid note')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
        [campaign_id, report_id]
      )

      unless row
        render json: { error: 'report not found' }, status: :not_found
        return
      end

      if row[3] == 'resolved'
        render json: { error: 'report already resolved' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?',
        ['resolved', action, note, username, campaign_id, report_id]
      )

      render json: {
        report_id: row[0],
        target_id: row[1],
        reason: row[2],
        status: 'resolved',
        reporter: row[4],
        sequence: row[5],
        action: action,
        note: note,
        resolver: username
      }, status: :ok
    end
  end

  # Safety boundaries
  def replace_safety_boundaries
    campaign_id = params[:id]
    username = @current_user[:username]

    blocked_tags = @body['blocked_tags']
    unless blocked_tags.is_a?(Array) && !blocked_tags.empty?
      bad_request('invalid blocked_tags')
      return
    end

    seen = Set.new
    blocked_tags.each do |tag|
      unless tag.is_a?(String) && !tag.empty?
        bad_request('invalid blocked_tags')
        return
      end
      if seen.include?(tag)
        bad_request('invalid blocked_tags')
        return
      end
      seen.add(tag)
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      sorted_tags = blocked_tags.sort
      tags_json = JSON.generate(sorted_tags)

      GameStorage.db.execute(
        'INSERT OR REPLACE INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) VALUES (?, ?)',
        [campaign_id, tags_json]
      )

      render json: { blocked_tags: sorted_tags }, status: :ok
    end
  end

  def read_safety_boundaries
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      tags_json = GameStorage.db.get_first_value(
        'SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?',
        campaign_id
      ) || '[]'

      render json: { blocked_tags: JSON.parse(tags_json) }, status: :ok
    end
  end

  def submit_safety_check
    campaign_id = params[:id]
    username = @current_user[:username]

    event_id = @body['event_id']
    kind = @body['kind']
    text = @body['text']
    tags = @body['tags']

    unless valid_non_empty_string?(event_id)
      bad_request('invalid event_id')
      return
    end

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    unless %w[narration chat].include?(kind)
      bad_request('invalid kind')
      return
    end

    unless tags.is_a?(Array) && !tags.empty?
      bad_request('invalid tags')
      return
    end

    seen = Set.new
    tags.each do |tag|
      unless tag.is_a?(String) && !tag.empty?
        bad_request('invalid tags')
        return
      end
      if seen.include?(tag)
        bad_request('invalid tags')
        return
      end
      seen.add(tag)
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      if existing
        render json: { error: 'event_id already accepted' }, status: :conflict
        return
      end

      blocked_tags_json = GameStorage.db.get_first_value(
        'SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?',
        campaign_id
      ) || '[]'
      blocked_tags = JSON.parse(blocked_tags_json)

      if tags.any? { |t| blocked_tags.include?(t) }
        render json: { error: 'blocked tag' }, status: :conflict
        return
      end

      sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, event_id, kind, text, JSON.generate(tags), sequence]
      )

      render json: {
        event_id: event_id,
        kind: kind,
        text: text,
        tags: tags,
        sequence: sequence
      }, status: :created
    end
  end

  def read_safety_events
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
        'SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      events = rows.map do |row|
        {
          event_id: row[0],
          kind: row[1],
          text: row[2],
          tags: JSON.parse(row[3]),
          sequence: row[4]
        }
      end

      render json: { events: events }, status: :ok
    end
  end

  # Fixture seeding
  def seed_fixture
    fixture_id = @body['fixture_id']
    unless fixture_id.is_a?(String) && fixture_id == 'canonical-v1'
      bad_request('invalid fixture_id')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?',
        campaign_id
      )

      if existing
        render json: CANONICAL_FIXTURE, status: :ok
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id, status) VALUES (?, ?, ?)',
        [campaign_id, fixture_id, 'seeded']
      )

      render json: CANONICAL_FIXTURE, status: :created
    end
  end

  def read_fixture_state
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?',
        campaign_id
      )

      unless existing
        render json: { error: 'fixture not found' }, status: :not_found
        return
      end

      render json: CANONICAL_FIXTURE, status: :ok
    end
  end

  private

  # Return all party usernames in insertion order. The queue is built from this
  # order, so every call site must use the same `ORDER BY ROWID` clause.
  def party_usernames(campaign_id)
    GameStorage.db.execute(
      'SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY ROWID',
      campaign_id
    ).map(&:first)
  end

  # Return all play events for a campaign in sequence order, serialized for
  # the public API. Player-facing endpoints omit DM-only fields at the action
  # level by not including them in the SELECT. Internal bookkeeping events
  # (start, nudge) and private chat messages are kept in the event log but
  # hidden from player contexts to preserve the earlier stage behavior of
  # recent_events.
  def recent_events(campaign_id)
    GameStorage.db.execute(
      'SELECT sequence, kind, actor, text, type, next_actor, destination_id, travel_turns, hp_current, hp_max, target FROM play_campaign_events WHERE campaign_id = ? AND kind NOT IN (?, ?, ?) ORDER BY sequence ASC',
      [campaign_id, 'start', 'nudge', 'chat']
    ).map { |row| serialize_event(row) }
  end

  def serialize_event(row)
    event = {
      sequence: row[0],
      kind: row[1],
      actor: row[2]
    }
    case row[1]
    when 'travel'
      event[:destination_id] = row[6] if row[6]
      event[:travel_turns] = row[7] if row[7]
    when 'rest'
      event[:type] = row[4] if row[4]
      event[:hp_current] = row[8] if row[8]
      event[:hp_max] = row[9] if row[9]
    else
      event[:text] = row[3]
    end
    event[:type] = row[4] if row[4] && row[1] != 'rest'
    event[:target] = row[10] if row[10] && row[1] == 'combat_action'
    event[:next_actor] = row[5] if row[5]
    event
  end

  def build_replay_state(campaign_id)
    rows = GameStorage.db.execute(
      'SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC',
      campaign_id
    )

    event_ids = rows.map(&:first)
    story = rows.map { |row| row[1] }.join
    digest = event_ids.join(',') + '|' + story

    {
      story: story,
      event_ids: event_ids,
      digest: digest
    }
  end

  # Deterministic roll algorithm: seed + "|" + sequence + "|" + roll_id + "|" + sides,
  # hashed with an unsigned 32-bit polynomial accumulator, then (acc % sides) + 1.
  def compute_roll(seed, sequence, roll_id, sides)
    acc = 0
    "#{seed}|#{sequence}|#{roll_id}|#{sides}".bytes.each do |b|
      acc = (acc * 31 + b) % 2**32
    end
    (acc % sides) + 1
  end

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

  def find_play_member(campaign_id, character_id)
    row = GameStorage.db.get_first_row(
      'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign_id, character_id]
    )
    if row.nil?
      render json: { error: 'character not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_loot(campaign_id, loot_id)
    row = GameStorage.db.get_first_row(
      'SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?',
      [campaign_id, loot_id]
    )
    if row.nil?
      render json: { error: 'loot not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_npc(campaign_id, npc_id)
    row = GameStorage.db.get_first_row(
      'SELECT campaign_id, npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
      [campaign_id, npc_id]
    )
    if row.nil?
      render json: { error: 'npc not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_faction(campaign_id, faction_id)
    row = GameStorage.db.get_first_row(
      'SELECT campaign_id, faction_id, name FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?',
      [campaign_id, faction_id]
    )
    if row.nil?
      render json: { error: 'faction not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_content(campaign_id, content_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, campaign_id, content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?',
      [campaign_id, content_id]
    )
    if row.nil?
      render json: { error: 'content not found' }, status: :not_found
      return nil
    end
    row
  end

  def serialize_content(content_id, kind, text, tags)
    {
      content_id: content_id,
      kind: kind,
      text: text,
      tags: tags
    }
  end

  def valid_content_fields?(content_id, kind, text, tags)
    content_id.is_a?(String) && !content_id.empty? &&
      kind.is_a?(String) && !kind.empty? &&
      text.is_a?(String) && !text.empty? &&
      tags.is_a?(Array) && !tags.empty? &&
      tags.all? { |t| t.is_a?(String) && !t.empty? } &&
      tags.uniq.length == tags.length
  end

  # True when +entity_id+ is a campaign member character or an NPC in the campaign.
  def entity_exists?(campaign_id, entity_id)
    member = GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign_id, entity_id]
    )
    return true if member

    npc = GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?',
      [campaign_id, entity_id]
    )
    !npc.nil?
  end

  def find_scene(campaign_id, scene_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?',
      [campaign_id, scene_id]
    )
    if row.nil?
      render json: { error: 'scene not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_encounter(campaign_id, encounter_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, name, status, combatants_json, round, turn_index, conditions_json, order_json, xp_awarded, loot_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?',
      [campaign_id, encounter_id]
    )
    if row.nil?
      render json: { error: 'encounter not found' }, status: :not_found
      return nil
    end
    row
  end

  # True if +username+ is the campaign owner or a member of the party.
  def campaign_member?(campaign_id, username, owner)
    return true if owner == username

    GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    )
  end

  def can_narrate?(campaign_id, username, owner)
    return true if owner == username

    active_delegation?(campaign_id, username, 'narrate')
  end

  def active_delegation?(campaign_id, username, power)
    row = GameStorage.db.get_first_row(
      'SELECT powers_json FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1',
      [campaign_id, username]
    )
    return false unless row

    powers = JSON.parse(row[0])
    powers.include?(power)
  rescue JSON::ParserError
    false
  end

  def valid_delegation_powers?(powers)
    powers.is_a?(Array) && !powers.empty? &&
      powers.all? { |p| p == 'narrate' } &&
      powers.uniq.length == powers.length
  end

  # Return the current round, turn_index, and active combatant for an encounter
  # row. The turn_index is clamped to the valid range. If the encounter has an
  # explicit order_json, that order is authoritative; otherwise the order is the
  # deterministic initiative sort (descending initiative, then insertion order).
  def current_encounter_state(encounter)
    combatants = JSON.parse(encounter[3] || '[]')
    ordered = encounter_turn_order(combatants, encounter[7])
    round = encounter[4] || 1
    turn_index = clamp_turn_index(encounter[5] || 0, ordered.length)
    active = ordered[turn_index]
    [round, turn_index, active]
  end

  # Sort combatants deterministically by initiative descending, breaking ties
  # by original array order so the result is stable across requests. If an
  # explicit +order_json+ is provided, it is used as the authoritative order
  # and any combatants not listed are appended at the end.
  def encounter_turn_order(combatants, order_json = nil)
    if order_json && !order_json.empty? && order_json != '[]'
      keys = JSON.parse(order_json)
      ordered = []
      keys.each do |key|
        combatant = combatants.find { |c| combatant_key(c) == key }
        ordered << combatant if combatant
      end
      ordered_keys = keys.to_set
      combatants.each do |c|
        ordered << c unless ordered_keys.include?(combatant_key(c))
      end
      ordered
    else
      combatants.each_with_index.sort_by { |c, i| [-c['initiative'].to_i, i] }.map(&:first)
    end
  end

  # Serialize a single combatant for the turn endpoint. Monsters have no
  # +member+ key; bound party members do.
  def serialize_active_combatant(combatant)
    {
      name: combatant['name'],
      kind: combatant['member'].is_a?(String) ? 'player' : 'monster',
      initiative: combatant['initiative']
    }
  end

  # Clamp a turn index to a valid position in a list of +count+ combatants.
  def clamp_turn_index(turn_index, count)
    return 0 if count <= 0
    [[turn_index, 0].max, count - 1].min
  end

  # Parse an optional index value from the request body. Returns nil if the
  # value is absent, the integer if it is already an integer, or the parsed
  # integer if it is a string. Returns :invalid for any other value so callers
  # can surface a 400 response.
  def parse_optional_index(value)
    return nil if value.nil?
    return value if value.is_a?(Integer)
    return value.to_i if value.is_a?(String) && value.match?(/\A-?\d+\z/)
    :invalid
  end

  # Return the unique key used to identify a combatant for conditions. Bound
  # party members are keyed by username; monsters are keyed by monster_id.
  def combatant_key(combatant)
    combatant['member'].is_a?(String) ? combatant['member'] : combatant['monster_id']
  end

  # Return true if a combatant with the given key exists in the encounter.
  def combatant_exists?(combatants, target)
    combatants.any? { |c| combatant_key(c) == target }
  end

  # Apply damage or healing to a named encounter combatant. Monsters store
  # their HP in the encounter's combatants_json; bound party members use the
  # persistent play_campaign_members HP columns so HP follows the character
  # across encounters.
  def apply_hp_change(target, amount, kind)
    campaign_id = params[:id]
    encounter_id = params[:enc_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      encounter = find_encounter(campaign_id, encounter_id)
      return unless encounter

      combatants = JSON.parse(encounter[3] || '[]')
      monster_index = combatants.index { |c| c['monster_id'] == target }

      if monster_index
        combatant = combatants[monster_index]
        hp_max = combatant['hp_max'] || 0
        hp_current = combatant['hp_current'] || hp_max
        new_hp = kind == 'damage' ? [hp_current - amount, 0].max : [hp_current + amount, hp_max].min
        combatant['hp_current'] = new_hp
        GameStorage.db.execute(
          'UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
          [JSON.generate(combatants), campaign_id, encounter_id]
        )
        key = kind == 'damage' ? :damage : :healing
        return render json: { target: target, hp_before: hp_current, hp_after: new_hp, key => amount }, status: :ok
      end

      member_index = combatants.index { |c| c['member'] == target }
      if member_index
        member = GameStorage.db.get_first_row(
          'SELECT username, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, target]
        )
        unless member
          render json: { error: 'target not found' }, status: :not_found
          return
        end
        hp_current = member[1] || 20
        hp_max = member[2] || 20
        status = member[3] || 'conscious'
        successes = member[4] || 0
        failures = member[5] || 0

        new_hp = if kind == 'damage'
                   [hp_current - amount, 0].max
                 else
                   [hp_current + amount, hp_max].min
                 end

        new_status = status
        new_successes = successes
        new_failures = failures

        if kind == 'damage' && new_hp == 0 && status != 'dead'
          new_status = 'unconscious'
          new_successes = 0
          new_failures = 0
        elsif kind == 'heal' && hp_current == 0 && new_hp > 0
          new_status = 'conscious'
          new_successes = 0
          new_failures = 0
        end

        GameStorage.db.execute(
          'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
          [new_hp, new_status, new_successes, new_failures, campaign_id, target]
        )
        key = kind == 'damage' ? :damage : :healing
        return render json: { target: target, hp_before: hp_current, hp_after: new_hp, key => amount }, status: :ok
      end

      render json: { error: 'target not found' }, status: :not_found
    end
  end

  def average_die(sides)
    ((sides + 1) / 2.0).ceil
  end

  def full_spell_slots(class_name, level)
    return {} unless spellcasting_class?(class_name)
    {
      1 => { 1 => 1 },
      2 => { 1 => 2 },
      3 => { 1 => 2, 2 => 1 },
      4 => { 1 => 3, 2 => 2 },
      5 => { 1 => 4, 2 => 3, 3 => 2 },
      6 => { 1 => 4, 2 => 3, 3 => 3 },
      7 => { 1 => 4, 2 => 3, 3 => 3, 4 => 1 },
      8 => { 1 => 4, 2 => 3, 3 => 3, 4 => 2 },
      9 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 1 },
      10 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2 },
      11 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1 },
      12 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1 },
      13 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1 },
      14 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1 },
      15 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1 },
      16 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1 },
      17 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1, 9 => 1 },
      18 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 1, 7 => 1, 8 => 1, 9 => 1 },
      19 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 1, 8 => 1, 9 => 1 },
      20 => { 1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 2, 8 => 1, 9 => 1 }
    }[level] || {}
  end

  def spell_valid_for_class?(spell_id, class_name)
    return false if class_name == 'rogue'
    return false unless class_name == 'wizard'
    WIZARD_SPELLS.include?(spell_id)
  end

  def spellcasting_class?(class_name)
    class_name == 'wizard'
  end

  def parse_concentration(json)
    return nil if json.nil? || json.empty?
    JSON.parse(json)
  rescue JSON::ParserError
    nil
  end

  # Privacy helpers
  def find_note(campaign_id, note_id)
    row = GameStorage.db.get_first_row(
      'SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?',
      [campaign_id, note_id]
    )
    if row.nil?
      render json: { error: 'note not found' }, status: :not_found
      return nil
    end
    row
  end

  def valid_note_fields?(text, visibility)
    valid_non_empty_string?(text) && %w[private party].include?(visibility)
  end

  def require_player
    return if performed?

    unless @current_user && @current_user[:role] == 'player'
      render json: { error: 'forbidden' }, status: :forbidden
    end
  end
end
