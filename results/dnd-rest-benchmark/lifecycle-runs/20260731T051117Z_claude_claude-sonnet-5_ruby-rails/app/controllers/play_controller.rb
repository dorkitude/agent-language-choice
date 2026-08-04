# Protected campaign-play surface under /v1/play. Requests must carry
# `Authorization: Bearer session-<username>`; backed by PLAY_CAMPAIGNS.
#
# Every action follows the same shape: authenticate, load the campaign
# (404 if missing), check authorization (403), validate params in order
# (400 on first failure), then apply the state change and persist. The
# `require_*!`/`load_campaign_or_404` helpers below factor out that shape;
# each renders the appropriate error and returns falsy on failure so
# callers can `return unless ...`.
class PlayController < ApplicationController
  TURN_DEADLINE_OFFSET = 3
  INVENTORY_ITEM_IDS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze
  EQUIPMENT_SLOTS = %w[armor accessory].freeze
  EQUIPMENT_ITEM_SLOTS = {
    'leather-armor' => 'armor',
    'ring-of-protection' => 'accessory',
    'amulet-of-health' => 'accessory'
  }.freeze
  ATTUNABLE_ITEM_IDS = %w[ring-of-protection amulet-of-health].freeze
  MAX_ATTUNEMENTS = 1
  CONSUMABLE_EFFECTS = {
    'healing-potion' => { type: 'healing', hp_restored: 5 }
  }.freeze

  def create_play_campaign
    username = authenticate_play_actor!
    return if username.nil?
    return unless require_owner_username!(username, 'dm')

    id = params[:id]
    name = params[:name]
    max_players = params[:max_players]

    return unless require_nonempty_string!(id, 'id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_valid_integer!(max_players, 'max_players')

    if PLAY_CAMPAIGNS.key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    PLAY_CAMPAIGNS[id] = {
      name: name,
      owner: username,
      status: 'lobby',
      max_players: max_players.to_i,
      members: {}
    }

    render json: {
      id: id,
      name: name,
      owner: username,
      status: 'lobby',
      max_players: max_players.to_i
    }, status: :created
  end

  def join_play_campaign
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    user = USERS[username]
    role = user && user[:role]

    if role != 'player' || campaign[:status] != 'lobby'
      render json: { error: 'membership unavailable' }, status: :conflict
      return
    end

    character_id = params[:character_id]
    name = params[:name]
    klass = params[:class]

    return unless require_nonempty_string!(character_id, 'character_id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_nonempty_string!(klass, 'class')

    campaign[:members] ||= {}
    members = campaign[:members]

    if members.key?(username) || members.values.any? { |m| m[:character_id] == character_id }
      render json: { error: 'duplicate party member' }, status: :conflict
      return
    end

    if members.size >= campaign[:max_players]
      render json: { error: 'party full' }, status: :conflict
      return
    end

    member = { username: username, character_id: character_id, name: name, class: klass, hp_max: 20, hp_current: 20, status: 'conscious', owner: username, gold: 10 }
    members[username] = member
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: member, status: :created
  end

  def start_play_campaign
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    members = campaign[:members] || {}
    if campaign[:status] != 'lobby' || members.size < 2
      render json: { error: 'campaign not startable' }, status: :conflict
      return
    end

    current_actor = members.keys.first

    campaign[:status] = 'active'
    campaign[:current_actor] = current_actor
    campaign[:turn_number] = 1
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      id: params[:id],
      status: 'active',
      current_actor: current_actor,
      turn_number: 1
    }
  end

  def create_narration
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner_or_delegate!(username, campaign, 'narrate')

    text = params[:text]
    return unless require_nonempty_string!(text, 'text')

    event = append_event(campaign, kind: 'narration', actor: username, text: text)
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: event, status: :created
  end

  def create_action
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    type = params[:type]
    text = params[:text]

    return unless require_nonempty_string!(type, 'type')
    return unless require_nonempty_string!(text, 'text')

    members = campaign[:members] || {}
    unless members.key?(username) && campaign[:current_actor] == username
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    event = append_event(campaign, kind: 'action', actor: username, type: type, text: text, next_actor: 'dm')
    campaign[:current_actor] = 'dm'
    campaign[:last_player_actor] = username
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: event, status: :created
  end

  def create_resolution
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    unless username == campaign[:owner] && campaign[:current_actor] == campaign[:owner]
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    text = params[:text]
    return unless require_nonempty_string!(text, 'text')

    members = campaign[:members] || {}
    player_keys = members.keys
    current_turn = campaign[:turn_number] || 1
    next_actor = if player_keys.size <= 1
                   player_keys.first
                 elsif current_turn < 2
                   player_keys[1]
                 else
                   player_keys[0]
                 end

    event = append_event(campaign, kind: 'resolution', actor: username, text: text, next_actor: next_actor)
    campaign[:current_actor] = next_actor
    campaign[:turn_number] = (campaign[:turn_number] || 1) + 1
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: event.merge(turn_number: campaign[:turn_number]), status: :created
  end

  def play_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    members = campaign[:members] || {}
    actor = campaign[:current_actor]
    actor_user = actor && USERS[actor]
    phase = actor_user ? actor_user[:role] : campaign[:status]
    queue = members.keys.flat_map { |member_username| [member_username, 'dm'] }

    turn_number = campaign[:turn_number] || 1

    render json: {
      campaign_id: params[:id],
      current_actor: actor,
      phase: phase,
      turn_number: turn_number,
      queue: queue,
      overdue: false,
      logical_deadline: TURN_DEADLINE_OFFSET
    }
  end

  # Owner-only reminder to the current actor. Does not change whose turn it
  # is; only records that a nudge was sent. nudge_count is a per-campaign
  # logical counter (never wall-clock based) that only ever increases.
  def turn_nudge
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    message = params[:message]
    return unless require_nonempty_string!(message, 'message')

    campaign[:nudge_count] = (campaign[:nudge_count] || 0) + 1
    append_event(campaign, kind: 'nudge', actor: username, text: message)
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      actor: username,
      target: campaign[:current_actor],
      message: message,
      nudge_count: campaign[:nudge_count]
    }, status: :created
  end

  # A campaign member with role player reads only their own character
  # context: whether it is currently their turn, the current actor, their
  # own {id,name} character, and recent public events. DM-only fields are
  # never exposed through this endpoint.
  def my_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    members = campaign[:members] || {}
    member = members[username]
    if member.nil?
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    current_actor = campaign[:current_actor]
    events = campaign[:events] || []

    render json: {
      is_my_turn: current_actor == username,
      current_actor: current_actor,
      character: { id: member[:character_id], name: member[:name] },
      recent_events: events.last(5)
    }
  end

  # Owner-only view of the current turn state for GM tooling: whether the
  # owner needs to act, the current actor, party member summaries, and
  # recent events.
  def gm_status
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    members = campaign[:members] || {}
    events = campaign[:events] || []
    current_actor = campaign[:current_actor]

    party = members.values.map do |member|
      { username: member[:username], character_id: member[:character_id], name: member[:name], class: member[:class] }
    end

    render json: {
      needs_attention: current_actor == campaign[:owner],
      current_actor: current_actor,
      party: party,
      recent_events: events.last(5)
    }
  end

  # Owner-only update of the durable role-filtered campaign document. The
  # owner sees both fields; players only ever see the public story via
  # show_campaign_document.
  def update_campaign_document
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    story = params[:story]
    dm_notes = params[:dm_notes]

    return unless require_nonempty_string!(story, 'story')
    return unless require_nonempty_string!(dm_notes, 'dm_notes')

    campaign[:document] = { story: story, dm_notes: dm_notes }
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: { story: story, dm_notes: dm_notes }
  end

  def show_campaign_document
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    document = campaign[:document] || { story: '', dm_notes: '' }

    if username == campaign[:owner]
      render json: { story: document[:story], dm_notes: document[:dm_notes] }
    else
      render json: { story: document[:story] }
    end
  end

  # Owner-only (DM) creation of a campaign invitation for a registered
  # player identity. The target user must exist with role player; unknown
  # or non-player targets return 400. Duplicate invitation_id values, or a
  # second active pending invitation for the same target username, return
  # 409.
  def create_invitation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    invitation_id = params[:invitation_id]
    target_username = params[:username]
    character_id = params[:character_id]

    return unless require_nonempty_string!(invitation_id, 'invitation_id')
    return unless require_nonempty_string!(target_username, 'username')
    return unless require_nonempty_string!(character_id, 'character_id')

    target_user = USERS[target_username]
    if target_user.nil? || target_user[:role] != 'player'
      render json: { error: 'invalid username' }, status: :bad_request
      return
    end

    campaign[:invitations] ||= {}
    if campaign[:invitations].key?(invitation_id)
      render json: { error: 'duplicate invitation_id' }, status: :conflict
      return
    end

    if campaign[:invitations].values.any? { |inv| inv[:username] == target_username && inv[:status] == 'pending' }
      render json: { error: 'duplicate active invitation' }, status: :conflict
      return
    end

    invitation = {
      invitation_id: invitation_id,
      username: target_username,
      character_id: character_id,
      status: 'pending'
    }
    campaign[:invitations][invitation_id] = invitation
    campaign[:invitation_order] ||= []
    campaign[:invitation_order] << invitation_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: invitation, status: :created
  end

  # Only the invited target user may accept their own invitation. Other
  # campaign members and the DM receive 403; unknown invitation ids return
  # 404; repeating acceptance returns 409. On first acceptance the target
  # is added as a campaign member using the invitation's character_id.
  def accept_invitation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    invitation = (campaign[:invitations] || {})[params[:invitation_id]]
    if invitation.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    unless username == invitation[:username]
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    if invitation[:status] == 'accepted'
      render json: { error: 'already accepted' }, status: :conflict
      return
    end

    campaign[:members] ||= {}
    campaign[:members][username] = {
      username: username,
      character_id: invitation[:character_id],
      name: username,
      class: 'unspecified',
      hp_max: 20,
      hp_current: 20,
      status: 'conscious',
      owner: username,
      gold: 10
    }
    invitation[:status] = 'accepted'
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: invitation
  end

  # The DM sees every invitation. A target user sees only their own
  # invitations, including before they become a campaign member. Other
  # campaign members see an empty list.
  def list_invitations
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    invitations_map = campaign[:invitations] || {}
    order = campaign[:invitation_order] || []
    invitations = order.map { |id| invitations_map[id] }.compact

    unless username == campaign[:owner]
      invitations = invitations.select { |inv| inv[:username] == username }
    end

    render json: { invitations: invitations }
  end

  VALID_DELEGATION_POWERS = %w[narrate].freeze

  # Owner-only grant of limited co-GM authority to an existing campaign
  # member. Invalid payloads, non-member targets, empty/duplicate powers,
  # and powers other than the supported set return 400. A duplicate active
  # delegation for the same username returns 409.
  def create_delegation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    target_username = params[:username]
    powers = params[:powers]

    return unless require_nonempty_string!(target_username, 'username')

    members = campaign[:members] || {}
    unless members.key?(target_username)
      render json: { error: 'invalid username' }, status: :bad_request
      return
    end

    unless valid_delegation_powers?(powers)
      render json: { error: 'invalid powers' }, status: :bad_request
      return
    end

    campaign[:delegations] ||= {}
    existing = campaign[:delegations][target_username]
    if existing && existing[:active]
      render json: { error: 'duplicate active delegation' }, status: :conflict
      return
    end

    delegation = { username: target_username, powers: powers, active: true }
    campaign[:delegations][target_username] = delegation
    append_delegation_audit(campaign, username: target_username, action: 'granted', powers: powers)
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: delegation, status: :created
  end

  # Owner-only revocation of a previously granted delegation.
  def revoke_delegation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    delegation = (campaign[:delegations] || {})[params[:username]]
    if delegation.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    delegation[:active] = false
    append_delegation_audit(campaign, username: delegation[:username], action: 'revoked', powers: delegation[:powers])
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: delegation
  end

  # Owner-only immutable audit trail of every grant/revoke, in order.
  def delegations_audit
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    render json: { entries: campaign[:delegation_audit] || [] }
  end

  # Owner-only (DM) update of the pre-start session-zero settings. Only
  # allowed while the campaign is still in the lobby; once started, updates
  # return 409.
  def update_session_zero
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    if campaign[:status] != 'lobby'
      render json: { error: 'campaign already started' }, status: :conflict
      return
    end

    rules = params[:rules]
    tone = params[:tone]
    consent = params[:consent]

    return unless require_nonempty_string!(rules, 'rules')
    return unless require_nonempty_string!(tone, 'tone')

    unless consent.is_a?(Array) && !consent.empty? && consent.all? { |c| c.is_a?(String) && !c.empty? } && consent.uniq.length == consent.length
      render json: { error: 'invalid consent' }, status: :bad_request
      return
    end

    settings = { rules: rules, tone: tone, consent: consent }
    campaign[:session_zero] = settings
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: settings
  end

  # Any campaign participant (DM or joined player) may read the stored
  # session-zero settings. 404 if the campaign has none set yet.
  def show_session_zero
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    settings = campaign[:session_zero]
    if settings.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    render json: settings
  end

  # Owner-only (DM) creation of a content record with deterministic tags.
  # Duplicate content_id values within the campaign return 409.
  def create_content
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    content_id = params[:content_id]
    kind = params[:kind]
    text = params[:text]
    tags = params[:tags]

    return unless require_nonempty_string!(content_id, 'content_id')
    return unless require_nonempty_string!(kind, 'kind')
    return unless require_nonempty_string!(text, 'text')

    unless valid_tag_array?(tags, allow_empty: false)
      render json: { error: 'invalid tags' }, status: :bad_request
      return
    end

    campaign[:content] ||= {}
    if campaign[:content].key?(content_id)
      render json: { error: 'duplicate content_id' }, status: :conflict
      return
    end

    record = { content_id: content_id, kind: kind, text: text, tags: tags }
    campaign[:content][content_id] = record
    campaign[:content_order] ||= []
    campaign[:content_order] << content_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: record, status: :created
  end

  # Owner-only (DM) replacement of a content record's tags. The replacement
  # list may be empty.
  def update_content_tags
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    content = (campaign[:content] || {})[params[:content_id]]
    if content.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    tags = params[:tags]
    unless valid_tag_array?(tags, allow_empty: true)
      render json: { error: 'invalid tags' }, status: :bad_request
      return
    end

    content[:tags] = tags
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: content
  end

  # Any campaign member lists content records in creation order. The
  # optional exclude_tag filters out matching records for players; the DM
  # always sees every record regardless of exclude_tag.
  def list_content
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    exclude_tag = params[:exclude_tag]
    if !exclude_tag.nil? && !(exclude_tag.is_a?(String) && !exclude_tag.empty?)
      render json: { error: 'invalid exclude_tag' }, status: :bad_request
      return
    end

    content_map = campaign[:content] || {}
    order = campaign[:content_order] || []
    records = order.map { |id| content_map[id] }.compact

    if exclude_tag && username != campaign[:owner]
      records = records.reject { |r| r[:tags].include?(exclude_tag) }
    end

    render json: { content: records }
  end

  NOTE_VISIBILITIES = %w[private party].freeze

  # A campaign member (player or DM) creates a note. owner is derived from
  # the authenticated actor; clients cannot choose another owner. Duplicate
  # note_id values within the campaign return 409.
  def create_note
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    note_id = params[:note_id]
    text = params[:text]
    visibility = params[:visibility]

    return unless require_nonempty_string!(note_id, 'note_id')
    return unless require_nonempty_string!(text, 'text')

    unless visibility.is_a?(String) && NOTE_VISIBILITIES.include?(visibility)
      render json: { error: 'invalid visibility' }, status: :bad_request
      return
    end

    campaign[:notes] ||= {}
    if campaign[:notes].key?(note_id)
      render json: { error: 'duplicate note_id' }, status: :conflict
      return
    end

    note = { note_id: note_id, text: text, visibility: visibility, owner: username }
    campaign[:notes][note_id] = note
    campaign[:note_order] ||= []
    campaign[:note_order] << note_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: note, status: :created
  end

  # The DM sees every note. Players see all party notes plus only their own
  # private notes, in creation order.
  def list_notes
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    notes_map = campaign[:notes] || {}
    order = campaign[:note_order] || []
    notes = order.map { |id| notes_map[id] }.compact

    unless username == campaign[:owner]
      notes = notes.select { |n| n[:visibility] == 'party' || n[:owner] == username }
    end

    render json: { notes: notes }
  end

  # Returns a single note when readable: the DM may read any note; other
  # campaign members may read party notes and their own private notes.
  def show_note
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    note = (campaign[:notes] || {})[params[:note_id]]
    if note.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    if note[:visibility] == 'private' && username != note[:owner] && username != campaign[:owner]
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    render json: note
  end

  # Only the note owner may update text/visibility; the DM does not override
  # ownership.
  def update_note
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    note = (campaign[:notes] || {})[params[:note_id]]
    if note.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    unless username == note[:owner]
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    text = params[:text]
    visibility = params[:visibility]

    return unless require_nonempty_string!(text, 'text')

    unless visibility.is_a?(String) && NOTE_VISIBILITIES.include?(visibility)
      render json: { error: 'invalid visibility' }, status: :bad_request
      return
    end

    note[:text] = text
    note[:visibility] = visibility
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: note
  end

  # A campaign player with an owned character sends a whisper to another
  # current campaign member's character. from_character_id is derived from
  # the sender's own character. Duplicate whisper_id values within the
  # campaign return 409.
  def create_whisper
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_player_member!(username, campaign)

    whisper_id = params[:whisper_id]
    to_character_id = params[:to_character_id]
    text = params[:text]

    return unless require_nonempty_string!(whisper_id, 'whisper_id')
    return unless require_nonempty_string!(to_character_id, 'to_character_id')
    return unless require_nonempty_string!(text, 'text')

    unless find_member_by_character_id(campaign, to_character_id)
      render json: { error: 'invalid to_character_id' }, status: :bad_request
      return
    end

    campaign[:whispers] ||= {}
    if campaign[:whispers].key?(whisper_id)
      render json: { error: 'duplicate whisper_id' }, status: :conflict
      return
    end

    from_character_id = campaign[:members][username][:character_id]
    whisper = {
      whisper_id: whisper_id,
      from_character_id: from_character_id,
      to_character_id: to_character_id,
      text: text
    }
    campaign[:whispers][whisper_id] = whisper
    campaign[:whisper_order] ||= []
    campaign[:whisper_order] << whisper_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: whisper, status: :created
  end

  # The DM sees every whisper. Players see only whispers where their own
  # character is the sender or recipient.
  def list_whispers
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    whispers_map = campaign[:whispers] || {}
    order = campaign[:whisper_order] || []
    whispers = order.map { |id| whispers_map[id] }.compact

    unless username == campaign[:owner]
      character_id = (campaign[:members][username] || {})[:character_id]
      whispers = whispers.select do |w|
        w[:from_character_id] == character_id || w[:to_character_id] == character_id
      end
    end

    render json: { whispers: whispers }
  end

  # Only the character owner and campaign DM may read a character's basic
  # sheet. Other campaign members receive 403.
  def show_character_sheet
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    owner = member[:owner] || member[:username]
    unless username == owner || username == campaign[:owner]
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    render json: {
      character_id: params[:character_id],
      owner: owner,
      name: member[:name],
      class: member[:class],
      level: 1,
      proficiency_bonus: 2,
      hp_max: 10,
      armor_class: 10
    }
  end

  # Owner-only creation of a scene under a campaign. Duplicate scene ids
  # (within the same campaign) return 409.
  def create_scene
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    id = params[:id]
    name = params[:name]

    return unless require_nonempty_string!(id, 'id')
    return unless require_nonempty_string!(name, 'name')

    campaign[:scenes] ||= {}
    if campaign[:scenes].key?(id)
      render json: { error: 'duplicate scene id' }, status: :conflict
      return
    end

    campaign[:scenes][id] = { id: id, name: name, status: 'open' }
    append_event(campaign, kind: 'scene', actor: username, text: id)
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: campaign[:scenes][id], status: :created
  end

  # Owner-only: sets the campaign's current scene. Closed scenes may not
  # be entered.
  def enter_scene
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    scenes = campaign[:scenes] || {}
    scene = scenes[params[:scene_id]]
    if scene.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    if scene[:status] == 'closed'
      render json: { error: 'scene closed' }, status: :conflict
      return
    end

    campaign[:current_scene_id] = scene[:id]
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { current_scene_id: scene[:id], name: scene[:name] }
  end

  # Owner-only: marks a scene closed.
  def close_scene
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    scenes = campaign[:scenes] || {}
    scene = scenes[params[:scene_id]]
    if scene.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    scene[:status] = 'closed'
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { id: scene[:id], status: 'closed' }
  end

  # Any campaign member reads the open current scene. 404 if none is set
  # or if the current scene has since been closed.
  def current_scene
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    scenes = campaign[:scenes] || {}
    scene = scenes[campaign[:current_scene_id]]
    if scene.nil? || scene[:status] != 'open'
      render json: { error: 'not found' }, status: :not_found
      return
    end

    render json: { id: scene[:id], name: scene[:name], status: scene[:status] }
  end

  # Owner-only creation of a location under a campaign. Duplicate location
  # ids (within the same campaign) return 409.
  def create_location
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    id = params[:id]
    name = params[:name]

    return unless require_nonempty_string!(id, 'id')
    return unless require_nonempty_string!(name, 'name')

    campaign[:locations] ||= {}
    if campaign[:locations].key?(id)
      render json: { error: 'duplicate location id' }, status: :conflict
      return
    end

    campaign[:locations][id] = { id: id, name: name, connections: [] }
    campaign[:current_location_id] ||= id
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { id: id, name: name }, status: :created
  end

  # Owner-only creation of a one-way connection from an existing location to
  # another. Rejects connections to a missing destination location or to a
  # destination already connected from this location.
  def create_location_connection
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    locations = campaign[:locations] || {}
    from_location = locations[params[:from_id]]
    if from_location.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    to_id = params[:to_id]
    travel_turns = params[:travel_turns]

    return unless require_nonempty_string!(to_id, 'to_id')
    return unless require_valid_integer!(travel_turns, 'travel_turns')

    unless locations.key?(to_id)
      render json: { error: 'unknown destination location' }, status: :bad_request
      return
    end

    from_location[:connections] ||= []
    if from_location[:connections].any? { |c| c[:to_id] == to_id }
      render json: { error: 'already connected' }, status: :bad_request
      return
    end

    connection = { from_id: from_location[:id], to_id: to_id, travel_turns: travel_turns.to_i }
    from_location[:connections] << connection
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: connection, status: :created
  end

  # Any campaign member reads the valid outbound connections from a
  # location as travel destinations.
  def location_travel
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    locations = campaign[:locations] || {}
    location = locations[params[:loc_id]]
    if location.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    destinations = (location[:connections] || []).map do |connection|
      destination = locations[connection[:to_id]]
      { id: connection[:to_id], name: destination && destination[:name], travel_turns: connection[:travel_turns] }
    end

    render json: { destinations: destinations }
  end

  # The active player consumes an exploration turn to travel along a valid
  # outbound edge from the party's current location. Only the current actor
  # may call it; invalid destinations or acting out of turn return 409. The
  # location graph and current scene are unchanged by travel.
  def travel_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    destination_id = params[:destination_id]
    return unless require_nonempty_string!(destination_id, 'destination_id')

    members = campaign[:members] || {}
    unless members.key?(username) && campaign[:current_actor] == username
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    locations = campaign[:locations] || {}
    current_location = locations[campaign[:current_location_id]]
    connection = current_location && (current_location[:connections] || []).find { |c| c[:to_id] == destination_id }
    if connection.nil?
      render json: { error: 'invalid destination' }, status: :conflict
      return
    end

    event = append_event(
      campaign,
      kind: 'travel',
      actor: username,
      destination_id: destination_id,
      travel_turns: connection[:travel_turns],
      next_actor: 'dm'
    )
    campaign[:current_actor] = 'dm'
    campaign[:last_player_actor] = username
    campaign[:current_location_id] = destination_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: event, status: :created
  end

  # Owner-only creation of a campaign-bound encounter from the current party
  # state. Duplicate encounter ids or a campaign already in combat return
  # 409. The encounter is independent from the exploration turn queue until
  # the campaign returns to exploration.
  def create_encounter
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    id = params[:id]
    name = params[:name]

    return unless require_nonempty_string!(id, 'id')
    return unless require_nonempty_string!(name, 'name')

    campaign[:encounters] ||= {}

    if campaign[:encounters].key?(id)
      render json: { error: 'duplicate encounter id' }, status: :conflict
      return
    end

    if campaign[:active_encounter_id]
      render json: { error: 'campaign already in combat' }, status: :conflict
      return
    end

    encounter = { id: id, name: name, status: 'active', combatants: [] }
    campaign[:encounters][id] = encounter
    campaign[:active_encounter_id] = id
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: encounter, status: :created
  end

  # Owner-only addition of a deterministic monster combatant to an existing
  # encounter. Duplicate monster ids within the encounter return 409.
  def add_monster
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    monster_id = params[:monster_id]
    name = params[:name]
    hp_max = params[:hp_max]
    initiative = params[:initiative]

    return unless require_nonempty_string!(monster_id, 'monster_id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_valid_integer!(hp_max, 'hp_max')
    return unless require_valid_integer!(initiative, 'initiative')

    encounter[:monsters] ||= {}

    if encounter[:monsters].key?(monster_id)
      render json: { error: 'duplicate monster id' }, status: :conflict
      return
    end

    monster = {
      monster_id: monster_id,
      name: name,
      hp_max: hp_max.to_i,
      initiative: initiative.to_i,
      hp_current: hp_max.to_i
    }
    encounter[:monsters][monster_id] = monster
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: monster, status: :created
  end

  # Owner-only removal of a monster combatant from an encounter.
  def remove_monster
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    monster_id = params[:monster_id]
    encounter[:monsters] ||= {}

    if encounter[:monsters].key?(monster_id)
      encounter[:monsters].delete(monster_id)
      PLAY_CAMPAIGNS.persist(params[:campaign_id])
    else
      render json: { error: 'not found' }, status: :not_found
      return
    end

    render json: { removed: monster_id }, status: :ok
  end

  # Owner-only binding of an existing party member as a combatant in an
  # encounter. Duplicate members within the encounter return 409; a member
  # not in the party returns 400.
  def bind_combatant
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    member_username = params[:member]
    initiative = params[:initiative]

    return unless require_nonempty_string!(member_username, 'member')
    return unless require_valid_integer!(initiative, 'initiative')

    members = campaign[:members] || {}
    party_member = members[member_username]
    if party_member.nil?
      render json: { error: 'unknown member' }, status: :bad_request
      return
    end

    encounter[:combatants] ||= []
    if encounter[:combatants].any? { |c| c[:member] == member_username }
      render json: { error: 'duplicate combatant' }, status: :conflict
      return
    end

    combatant = {
      member: member_username,
      character_id: party_member[:character_id],
      name: party_member[:name],
      initiative: initiative.to_i
    }
    encounter[:combatants] << combatant
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: combatant, status: :created
  end

  # Owner-only removal of a party-member combatant from an encounter.
  def unbind_combatant
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    member_username = params[:member]
    encounter[:combatants] ||= []

    if encounter[:combatants].any? { |c| c[:member] == member_username }
      encounter[:combatants].reject! { |c| c[:member] == member_username }
      PLAY_CAMPAIGNS.persist(params[:campaign_id])
    else
      render json: { error: 'not found' }, status: :not_found
      return
    end

    render json: { removed: member_username }, status: :ok
  end

  # Returns the current combatant for the given encounter, viewable by any
  # campaign member. Initiative order is fixed the first time it is
  # observed (via this action or turn/advance) from the encounter's current
  # combatants and monsters.
  def encounter_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    ensure_encounter_turn_order!(campaign, encounter)

    render json: encounter_turn_json(encounter)
  end

  # Advances to the next combatant in deterministic initiative order. Only
  # the encounter owner or the current combatant may call it; acting out of
  # turn returns 409.
  def advance_encounter_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    ensure_encounter_turn_order!(campaign, encounter)

    order = encounter[:turn_order]
    active = order[encounter[:turn_index]]

    unless username == campaign[:owner] || username == active[:member]
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    encounter[:turn_index] += 1
    if encounter[:turn_index] >= order.length
      encounter[:turn_index] = 0
      encounter[:round] += 1
    end

    new_active = order[encounter[:turn_index]]
    decrement_conditions_for_target!(encounter, new_active[:target_id])

    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: encounter_turn_json(encounter)
  end

  # Moves the current combatant to a new position in the initiative order
  # without granting or duplicating a turn. Only the encounter owner or the
  # current combatant may call it; acting out of turn returns 409. An
  # out-of-bounds new_index returns 400.
  def delay_encounter_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    ensure_encounter_turn_order!(campaign, encounter)

    order = encounter[:turn_order]
    current_index = encounter[:turn_index]
    active = order[current_index]

    unless username == campaign[:owner] || username == active[:member]
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    index = params[:new_index]
    return unless require_valid_integer!(index, 'new_index')

    new_index = index.to_i
    if new_index < 0 || new_index >= order.length
      render json: { error: 'invalid new_index' }, status: :bad_request
      return
    end

    entry = order.delete_at(current_index)
    insert_at = [new_index, order.length].min
    order.insert(insert_at, entry)
    encounter[:turn_index] = insert_at

    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { order: encounter_order_json(encounter) }, status: :ok
  end

  # Records that the current combatant is readying an action to trigger
  # later; it does not change the turn order or advance the turn. Only the
  # current combatant may call it; acting out of turn returns 409.
  def ready_encounter_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    ensure_encounter_turn_order!(campaign, encounter)

    order = encounter[:turn_order]
    active = order[encounter[:turn_index]]

    unless active[:member] == username
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    trigger = params[:trigger]
    return unless require_nonempty_string!(trigger, 'trigger')

    ready_record = { actor: username, trigger: trigger }
    encounter[:ready_actions] ||= []
    encounter[:ready_actions] << ready_record
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: ready_record, status: :created
  end

  REST_TYPES = %w[short long].freeze

  # The active player consumes an exploration turn to take a short or long
  # rest. Only the current actor may call it; a long rest restores the
  # acting character's hp_current to hp_max. Acting out of turn returns 409;
  # an invalid type returns 400.
  def rest_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    type = params[:type]
    unless type.is_a?(String) && REST_TYPES.include?(type)
      render json: { error: 'invalid type' }, status: :bad_request
      return
    end

    members = campaign[:members] || {}
    unless members.key?(username) && campaign[:current_actor] == username
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    member = members[username]
    member[:hp_max] ||= 20
    member[:hp_current] ||= 20
    member[:hp_current] = member[:hp_max] if type == 'long'

    event = append_event(
      campaign,
      kind: 'rest',
      actor: username,
      type: type,
      hp_current: member[:hp_current],
      hp_max: member[:hp_max],
      next_actor: 'dm'
    )
    campaign[:current_actor] = 'dm'
    campaign[:last_player_actor] = username
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: event, status: :created
  end

  COMBAT_ACTION_TYPES = %w[attack help dodge ready].freeze

  # The current combatant submits a typed combat action that is recorded but
  # does not itself advance the encounter turn. Only the current combatant
  # may call it; acting out of turn returns 409. Invalid types return 400.
  def create_combat_action
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    type = params[:type]
    text = params[:text]
    target = params[:target]

    unless type.is_a?(String) && COMBAT_ACTION_TYPES.include?(type)
      render json: { error: 'invalid type' }, status: :bad_request
      return
    end
    return unless require_nonempty_string!(text, 'text')

    ensure_encounter_turn_order!(campaign, encounter)

    order = encounter[:turn_order]
    active = order[encounter[:turn_index]]

    unless active[:member] == username
      render json: { error: 'not your turn' }, status: :conflict
      return
    end

    fields = { kind: 'combat_action', actor: username, type: type }
    fields[:target] = target unless target.nil?
    fields[:text] = text

    event = append_event(campaign, **fields)
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: event, status: :created
  end

  # Owner-only application of deterministic damage to an encounter
  # combatant (monster or bound party member). HP floors at 0.
  def apply_damage
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    target = params[:target]
    amount = params[:amount]

    return unless require_nonempty_string!(target, 'target')
    return unless require_valid_integer!(amount, 'amount')

    hp_holder = resolve_combat_target(campaign, encounter, target)
    if hp_holder.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    hp_before = hp_holder[:hp_current]
    hp_after = [hp_before - amount.to_i, 0].max
    hp_holder[:hp_current] = hp_after
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { target: target, hp_before: hp_before, hp_after: hp_after, damage: amount.to_i }, status: :ok
  end

  # Owner-only application of deterministic healing to an encounter
  # combatant (monster or bound party member). HP caps at hp_max.
  def apply_healing
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    target = params[:target]
    amount = params[:amount]

    return unless require_nonempty_string!(target, 'target')
    return unless require_valid_integer!(amount, 'amount')

    hp_holder = resolve_combat_target(campaign, encounter, target)
    if hp_holder.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    hp_before = hp_holder[:hp_current]
    hp_after = [hp_before + amount.to_i, hp_holder[:hp_max]].min
    hp_holder[:hp_current] = hp_after
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { target: target, hp_before: hp_before, hp_after: hp_after, healing: amount.to_i }, status: :ok
  end

  # Owner-only application of a named condition to an encounter combatant
  # (monster or bound party member). Conditions decrement remaining_rounds
  # at the start of the target's turn and are removed at 0.
  def add_condition
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    target = params[:target]
    condition = params[:condition]
    duration_rounds = params[:duration_rounds]

    return unless require_nonempty_string!(target, 'target')
    return unless require_nonempty_string!(condition, 'condition')
    return unless require_valid_integer!(duration_rounds, 'duration_rounds')

    unless combat_target_exists?(encounter, target)
      render json: { error: 'not found' }, status: :not_found
      return
    end

    encounter[:conditions] ||= {}
    encounter[:conditions][target] ||= []
    encounter[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds.to_i }
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { target: target, conditions: encounter[:conditions][target] }, status: :created
  end

  # Returns the full encounter state (round, turn_index, active, initiative
  # order, and per-target conditions), viewable by any campaign member.
  def encounter_status
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    ensure_encounter_turn_order!(campaign, encounter)

    render json: encounter_status_json(encounter)
  end

  # Owner-only application of deterministic damage directly to a party
  # character (outside an encounter). HP floors at 0; reaching 0 knocks the
  # character unconscious and resets its death save counters.
  def character_damage
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    amount = params[:amount]
    return unless require_valid_integer!(amount, 'amount')

    member[:hp_max] ||= 20
    member[:hp_current] ||= 20
    member[:status] ||= 'conscious'

    hp_before = member[:hp_current]
    hp_after = [hp_before - amount.to_i, 0].max
    member[:hp_current] = hp_after

    if hp_after == 0 && member[:status] == 'conscious'
      member[:status] = 'unconscious'
      member[:death_save_successes] = 0
      member[:death_save_failures] = 0
    end

    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      target: params[:char_id],
      hp_before: hp_before,
      hp_after: hp_after,
      damage: amount.to_i,
      status: member[:status]
    }, status: :ok
  end

  DEATH_SAVE_OUTCOMES = %w[success failure].freeze

  # The character's owner rolls a death save while unconscious. Three
  # successes stabilize the character; three failures kill it. Non-owners
  # are forbidden; rolls on a character that isn't unconscious conflict.
  def death_save
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member

    unless member[:username] == username
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    unless member[:status] == 'unconscious'
      render json: { error: 'character not unconscious' }, status: :conflict
      return
    end

    outcome = params[:outcome]
    unless outcome.is_a?(String) && DEATH_SAVE_OUTCOMES.include?(outcome)
      render json: { error: 'invalid outcome' }, status: :bad_request
      return
    end

    member[:death_save_successes] ||= 0
    member[:death_save_failures] ||= 0

    if outcome == 'success'
      member[:death_save_successes] += 1
      member[:status] = 'stable' if member[:death_save_successes] >= 3
    else
      member[:death_save_failures] += 1
      member[:status] = 'dead' if member[:death_save_failures] >= 3
    end

    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      successes: member[:death_save_successes],
      failures: member[:death_save_failures],
      status: member[:status]
    }, status: :created
  end

  # Any campaign member may check a character's current HP and status.
  def character_status
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    member[:hp_max] ||= 20
    member[:hp_current] ||= 20
    member[:status] ||= 'conscious'

    render json: {
      character_id: params[:char_id],
      hp_current: member[:hp_current],
      hp_max: member[:hp_max],
      status: member[:status]
    }
  end

  # Any campaign member may read a character's current owning player.
  def character_owner
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member
    member[:owner] ||= member[:username]

    render json: { character_id: params[:char_id], owner: member[:owner] }
  end

  # A campaign member may claim a character that has no current owner.
  # Already-owned characters return 409, regardless of who's asking.
  def claim_character
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    if member[:owner] && member[:owner] != username
      render json: { error: 'already owned' }, status: :conflict
      return
    end

    member[:owner] = username
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { character_id: params[:char_id], owner: member[:owner] }, status: :created
  end

  # Only the current owner may transfer a character to another campaign
  # member. The new owner must already be a member of the campaign.
  def transfer_character
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    unless member[:owner] == username
      render json: { error: 'forbidden' }, status: :forbidden
      return
    end

    new_owner = params[:new_owner]
    return unless require_nonempty_string!(new_owner, 'new_owner')

    unless (campaign[:members] || {}).key?(new_owner)
      render json: { error: 'not a campaign member' }, status: :bad_request
      return
    end

    member[:owner] = new_owner
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { character_id: params[:char_id], owner: member[:owner] }
  end

  # Any campaign member may read a character's current gold balance.
  def character_currency
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member
    member[:gold] ||= 0

    render json: { character_id: params[:char_id], gold: member[:gold] }
  end

  # Only the source character's owner may transfer gold. The destination
  # must be a different character in the same campaign; unknown
  # destinations, same-character destinations, and non-positive gold
  # amounts return 400. Insufficient source balance returns 409 and leaves
  # both balances unchanged. Successful transfers debit/credit atomically
  # and assign a deterministic, campaign-local, 1-based transfer id.
  def create_currency_transfer
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    from_member = load_character_member_or_404(campaign)
    return unless from_member
    return unless require_character_owner!(from_member, username)

    to_character_id = params[:to_character_id]
    gold = params[:gold]

    to_member = find_member_by_character_id(campaign, to_character_id)

    if to_member.nil? || to_character_id == params[:char_id]
      render json: { error: 'invalid to_character_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(gold, 'gold')
    gold = gold.to_i

    unless gold.positive?
      render json: { error: 'invalid gold' }, status: :bad_request
      return
    end

    from_member[:gold] ||= 0
    to_member[:gold] ||= 0

    if from_member[:gold] < gold
      render json: { error: 'insufficient gold' }, status: :conflict
      return
    end

    from_member[:gold] -= gold
    to_member[:gold] += gold

    campaign[:currency_transfers] ||= []
    transfer_id = campaign[:currency_transfers].length + 1
    campaign[:currency_transfers] << transfer_id

    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      from_character_id: params[:char_id],
      to_character_id: to_character_id,
      gold: gold,
      from_gold: from_member[:gold],
      to_gold: to_member[:gold],
      transfer_id: transfer_id
    }, status: :created
  end

  RACES = %w[dragonborn dwarf elf gnome half-elf half-orc halfling human tiefling].freeze
  CLASSES = %w[barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard].freeze
  BACKGROUNDS = %w[acolyte charlatan criminal entertainer folk-hero guild-artisan hermit noble outlander sage sailor soldier].freeze
  HIT_DICE = {
    'barbarian' => 12,
    'fighter' => 10, 'paladin' => 10, 'ranger' => 10,
    'bard' => 8, 'cleric' => 8, 'druid' => 8, 'monk' => 8, 'rogue' => 8, 'warlock' => 8,
    'sorcerer' => 6, 'wizard' => 6
  }.freeze
  ABILITY_KEYS = %w[str dex con int wis cha].freeze
  SKILLS = %w[
    acrobatics animal-handling arcana athletics deception history insight
    intimidation investigation medicine nature perception performance
    persuasion religion sleight-of-hand stealth survival
  ].freeze

  # The character's owner submits race/class/background and ability scores.
  # Validates choices against the known reference tables and ability scores
  # in 1-30, then returns the resulting level-1 sheet with derived hp_max and
  # proficiency_bonus. Only the character's owner may call it.
  def build_character
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    race = params[:race]
    klass = params[:class]
    background = params[:background]
    abilities = params[:abilities]

    unless race.is_a?(String) && RACES.include?(race)
      render json: { error: 'invalid race' }, status: :bad_request
      return
    end

    unless klass.is_a?(String) && CLASSES.include?(klass)
      render json: { error: 'invalid class' }, status: :bad_request
      return
    end

    unless background.is_a?(String) && BACKGROUNDS.include?(background)
      render json: { error: 'invalid background' }, status: :bad_request
      return
    end

    unless abilities.is_a?(ActionController::Parameters) || abilities.is_a?(Hash)
      render json: { error: 'invalid abilities' }, status: :bad_request
      return
    end

    ability_scores = {}
    ABILITY_KEYS.each do |key|
      value = abilities[key]
      unless valid_integer?(value) && value.to_i.between?(1, 30)
        render json: { error: "invalid ability: #{key}" }, status: :bad_request
        return
      end
      ability_scores[key] = value.to_i
    end

    level = 1
    hp_max = HIT_DICE[klass] + ability_mod(ability_scores['con'])

    member[:race] = race
    member[:class] = klass
    member[:background] = background
    member[:abilities] = ability_scores
    member[:level] = level
    member[:hp_max] = hp_max
    member[:proficiency_bonus] = proficiency_bonus(level)
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      race: race,
      class: klass,
      background: background,
      level: level,
      hp_max: hp_max,
      proficiency_bonus: proficiency_bonus(level)
    }, status: :ok
  end

  # The character's owner advances the character exactly one level at a
  # time, gaining deterministic max HP (class hit die + con modifier, same
  # formula used at character creation) and an updated proficiency bonus.
  def level_up
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    new_level = params[:level]
    return unless require_valid_integer!(new_level, 'level')
    new_level = new_level.to_i

    current_level = member[:level] || 1
    unless new_level == current_level + 1
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    die = HIT_DICE[member[:class]] || 8
    con_score = (member[:abilities] || {})['con'] || 10
    average_die_roll = (die / 2) + 1
    hp_gain = average_die_roll + ability_mod(con_score)

    member[:hp_max] = (member[:hp_max] || die + ability_mod(con_score)) + hp_gain
    member[:level] = new_level
    member[:proficiency_bonus] = proficiency_bonus(new_level)
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      level: new_level,
      hp_max: member[:hp_max],
      hit_dice: "1d#{die}",
      proficiency_bonus: member[:proficiency_bonus]
    }, status: :ok
  end

  # Owner-only skill check resolution: modifier is the character's ability
  # modifier plus their proficiency bonus when proficient, total is roll +
  # modifier. Both skill and ability must be from the known lists.
  def skill_check
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    skill = params[:skill]
    ability = params[:ability]
    proficient = params[:proficient]
    roll = params[:roll]

    unless skill.is_a?(String) && SKILLS.include?(skill)
      render json: { error: 'invalid skill' }, status: :bad_request
      return
    end

    unless ability.is_a?(String) && ABILITY_KEYS.include?(ability)
      render json: { error: 'invalid ability' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(roll, 'roll')
    roll = roll.to_i

    proficient = proficient == true || proficient == 'true'

    ability_score = (member[:abilities] || {})[ability] || 10
    modifier = ability_mod(ability_score)
    modifier += member[:proficiency_bonus] || proficiency_bonus(member[:level] || 1) if proficient

    render json: {
      character_id: params[:char_id],
      skill: skill,
      ability: ability,
      modifier: modifier,
      total: roll + modifier
    }, status: :ok
  end

  # Classes capable of learning/casting spells. Non-casters (barbarian,
  # fighter, monk, rogue) can never add a spell, regardless of spell_id.
  SPELLCASTING_CLASSES = %w[bard cleric druid paladin ranger sorcerer warlock wizard].freeze

  # Owner-only: adds a known spell to the character's spellbook if their
  # class can cast spells at all. Duplicate spell_ids return 409.
  def add_spell
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    spell_id = params[:spell_id]
    name = params[:name]
    level = params[:level]

    return unless require_nonempty_string!(spell_id, 'spell_id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_valid_integer!(level, 'level')
    level = level.to_i

    unless level.between?(0, 9)
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    unless SPELLCASTING_CLASSES.include?(member[:class])
      render json: { error: 'invalid class/spell combination' }, status: :bad_request
      return
    end

    member[:spells] ||= {}

    if member[:spells].key?(spell_id)
      render json: { error: 'spell already known' }, status: :conflict
      return
    end

    member[:spells][spell_id] = { spell_id: spell_id, name: name, level: level }
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { spell_id: spell_id, name: name, level: level }, status: :created
  end

  # Any campaign member may read a character's known spells.
  def list_spells
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    spells = (member[:spells] || {}).values.map do |spell|
      { spell_id: spell[:spell_id], name: spell[:name], level: spell[:level] }
    end

    render json: { spells: spells }
  end

  # Owner-only: replaces the character's prepared spell list. The class must
  # be a spellcaster, every spell_id must already be known, and the list may
  # not exceed the character's level (at level 1 a wizard may prepare at most
  # one spell).
  def update_prepared_spells
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    unless SPELLCASTING_CLASSES.include?(member[:class])
      render json: { error: 'invalid class/spell combination' }, status: :bad_request
      return
    end

    spell_ids = params[:spell_ids]
    unless spell_ids.is_a?(Array) && spell_ids.all? { |id| id.is_a?(String) }
      render json: { error: 'invalid spell_ids' }, status: :bad_request
      return
    end

    known_spells = member[:spells] || {}
    unless spell_ids.all? { |id| known_spells.key?(id) }
      render json: { error: 'unknown spell' }, status: :bad_request
      return
    end

    max_prepared = member[:level] || 1
    if spell_ids.length > max_prepared
      render json: { error: 'too many prepared spells' }, status: :bad_request
      return
    end

    member[:prepared_spells] = spell_ids
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      prepared_spells: spell_ids,
      max_prepared: max_prepared
    }, status: :ok
  end

  # Any campaign member may read a character's prepared spells.
  def prepared_spells
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    max_prepared = member[:level] || 1

    render json: {
      character_id: params[:char_id],
      prepared_spells: member[:prepared_spells] || [],
      max_prepared: max_prepared
    }
  end

  # Spell slots available per character level, keyed by spell level. Mirrors
  # the standard full-caster progression, except level 1 grants a single
  # first-level slot rather than two.
  SPELL_SLOTS_BY_LEVEL = {
    1 => { 1 => 1 },
    2 => { 1 => 3 },
    3 => { 1 => 4, 2 => 2 },
    4 => { 1 => 4, 2 => 3 },
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
  }.freeze

  # Owner-only: casts a currently prepared spell if the character has a
  # remaining slot of the spell's level, recording the event to the
  # character's cast history. Non-owners get 403; a non-spellcaster class or
  # an unprepared spell gets 400; an exhausted slot gets 409.
  def cast_spell
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    spell_id = params[:spell_id]
    target = params[:target]
    return unless require_nonempty_string!(spell_id, 'spell_id')
    return unless require_nonempty_string!(target, 'target')

    unless SPELLCASTING_CLASSES.include?(member[:class])
      render json: { error: 'invalid class/spell combination' }, status: :bad_request
      return
    end

    prepared = member[:prepared_spells] || []
    unless prepared.include?(spell_id)
      render json: { error: 'spell not prepared' }, status: :bad_request
      return
    end

    spell = (member[:spells] || {})[spell_id]
    spell_level = spell ? spell[:level] : 0
    spell_level = 1 if spell_level.to_i <= 0

    level_slots = SPELL_SLOTS_BY_LEVEL[member[:level] || 1] || {}
    total_slots = level_slots[spell_level] || 0

    member[:spell_slots_used] ||= {}
    used = member[:spell_slots_used][spell_level] || 0
    slots_remaining = total_slots - used

    if slots_remaining <= 0
      render json: { error: 'no remaining spell slots' }, status: :conflict
      return
    end

    member[:spell_slots_used][spell_level] = used + 1
    slots_remaining -= 1

    member[:casts] ||= []
    sequence = member[:casts].length + 1

    cast_record = {
      character_id: params[:char_id],
      spell_id: spell_id,
      target: target,
      slot_level: spell_level,
      slots_remaining: slots_remaining,
      sequence: sequence
    }
    member[:casts] << cast_record
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: cast_record, status: :created
  end

  # Any campaign member may read a character's cast history.
  def list_casts
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    render json: { casts: member[:casts] || [] }
  end

  # Owner-only: sets (or replaces) the character's active concentration.
  # Requires a spellcasting class, a known and currently prepared spell, and
  # a positive duration_turns.
  def set_concentration
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    spell_id = params[:spell_id]
    target = params[:target]
    duration_turns = params[:duration_turns]

    return unless require_nonempty_string!(spell_id, 'spell_id')
    return unless require_nonempty_string!(target, 'target')
    return unless require_valid_integer!(duration_turns, 'duration_turns')
    duration_turns = duration_turns.to_i

    unless SPELLCASTING_CLASSES.include?(member[:class])
      render json: { error: 'invalid class/spell combination' }, status: :bad_request
      return
    end

    known_spells = member[:spells] || {}
    unless known_spells.key?(spell_id)
      render json: { error: 'unknown spell' }, status: :bad_request
      return
    end

    prepared = member[:prepared_spells] || []
    unless prepared.include?(spell_id)
      render json: { error: 'spell not prepared' }, status: :bad_request
      return
    end

    unless duration_turns.positive?
      render json: { error: 'invalid duration_turns' }, status: :bad_request
      return
    end

    member[:concentration] = {
      spell_id: spell_id,
      target: target,
      remaining_turns: duration_turns
    }
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { character_id: params[:char_id], concentration: member[:concentration] }, status: :ok
  end

  # Any campaign member may read a character's active concentration.
  def get_concentration
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    render json: { character_id: params[:char_id], concentration: member[:concentration] }
  end

  # Any campaign member may advance the active concentration by one turn,
  # decrementing remaining_turns and clearing it once exhausted.
  def advance_concentration_turn
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    concentration = member[:concentration]
    if concentration
      concentration[:remaining_turns] -= 1
      member[:concentration] = nil if concentration[:remaining_turns] <= 0
      PLAY_CAMPAIGNS.persist(params[:campaign_id])
    end

    render json: { character_id: params[:char_id], concentration: member[:concentration] }
  end

  # Owner-only: clears the character's active concentration outright.
  def clear_concentration
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    member[:concentration] = nil
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: { character_id: params[:char_id], concentration: nil }
  end

  # Owner-only: adds to the character's inventory item stack. item_id must
  # be a known catalog item and quantity must be positive.
  def add_inventory_item
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    item_id = params[:item_id]
    quantity = params[:quantity]

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(quantity, 'quantity')
    quantity = quantity.to_i

    unless quantity.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    member[:inventory] ||= {}
    member[:inventory][item_id] = (member[:inventory][item_id] || 0) + quantity
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      item_id: item_id,
      quantity: quantity,
      total_quantity: member[:inventory][item_id]
    }, status: :created
  end

  # Any campaign member may read a character's held item stacks, in
  # lexicographic item_id order.
  def list_inventory_items
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    inventory = member[:inventory] || {}
    items = inventory.keys.sort.select { |item_id| inventory[item_id].positive? }
                      .map { |item_id| { item_id: item_id, quantity: inventory[item_id] } }

    render json: { character_id: params[:char_id], items: items }
  end

  # Owner-only: removes from the character's inventory item stack. Quantity
  # must be positive and no larger than the held stack (409 otherwise).
  def remove_inventory_item
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    item_id = params[:item_id]
    quantity = params[:quantity]

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(quantity, 'quantity')
    quantity = quantity.to_i

    unless quantity.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    member[:inventory] ||= {}
    held = member[:inventory][item_id] || 0

    if quantity > held
      render json: { error: 'insufficient quantity' }, status: :conflict
      return
    end

    member[:inventory][item_id] = held - quantity
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      item_id: item_id,
      quantity: quantity,
      total_quantity: member[:inventory][item_id]
    }, status: :ok
  end

  # Owner-only: consumes one unit of a held consumable item stack. Only
  # catalog items listed in CONSUMABLE_EFFECTS are consumable; other known
  # items return 400, as do unknown item IDs. A missing or empty stack
  # returns 409.
  def consume_inventory_item
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    item_id = params[:item_id]

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    effect = CONSUMABLE_EFFECTS[item_id]
    unless effect
      render json: { error: 'item is not consumable' }, status: :bad_request
      return
    end

    member[:inventory] ||= {}
    held = member[:inventory][item_id] || 0

    if held <= 0
      render json: { error: 'no held stack to consume' }, status: :conflict
      return
    end

    member[:inventory][item_id] = held - 1
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      item_id: item_id,
      quantity_consumed: 1,
      total_quantity: member[:inventory][item_id],
      effect: effect
    }, status: :ok
  end

  # Owner-only: equips a held inventory item into the given slot. The item
  # must be a known equipment item, match the slot's legal item, and be
  # currently held (positive quantity) in the character's inventory.
  def update_equipment
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    slot = params[:slot]
    unless EQUIPMENT_SLOTS.include?(slot)
      render json: { error: 'invalid slot' }, status: :bad_request
      return
    end

    item_id = params[:item_id]
    unless EQUIPMENT_ITEM_SLOTS.key?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    unless EQUIPMENT_ITEM_SLOTS[item_id] == slot
      render json: { error: 'item does not match slot' }, status: :bad_request
      return
    end

    held = (member[:inventory] || {})[item_id] || 0
    unless held.positive?
      render json: { error: 'item not held' }, status: :bad_request
      return
    end

    member[:equipment] ||= {}
    member[:equipment][slot] = { item_id: item_id, attuned: false }
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      slot: slot,
      item_id: item_id,
      attuned: false
    }, status: :ok
  end

  # Any campaign member may read a character's equipped item for a slot.
  # An empty slot returns item_id: '' rather than 404.
  def show_equipment
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    member = load_character_member_or_404(campaign)
    return unless member

    slot = params[:slot]
    unless EQUIPMENT_SLOTS.include?(slot)
      render json: { error: 'invalid slot' }, status: :bad_request
      return
    end

    entry = (member[:equipment] || {})[slot]

    render json: {
      character_id: params[:char_id],
      slot: slot,
      item_id: entry ? entry[:item_id] : '',
      attuned: entry ? entry[:attuned] : false
    }, status: :ok
  end

  # Owner-only: attunes the equipped item in the given slot. The slot must
  # hold an attunable accessory, and a character may have at most
  # MAX_ATTUNEMENTS items attuned at once (409 if the limit is already met).
  def attune_equipment
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign

    member = load_character_member_or_404(campaign)
    return unless member
    return unless require_character_owner!(member, username)

    slot = params[:slot]
    unless EQUIPMENT_SLOTS.include?(slot)
      render json: { error: 'invalid slot' }, status: :bad_request
      return
    end

    entry = (member[:equipment] || {})[slot]
    unless entry && ATTUNABLE_ITEM_IDS.include?(entry[:item_id])
      render json: { error: 'slot is not an attunable item' }, status: :bad_request
      return
    end

    member[:attunement_count] ||= 0

    if entry[:attuned] || member[:attunement_count] >= MAX_ATTUNEMENTS
      render json: { error: 'attunement limit reached' }, status: :conflict
      return
    end

    entry[:attuned] = true
    member[:attunement_count] += 1
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      character_id: params[:char_id],
      slot: slot,
      item_id: entry[:item_id],
      attuned: true,
      attunement_count: member[:attunement_count],
      max_attunements: MAX_ATTUNEMENTS
    }, status: :ok
  end

  # Owner-only, once-per-encounter award of deterministic XP and loot.
  # Duplicate awards on an already-rewarded encounter return 409.
  def award_encounter_rewards
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    if encounter[:rewards]
      render json: { error: 'rewards already awarded' }, status: :conflict
      return
    end

    xp = params[:xp]
    loot = params[:loot]

    return unless require_valid_integer!(xp, 'xp')

    unless loot.is_a?(Array)
      render json: { error: 'invalid loot' }, status: :bad_request
      return
    end

    loot_items = []
    loot.each do |item|
      slug = item[:slug]
      quantity = item[:quantity]
      unless slug.is_a?(String) && !slug.empty? && valid_integer?(quantity)
        render json: { error: 'invalid loot' }, status: :bad_request
        return
      end
      loot_items << { slug: slug, quantity: quantity.to_i }
    end

    reward = { encounter_id: encounter[:id], xp: xp.to_i, loot: loot_items }
    encounter[:rewards] = reward
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: reward, status: :ok
  end

  # Owner-only closing of an encounter. xp_awarded reflects a prior rewards
  # call, or 0 if the encounter was closed before rewards were awarded.
  def close_encounter
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    encounter[:status] = 'closed'
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      id: encounter[:id],
      status: encounter[:status],
      xp_awarded: encounter[:rewards] ? encounter[:rewards][:xp] : 0
    }, status: :ok
  end

  # Owner-only closing of the active encounter that also returns the
  # campaign to its exploration turn queue, resuming from whichever actor
  # held the turn before combat began (campaign[:current_actor] is never
  # touched by encounter/combat actions, so it's still holding that value).
  # If this encounter isn't the campaign's active combat encounter, 409.
  def end_encounter
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    encounter = load_encounter_or_404(campaign)
    return unless encounter

    if campaign[:active_encounter_id] != params[:encounter_id]
      render json: { error: 'campaign not in combat' }, status: :conflict
      return
    end

    encounter[:status] = 'closed' if encounter[:status] != 'closed'
    campaign[:active_encounter_id] = nil
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      campaign_id: params[:campaign_id],
      status: campaign[:status],
      phase: 'exploration',
      current_actor: campaign[:current_actor]
    }, status: :ok
  end

  # Owner-only (DM) creation of a campaign-scoped loot record for a known
  # inventory catalog item. Duplicate loot_id values within the campaign
  # return 409. The created record is immutable and open for voting.
  def create_loot
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    loot_id = params[:loot_id]
    item_id = params[:item_id]
    quantity = params[:quantity]

    return unless require_nonempty_string!(loot_id, 'loot_id')

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(quantity, 'quantity')
    quantity = quantity.to_i

    unless quantity.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    campaign[:loot] ||= {}
    if campaign[:loot].key?(loot_id)
      render json: { error: 'duplicate loot id' }, status: :conflict
      return
    end

    loot = {
      loot_id: loot_id,
      item_id: item_id,
      quantity: quantity,
      status: 'open',
      votes: {},
      recipient_character_id: nil,
      final_votes: nil
    }
    campaign[:loot][loot_id] = loot
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      loot_id: loot_id,
      item_id: item_id,
      quantity: quantity,
      status: 'open'
    }, status: :created
  end

  # Player-only casting of an immutable vote for who should receive a loot
  # record. The recipient must be a character in the same campaign. Each
  # player identity may vote once per loot record; duplicate or changed
  # votes return 409.
  def create_loot_vote
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_player_member!(username, campaign)

    loot = load_loot_or_404(campaign)
    return unless loot

    recipient_character_id = params[:recipient_character_id]
    return unless require_nonempty_string!(recipient_character_id, 'recipient_character_id')

    recipient_member = find_member_by_character_id(campaign, recipient_character_id)
    if recipient_member.nil?
      render json: { error: 'invalid recipient_character_id' }, status: :bad_request
      return
    end

    loot[:votes] ||= {}
    if loot[:votes].key?(username)
      render json: { error: 'duplicate vote' }, status: :conflict
      return
    end

    loot[:votes][username] = recipient_character_id
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    votes_for_recipient = loot[:votes].values.count { |v| v == recipient_character_id }

    render json: {
      loot_id: loot[:loot_id],
      voter: username,
      recipient_character_id: recipient_character_id,
      votes_for_recipient: votes_for_recipient
    }, status: :created
  end

  # Owner-only (DM) assignment of open loot to its unambiguous highest-vote
  # recipient. Requires the loot to be open and to have a single highest
  # vote recipient; tied or voteless loot returns 409. Atomically adds the
  # loot quantity to the recipient's inventory and closes the loot.
  # Duplicate assignment attempts return 409 without adding inventory again.
  def assign_loot
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_owner!(username, campaign)

    loot = load_loot_or_404(campaign)
    return unless loot

    if loot[:status] != 'open'
      render json: { error: 'loot not open' }, status: :conflict
      return
    end

    votes = loot[:votes] || {}
    tally = Hash.new(0)
    votes.each_value { |recipient_character_id| tally[recipient_character_id] += 1 }

    if tally.empty?
      render json: { error: 'no votes' }, status: :conflict
      return
    end

    max_votes = tally.values.max
    top_recipients = tally.select { |_, count| count == max_votes }.keys

    if top_recipients.length != 1
      render json: { error: 'ambiguous vote result' }, status: :conflict
      return
    end

    recipient_character_id = top_recipients.first
    recipient_member = find_member_by_character_id(campaign, recipient_character_id)

    recipient_member[:inventory] ||= {}
    recipient_member[:inventory][loot[:item_id]] = (recipient_member[:inventory][loot[:item_id]] || 0) + loot[:quantity]

    loot[:status] = 'assigned'
    loot[:recipient_character_id] = recipient_character_id
    loot[:final_votes] = tally
    PLAY_CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      loot_id: loot[:loot_id],
      recipient_character_id: recipient_character_id,
      item_id: loot[:item_id],
      quantity: loot[:quantity],
      votes: max_votes,
      status: 'assigned'
    }, status: :ok
  end

  # Any authenticated campaign member reads the immutable loot record.
  # Unknown loot returns 404.
  def show_loot
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:campaign_id])
    return unless campaign
    return unless require_participant!(username, campaign)

    loot = load_loot_or_404(campaign)
    return unless loot

    votes = if loot[:status] == 'assigned'
              loot[:final_votes] || {}
            else
              tally = Hash.new(0)
              (loot[:votes] || {}).each_value { |recipient_character_id| tally[recipient_character_id] += 1 }
              tally
            end

    render json: {
      loot_id: loot[:loot_id],
      item_id: loot[:item_id],
      quantity: loot[:quantity],
      status: loot[:status],
      recipient_character_id: loot[:recipient_character_id],
      votes: votes
    }
  end

  # Owner-only (DM) creation of a campaign NPC record: a private agenda
  # paired with a player-visible public_status. Duplicate npc_id values
  # within the campaign return 409.
  def create_play_npc
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_owner!(username, campaign)

    npc_id = params[:npc_id]
    name = params[:name]
    agenda = params[:agenda]
    public_status = params[:public_status]

    return unless require_nonempty_string!(npc_id, 'npc_id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_nonempty_string!(agenda, 'agenda')
    return unless require_nonempty_string!(public_status, 'public_status')

    campaign[:npcs] ||= {}
    if campaign[:npcs].key?(npc_id)
      render json: { error: 'duplicate npc id' }, status: :conflict
      return
    end

    npc = { npc_id: npc_id, name: name, agenda: agenda, public_status: public_status }
    campaign[:npcs][npc_id] = npc
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: npc, status: :created
  end

  # Owner-only (DM) update of an existing NPC's agenda and public_status.
  # Unknown NPCs return 404.
  def update_play_npc_agenda
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_owner!(username, campaign)

    npc = load_play_npc_or_404(campaign)
    return unless npc

    agenda = params[:agenda]
    public_status = params[:public_status]

    return unless require_nonempty_string!(agenda, 'agenda')
    return unless require_nonempty_string!(public_status, 'public_status')

    npc[:agenda] = agenda
    npc[:public_status] = public_status
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: npc, status: :ok
  end

  # Any authenticated campaign member reads an NPC record. The DM sees the
  # private agenda; players see only npc_id/name/public_status.
  def show_play_npc
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_participant!(username, campaign)

    npc = load_play_npc_or_404(campaign)
    return unless npc

    if username == campaign[:owner]
      render json: npc
    else
      render json: { npc_id: npc[:npc_id], name: npc[:name], public_status: npc[:public_status] }
    end
  end

  # Owner-only (DM) append of an attributed dialogue entry to an NPC's
  # history. Duplicate dialogue_ids within the same NPC return 409.
  def create_play_npc_dialogue
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_owner!(username, campaign)

    npc = load_play_npc_or_404(campaign)
    return unless npc

    dialogue_id = params[:dialogue_id]
    speaker = params[:speaker]
    text = params[:text]
    visibility = params[:visibility]

    return unless require_nonempty_string!(dialogue_id, 'dialogue_id')
    return unless require_nonempty_string!(speaker, 'speaker')
    return unless require_nonempty_string!(text, 'text')

    unless visibility == 'public' || visibility == 'private'
      render json: { error: 'invalid visibility' }, status: :bad_request
      return
    end

    npc[:dialogue] ||= []
    if npc[:dialogue].any? { |e| e[:dialogue_id] == dialogue_id }
      render json: { error: 'duplicate dialogue id' }, status: :conflict
      return
    end

    entry = { dialogue_id: dialogue_id, speaker: speaker, text: text, visibility: visibility }
    npc[:dialogue] << entry
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: entry, status: :created
  end

  # Any authenticated campaign member reads an NPC's dialogue history. The
  # DM sees every entry; players see only entries with visibility "public".
  def play_npc_dialogue
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_participant!(username, campaign)

    npc = load_play_npc_or_404(campaign)
    return unless npc

    entries = npc[:dialogue] || []
    entries = entries.select { |e| e[:visibility] == 'public' } if username != campaign[:owner]

    render json: { npc_id: npc[:npc_id], entries: entries }
  end

  # Owner-only (DM) creation of a campaign faction. Duplicate faction_ids
  # within the same campaign return 409.
  def create_play_faction
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_owner!(username, campaign)

    faction_id = params[:faction_id]
    name = params[:name]

    return unless require_nonempty_string!(faction_id, 'faction_id')
    return unless require_nonempty_string!(name, 'name')

    campaign[:factions] ||= {}
    if campaign[:factions].key?(faction_id)
      render json: { error: 'duplicate faction id' }, status: :conflict
      return
    end

    faction = { faction_id: faction_id, name: name }
    campaign[:factions][faction_id] = faction
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: faction, status: :created
  end

  # Owner-only (DM) change to a character's reputation with a faction. The
  # stored total is bounded to [-100, 100]; each accepted change appends an
  # immutable history record.
  def update_faction_reputation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_owner!(username, campaign)

    faction = load_play_faction_or_404(campaign)
    return unless faction

    character_id = params[:character_id]
    delta = params[:delta]
    reason = params[:reason]

    return unless require_nonempty_string!(character_id, 'character_id')

    member = find_member_by_character_id(campaign, character_id)
    if member.nil?
      render json: { error: 'invalid character_id' }, status: :bad_request
      return
    end

    unless valid_integer?(delta) && delta.to_i != 0 && delta.to_i.between?(-25, 25)
      render json: { error: 'invalid delta' }, status: :bad_request
      return
    end
    delta = delta.to_i

    return unless require_nonempty_string!(reason, 'reason')

    faction_id = params[:faction_id]
    campaign[:faction_reputation] ||= {}
    campaign[:faction_reputation][faction_id] ||= {}
    current = campaign[:faction_reputation][faction_id][character_id] || 0
    reputation = (current + delta).clamp(-100, 100)
    campaign[:faction_reputation][faction_id][character_id] = reputation

    entry = { faction_id: faction_id, character_id: character_id, reputation: reputation, delta: delta, reason: reason }
    campaign[:faction_reputation_history] ||= []
    campaign[:faction_reputation_history] << entry
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: entry, status: :created
  end

  # Any authenticated campaign member reads a faction's reputation history.
  # The DM sees every entry; players see only entries for the character
  # they own.
  def faction_reputation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404(params[:id])
    return unless campaign
    return unless require_participant!(username, campaign)

    faction = load_play_faction_or_404(campaign)
    return unless faction

    entries = (campaign[:faction_reputation_history] || []).select { |e| e[:faction_id] == params[:faction_id] }

    if username != campaign[:owner]
      own_character_ids = (campaign[:members] || {}).values.select { |m| (m[:owner] || m[:username]) == username }.map { |m| m[:character_id] }
      entries = entries.select { |e| own_character_ids.include?(e[:character_id]) }
    end

    render json: { faction_id: params[:faction_id], entries: entries }
  end

  # Owner-only (DM) creation of a directed relationship edge between two
  # campaign entities (member character IDs or NPC IDs). Duplicate
  # (source_id, target_id, kind) edges return 409.
  def create_relationship
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    source_id = params[:source_id]
    target_id = params[:target_id]
    kind = params[:kind]
    score = params[:score]

    return unless require_nonempty_string!(source_id, 'source_id')
    return unless require_nonempty_string!(target_id, 'target_id')
    return unless require_nonempty_string!(kind, 'kind')

    if source_id == target_id
      render json: { error: 'invalid self-edge' }, status: :bad_request
      return
    end

    unless valid_integer?(score) && score.to_i.between?(-100, 100)
      render json: { error: 'invalid score' }, status: :bad_request
      return
    end
    score = score.to_i

    entities = campaign_entity_ids(campaign)
    unless entities.include?(source_id) && entities.include?(target_id)
      render json: { error: 'not found' }, status: :not_found
      return
    end

    campaign[:relationships] ||= []
    if campaign[:relationships].any? { |e| e[:source_id] == source_id && e[:target_id] == target_id && e[:kind] == kind }
      render json: { error: 'duplicate relationship' }, status: :conflict
      return
    end

    edge = { source_id: source_id, target_id: target_id, kind: kind, score: score }
    campaign[:relationships] << edge
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: edge, status: :created
  end

  # Owner-only (DM) update of an existing relationship edge's score.
  def update_relationship
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    source_id = params[:source_id]
    target_id = params[:target_id]
    kind = params[:kind]
    score = params[:score]

    edge = (campaign[:relationships] || []).find { |e| e[:source_id] == source_id && e[:target_id] == target_id && e[:kind] == kind }
    if edge.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    unless valid_integer?(score) && score.to_i.between?(-100, 100)
      render json: { error: 'invalid score' }, status: :bad_request
      return
    end

    edge[:score] = score.to_i
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: edge, status: :ok
  end

  # Any authenticated campaign member reads all relationship edges in
  # insertion order.
  def list_relationships
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    render json: { edges: campaign[:relationships] || [] }
  end

  # Owner-only (DM) creation of a campaign clue. Clues may target a single
  # character, the whole party, or be hidden from players entirely. Clue
  # IDs are unique per campaign; duplicates return 409.
  def create_clue
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    clue_id = params[:clue_id]
    text = params[:text]
    audience = params[:audience]
    character_id = params[:character_id]

    return unless require_nonempty_string!(clue_id, 'clue_id')
    return unless require_nonempty_string!(text, 'text')

    unless %w[character party hidden].include?(audience)
      render json: { error: 'invalid audience' }, status: :bad_request
      return
    end

    if audience == 'character'
      unless character_id.is_a?(String) && !character_id.empty?
        render json: { error: 'invalid character_id' }, status: :bad_request
        return
      end
      member = find_member_by_character_id(campaign, character_id)
      if member.nil?
        render json: { error: 'invalid character_id' }, status: :bad_request
        return
      end
    else
      unless character_id.nil?
        render json: { error: 'invalid character_id' }, status: :bad_request
        return
      end
    end

    campaign[:clues] ||= []
    if campaign[:clues].any? { |c| c[:clue_id] == clue_id }
      render json: { error: 'duplicate clue' }, status: :conflict
      return
    end

    clue = { clue_id: clue_id, text: text, audience: audience }
    clue[:character_id] = character_id if audience == 'character'
    campaign[:clues] << clue
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: clue, status: :created
  end

  # Any authenticated campaign member reads clues. The DM sees every clue
  # in insertion order; a player sees party clues and character clues
  # targeted to their own character only.
  def list_clues
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    clues = campaign[:clues] || []

    if username != campaign[:owner]
      own_character_ids = (campaign[:members] || {}).values.select { |m| (m[:owner] || m[:username]) == username }.map { |m| m[:character_id] }
      clues = clues.select do |c|
        c[:audience] == 'party' || (c[:audience] == 'character' && own_character_ids.include?(c[:character_id]))
      end
    end

    render json: { clues: clues }
  end

  # Owner-only (DM) creation of a campaign quest, locked until its
  # dependencies (if any) are completed. Quest IDs are unique per campaign;
  # duplicates return 409.
  def create_play_quest
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    quest_id = params[:quest_id]
    title = params[:title]
    depends_on = params[:depends_on]

    return unless require_nonempty_string!(quest_id, 'quest_id')
    return unless require_nonempty_string!(title, 'title')

    unless depends_on.is_a?(Array) && depends_on.all? { |d| d.is_a?(String) }
      render json: { error: 'invalid depends_on' }, status: :bad_request
      return
    end

    if depends_on.uniq.length != depends_on.length
      render json: { error: 'invalid depends_on' }, status: :bad_request
      return
    end

    if depends_on.include?(quest_id)
      render json: { error: 'invalid depends_on' }, status: :bad_request
      return
    end

    campaign[:quests] ||= []
    existing_ids = campaign[:quests].map { |q| q[:quest_id] }

    if existing_ids.include?(quest_id)
      render json: { error: 'duplicate quest' }, status: :conflict
      return
    end

    unless depends_on.all? { |d| existing_ids.include?(d) }
      render json: { error: 'invalid depends_on' }, status: :bad_request
      return
    end

    quest = { quest_id: quest_id, title: title, depends_on: depends_on, state: 'locked' }
    campaign[:quests] << quest
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: quest, status: :created
  end

  # Owner-only (DM) quest state transition. locked -> active requires every
  # dependency to be completed; active -> completed is always allowed. All
  # other transitions return 409.
  def update_play_quest_state
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    quest = (campaign[:quests] || []).find { |q| q[:quest_id] == params[:quest_id] }
    if quest.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    state = params[:state]
    unless %w[active completed].include?(state)
      render json: { error: 'invalid state' }, status: :bad_request
      return
    end

    if state == 'active'
      unless quest[:state] == 'locked'
        render json: { error: 'invalid transition' }, status: :conflict
        return
      end
      quests_by_id = (campaign[:quests] || []).each_with_object({}) { |q, acc| acc[q[:quest_id]] = q }
      unless quest[:depends_on].all? { |d| quests_by_id[d] && quests_by_id[d][:state] == 'completed' }
        render json: { error: 'invalid transition' }, status: :conflict
        return
      end
    else
      unless quest[:state] == 'active'
        render json: { error: 'invalid transition' }, status: :conflict
        return
      end
    end

    quest[:state] = state
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: quest, status: :ok
  end

  # Any authenticated campaign member reads all quests in creation order.
  def list_play_quests
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    render json: { quests: campaign[:quests] || [] }
  end

  # Owner-only (DM) configuration of a quest's one-time completion rewards.
  # Allowed while the quest is locked or active; completed quests reject
  # reconfiguration with 409.
  def configure_quest_rewards
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    quest = load_play_quest_or_404(campaign)
    return unless quest

    unless %w[locked active].include?(quest[:state])
      render json: { error: 'quest already completed' }, status: :conflict
      return
    end

    xp = params[:xp]
    items = params[:items]

    unless valid_integer?(xp) && xp.to_i >= 0
      render json: { error: 'invalid xp' }, status: :bad_request
      return
    end

    unless items.is_a?(ActionController::Parameters) || items.is_a?(Hash)
      render json: { error: 'invalid items' }, status: :bad_request
      return
    end

    items_hash = {}
    items.each do |item_id, quantity|
      unless INVENTORY_ITEM_IDS.include?(item_id) && valid_integer?(quantity) && quantity.to_i.positive?
        render json: { error: 'invalid items' }, status: :bad_request
        return
      end
      items_hash[item_id] = quantity.to_i
    end

    quest[:rewards] = { xp: xp.to_i, items: items_hash }
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: quest, status: :ok
  end

  # Owner-only (DM) one-time award of a quest's configured rewards to every
  # campaign member. The quest must be completed and have rewards configured;
  # a repeat award returns 409 and makes no changes.
  def award_quest_rewards
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    quest = load_play_quest_or_404(campaign)
    return unless quest

    rewards = quest[:rewards]
    if quest[:state] != 'completed' || rewards.nil? || rewards[:awarded]
      render json: { error: 'invalid state' }, status: :conflict
      return
    end

    (campaign[:members] || {}).each_value do |member|
      character_id = member[:character_id]
      next unless character_id

      grants = (campaign[:quest_reward_grants] ||= {})
      grant = (grants[character_id] ||= { xp: 0, items: {} })
      grant[:xp] += rewards[:xp]
      member[:inventory] ||= {}
      rewards[:items].each do |item_id, quantity|
        grant[:items][item_id] = (grant[:items][item_id] || 0) + quantity
        member[:inventory][item_id] = (member[:inventory][item_id] || 0) + quantity
      end
    end

    rewards[:awarded] = true
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      quest_id: quest[:quest_id],
      awarded: true,
      xp: rewards[:xp],
      items: rewards[:items]
    }, status: :created
  end

  # Any authenticated campaign member reads cumulative quest reward grants
  # for a character.
  def character_quest_rewards
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    character_id = params[:character_id]
    member = find_member_by_character_id(campaign, character_id)
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    grant = (campaign[:quest_reward_grants] || {})[character_id] || { xp: 0, items: {} }

    render json: { character_id: character_id, xp: grant[:xp], items: grant[:items] }
  end

  # Owner-only (DM) scheduling of a deterministic world event to resolve on a
  # future (or current) campaign turn. Event IDs are unique per campaign;
  # duplicates return 409.
  def create_world_event
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    event_id = params[:event_id]
    turn_number = params[:turn_number]
    title = params[:title]
    text = params[:text]

    return unless require_nonempty_string!(event_id, 'event_id')
    return unless require_nonempty_string!(title, 'title')
    return unless require_nonempty_string!(text, 'text')
    return unless require_valid_integer!(turn_number, 'turn_number')

    current_turn = campaign[:turn_number] || 1
    if turn_number.to_i < current_turn
      render json: { error: 'invalid turn_number' }, status: :bad_request
      return
    end

    campaign[:world_events] ||= []
    if campaign[:world_events].any? { |e| e[:event_id] == event_id }
      render json: { error: 'duplicate event' }, status: :conflict
      return
    end

    world_event = {
      event_id: event_id,
      turn_number: turn_number.to_i,
      title: title,
      text: text,
      status: 'scheduled'
    }
    campaign[:world_events] << world_event
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: world_event, status: :created
  end

  # Owner-only (DM) resolution of a scheduled world event. Requires the
  # campaign's current turn to exactly match the event's turn_number. Already
  # resolved events return 409 without changing the stored resolution.
  def resolve_world_event
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    world_event = (campaign[:world_events] || []).find { |e| e[:event_id] == params[:event_id] }
    if world_event.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    text = params[:text]
    return unless require_nonempty_string!(text, 'text')

    if world_event[:status] == 'resolved'
      render json: { error: 'already resolved' }, status: :conflict
      return
    end

    current_turn = campaign[:turn_number] || 1
    if current_turn != world_event[:turn_number]
      render json: { error: 'invalid turn' }, status: :conflict
      return
    end

    world_event[:status] = 'resolved'
    world_event[:resolution] = { turn_number: world_event[:turn_number], text: text }
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: world_event, status: :created
  end

  # Any authenticated campaign member reads world events ordered by
  # turn_number ascending, then creation order.
  def list_world_events
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    events = (campaign[:world_events] || []).each_with_index.sort_by { |e, i| [e[:turn_number], i] }.map(&:first)

    render json: { events: events }
  end

  SEASON_OFFSETS = { 'spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3 }.freeze
  WEATHER_BY_OFFSET = { 0 => 'clear', 1 => 'rain', 2 => 'wind', 3 => 'snow' }.freeze

  # Owner-only (DM) one-time initialization of a campaign's calendar.
  def create_calendar
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    day = params[:day]
    season = params[:season]

    return unless require_valid_integer!(day, 'day')
    if day.to_i < 1
      render json: { error: 'invalid day' }, status: :bad_request
      return
    end
    unless SEASON_OFFSETS.key?(season)
      render json: { error: 'invalid season' }, status: :bad_request
      return
    end

    if campaign[:calendar]
      render json: { error: 'already initialized' }, status: :conflict
      return
    end

    campaign[:calendar] = { day: day.to_i, season: season }
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: calendar_json(campaign[:calendar]), status: :created
  end

  # Any authenticated campaign member reads the current calendar state.
  def show_calendar
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    if campaign[:calendar].nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    render json: calendar_json(campaign[:calendar])
  end

  # Owner-only (DM) bounded advance of the campaign's calendar day.
  def advance_calendar
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    if campaign[:calendar].nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    days = params[:days]
    return unless require_valid_integer!(days, 'days')
    unless (1..30).cover?(days.to_i)
      render json: { error: 'invalid days' }, status: :bad_request
      return
    end

    campaign[:calendar][:day] += days.to_i
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: calendar_json(campaign[:calendar])
  end

  SETTLEMENT_AVAILABILITIES = %w[open limited closed].freeze

  # Owner-only (DM) creation of a campaign settlement. Settlement IDs are
  # unique per campaign; duplicates return 409.
  def create_settlement
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    settlement_id = params[:settlement_id]
    return unless require_nonempty_string!(settlement_id, 'settlement_id')

    services = normalize_settlement_services(params[:services])
    return unless require_valid_settlement_fields!(params[:name], services, params[:availability])

    campaign[:settlements] ||= []
    if campaign[:settlements].any? { |s| s[:settlement_id] == settlement_id }
      render json: { error: 'duplicate settlement' }, status: :conflict
      return
    end

    settlement = {
      settlement_id: settlement_id,
      name: params[:name],
      services: services,
      availability: params[:availability],
      discovered_by: []
    }
    campaign[:settlements] << settlement
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: settlement, status: :created
  end

  # Owner-only (DM) replacement of a settlement's name, services, and
  # availability. discovered_by order is preserved.
  def update_settlement
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    settlement = (campaign[:settlements] || []).find { |s| s[:settlement_id] == params[:settlement_id] }
    if settlement.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    services = normalize_settlement_services(params[:services])
    return unless require_valid_settlement_fields!(params[:name], services, params[:availability])

    settlement[:name] = params[:name]
    settlement[:services] = services
    settlement[:availability] = params[:availability]
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: settlement
  end

  # Joined-player-only discovery of a settlement by their own character.
  # Idempotent: repeat discoveries do not append duplicates.
  def discover_settlement
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_player_member!(username, campaign)

    settlement = (campaign[:settlements] || []).find { |s| s[:settlement_id] == params[:settlement_id] }
    if settlement.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    character_id = campaign[:members][username][:character_id]
    settlement[:discovered_by] ||= []

    if settlement[:discovered_by].include?(character_id)
      render json: settlement_player_json(settlement, character_id)
      return
    end

    settlement[:discovered_by] << character_id
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: settlement_player_json(settlement, character_id), status: :created
  end

  # The DM sees every settlement with full discovered_by lists. A player
  # sees only settlements discovered by their own character, with
  # discovered_by limited to their own character ID.
  def list_settlements
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    settlements = campaign[:settlements] || []

    if username == campaign[:owner]
      render json: { settlements: settlements }
      return
    end

    character_id = campaign[:members][username][:character_id]
    filtered = settlements.select { |s| (s[:discovered_by] || []).include?(character_id) }
                          .map { |s| settlement_player_json(s, character_id) }

    render json: { settlements: filtered }
  end

  # Owner-only (DM) creation of a settlement shop. Shop IDs are unique per
  # settlement.
  def create_shop
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    settlement = load_settlement_or_404(campaign)
    return unless settlement

    shop_id = params[:shop_id]
    name = params[:name]
    stock = params[:stock]
    buy_price = params[:buy_price]
    sell_price = params[:sell_price]

    return unless require_nonempty_string!(shop_id, 'shop_id')
    normalized_stock = require_valid_shop_fields!(name, stock, buy_price, sell_price)
    return if normalized_stock.nil?

    settlement[:shops] ||= []
    if settlement[:shops].any? { |s| s[:shop_id] == shop_id }
      render json: { error: 'duplicate shop' }, status: :conflict
      return
    end

    shop = {
      shop_id: shop_id,
      name: name,
      stock: normalized_stock,
      buy_price: buy_price.to_i,
      sell_price: sell_price.to_i
    }
    settlement[:shops] << shop
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: shop_json(shop), status: :created
  end

  # The DM may always read a shop. A player may read a shop only after
  # their character has discovered the containing settlement.
  def show_shop
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    settlement = load_settlement_or_404(campaign)
    return unless settlement

    if username != campaign[:owner]
      character_id = campaign[:members][username][:character_id]
      unless (settlement[:discovered_by] || []).include?(character_id)
        render json: { error: 'not found' }, status: :not_found
        return
      end
    end

    shop = load_shop_or_404(settlement)
    return unless shop

    render json: shop_json(shop)
  end

  # Only the owning player of character_id may buy from a shop. Requires
  # sufficient stock and gold; mutates atomically or not at all.
  def buy_from_shop
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    settlement = load_settlement_or_404(campaign)
    return unless settlement

    shop = load_shop_or_404(settlement)
    return unless shop

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end
    return unless require_character_owner!(member, username)

    item_id = params[:item_id]
    quantity = params[:quantity]

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(quantity, 'quantity')
    quantity = quantity.to_i

    unless quantity.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    stock = shop[:stock][item_id] || 0
    cost = shop[:buy_price] * quantity
    member[:gold] ||= 0

    if stock < quantity || member[:gold] < cost
      render json: { error: 'insufficient stock or funds' }, status: :conflict
      return
    end

    shop[:stock][item_id] = stock - quantity
    member[:gold] -= cost
    member[:inventory] ||= {}
    member[:inventory][item_id] = (member[:inventory][item_id] || 0) + quantity

    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      character_id: params[:character_id],
      item_id: item_id,
      quantity: quantity,
      gold: member[:gold],
      stock: shop[:stock][item_id]
    }
  end

  # Only the owning player of character_id may sell to a shop. Requires
  # sufficient held inventory; mutates atomically or not at all.
  def sell_to_shop
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    settlement = load_settlement_or_404(campaign)
    return unless settlement

    shop = load_shop_or_404(settlement)
    return unless shop

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end
    return unless require_character_owner!(member, username)

    item_id = params[:item_id]
    quantity = params[:quantity]

    unless INVENTORY_ITEM_IDS.include?(item_id)
      render json: { error: 'invalid item_id' }, status: :bad_request
      return
    end

    return unless require_valid_integer!(quantity, 'quantity')
    quantity = quantity.to_i

    unless quantity.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    member[:inventory] ||= {}
    held = member[:inventory][item_id] || 0

    if held < quantity
      render json: { error: 'insufficient inventory' }, status: :conflict
      return
    end

    member[:inventory][item_id] = held - quantity
    member[:gold] ||= 0
    member[:gold] += shop[:sell_price] * quantity
    shop[:stock] ||= {}
    shop[:stock][item_id] = (shop[:stock][item_id] || 0) + quantity

    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      character_id: params[:character_id],
      item_id: item_id,
      quantity: quantity,
      gold: member[:gold],
      stock: shop[:stock][item_id]
    }
  end

  # Owner-only (DM) creation of a campaign crafting recipe. Recipe IDs are
  # unique per campaign.
  def create_recipe
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    recipe_id = params[:recipe_id]
    name = params[:name]
    ingredients = params[:ingredients]
    output_item = params[:output_item]
    output_quantity = params[:output_quantity]

    return unless require_nonempty_string!(recipe_id, 'recipe_id')
    return unless require_nonempty_string!(name, 'name')
    normalized_ingredients = require_valid_recipe_fields!(ingredients, output_item, output_quantity)
    return if normalized_ingredients.nil?

    campaign[:recipes] ||= []
    if campaign[:recipes].any? { |r| r[:recipe_id] == recipe_id }
      render json: { error: 'duplicate recipe' }, status: :conflict
      return
    end

    recipe = {
      recipe_id: recipe_id,
      name: name,
      ingredients: normalized_ingredients,
      output_item: output_item,
      output_quantity: output_quantity.to_i
    }
    campaign[:recipes] << recipe
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: recipe_json(recipe), status: :created
  end

  # Any authenticated campaign member (owner or party member) may list
  # recipes, in creation order.
  def list_recipes
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    recipes = (campaign[:recipes] || []).map { |r| recipe_json(r) }
    render json: { recipes: recipes }
  end

  # Only the owning player of character_id may craft a recipe. Requires
  # holding at least every required ingredient quantity; mutates atomically
  # or not at all.
  def craft_recipe
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    recipe = load_recipe_or_404(campaign)
    return unless recipe

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end
    return unless require_character_owner!(member, username)

    member[:inventory] ||= {}
    insufficient = recipe[:ingredients].any? { |item_id, quantity| (member[:inventory][item_id] || 0) < quantity }
    if insufficient
      render json: { error: 'insufficient ingredients' }, status: :conflict
      return
    end

    recipe[:ingredients].each do |item_id, quantity|
      member[:inventory][item_id] -= quantity
    end
    output_item = recipe[:output_item]
    member[:inventory][output_item] = (member[:inventory][output_item] || 0) + recipe[:output_quantity]

    PLAY_CAMPAIGNS.persist(params[:id])

    render json: {
      character_id: params[:character_id],
      recipe_id: recipe[:recipe_id],
      output_item: output_item,
      output_quantity: recipe[:output_quantity]
    }, status: :created
  end

  # Owner-only (DM) creation of a campaign downtime activity. Activity IDs
  # are unique per campaign.
  def create_downtime_activity
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_owner!(username, campaign)

    activity_id = params[:activity_id]
    name = params[:name]
    cycles_required = params[:cycles_required]

    return unless require_nonempty_string!(activity_id, 'activity_id')
    return unless require_nonempty_string!(name, 'name')
    return unless require_valid_cycles_required!(cycles_required)

    campaign[:downtime_activities] ||= []
    if campaign[:downtime_activities].any? { |a| a[:activity_id] == activity_id }
      render json: { error: 'duplicate activity' }, status: :conflict
      return
    end

    activity = {
      activity_id: activity_id,
      name: name,
      cycles_required: cycles_required.to_i
    }
    campaign[:downtime_activities] << activity
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: downtime_activity_json(activity), status: :created
  end

  # Only the owning player of character_id may allocate a downtime
  # activity. Duplicate allocations for the same character/activity pair
  # are rejected.
  def create_downtime_allocation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end
    return unless require_character_owner!(member, username)

    activity = load_downtime_activity_or_404(campaign)
    return unless activity

    activity_id = params[:activity_id]
    member[:downtime_allocations] ||= {}
    if member[:downtime_allocations].key?(activity_id)
      render json: { error: 'duplicate allocation' }, status: :conflict
      return
    end

    allocation = { activity_id: activity_id, cycles_completed: 0, completions: 0 }
    member[:downtime_allocations][activity_id] = allocation
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: downtime_allocation_json(params[:character_id], allocation), status: :created
  end

  # Only the owning player of character_id may progress an allocation.
  # Increments cycles_completed; on reaching cycles_required, resets to 0
  # and increments completions so the activity can recur.
  def progress_downtime_allocation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end
    return unless require_character_owner!(member, username)

    activity = load_downtime_activity_or_404(campaign)
    return unless activity

    allocation = load_downtime_allocation_or_404(member)
    return unless allocation

    allocation[:cycles_completed] += 1
    if allocation[:cycles_completed] >= activity[:cycles_required]
      allocation[:cycles_completed] = 0
      allocation[:completions] += 1
    end
    PLAY_CAMPAIGNS.persist(params[:id])

    render json: downtime_allocation_json(params[:character_id], allocation)
  end

  # Any authenticated campaign member may read an allocation.
  def show_downtime_allocation
    username = authenticate_play_actor!
    return if username.nil?

    campaign = load_campaign_or_404
    return unless campaign
    return unless require_participant!(username, campaign)

    member = find_member_by_character_id(campaign, params[:character_id])
    if member.nil?
      render json: { error: 'not found' }, status: :not_found
      return
    end

    activity = load_downtime_activity_or_404(campaign)
    return unless activity

    allocation = load_downtime_allocation_or_404(member)
    return unless allocation

    render json: downtime_allocation_json(params[:character_id], allocation)
  end

  private

  # Builds the public calendar representation with deterministic weather.
  def calendar_json(calendar)
    offset = SEASON_OFFSETS[calendar[:season]]
    weather = WEATHER_BY_OFFSET[(calendar[:day] + offset) % 4]
    { day: calendar[:day], season: calendar[:season], weather: weather }
  end

  # Trims surrounding whitespace from each service for storage/response.
  # Returns the raw value unchanged if it isn't an array, so validation
  # can reject it uniformly.
  def normalize_settlement_services(services)
    return services unless services.is_a?(Array)

    services.map { |s| s.is_a?(String) ? s.strip : s }
  end

  # Shared validation for settlement create/update: name must be a
  # nonempty string, services a nonempty array of nonempty strings with
  # unique normalized values, and availability one of the allowed states.
  def require_valid_settlement_fields!(name, services, availability)
    return false unless require_nonempty_string!(name, 'name')

    unless services.is_a?(Array) && !services.empty? && services.all? { |s| s.is_a?(String) && !s.empty? }
      render json: { error: 'invalid services' }, status: :bad_request
      return false
    end

    if services.uniq.length != services.length
      render json: { error: 'invalid services' }, status: :bad_request
      return false
    end

    unless SETTLEMENT_AVAILABILITIES.include?(availability)
      render json: { error: 'invalid availability' }, status: :bad_request
      return false
    end

    true
  end

  # Builds a player-filtered settlement representation: discovered_by
  # limited to the requesting player's own character ID.
  def settlement_player_json(settlement, character_id)
    {
      settlement_id: settlement[:settlement_id],
      name: settlement[:name],
      services: settlement[:services],
      availability: settlement[:availability],
      discovered_by: [character_id]
    }
  end

  # Looks up the given settlement by params[:settlement_id] within a
  # campaign already loaded via load_campaign_or_404, rendering 404 and
  # returning nil on a miss so callers can `return unless settlement`.
  def load_settlement_or_404(campaign)
    settlement = (campaign[:settlements] || []).find { |s| s[:settlement_id] == params[:settlement_id] }
    render json: { error: 'not found' }, status: :not_found if settlement.nil?
    settlement
  end

  # Looks up the given shop by params[:shop_id] within a settlement already
  # loaded via load_settlement_or_404, rendering 404 and returning nil on a
  # miss so callers can `return unless shop`.
  def load_shop_or_404(settlement)
    shop = (settlement[:shops] || []).find { |s| s[:shop_id] == params[:shop_id] }
    render json: { error: 'not found' }, status: :not_found if shop.nil?
    shop
  end

  # Validates and normalizes shop creation fields: name nonempty, stock a
  # nonempty object of valid catalog item IDs to positive integer
  # quantities, buy_price a positive integer, sell_price a nonnegative
  # integer. Returns the normalized stock hash (String keys, Integer
  # values) on success, or nil after rendering an error.
  def require_valid_shop_fields!(name, stock, buy_price, sell_price)
    return nil unless require_nonempty_string!(name, 'name')

    unless stock.is_a?(ActionController::Parameters) || stock.is_a?(Hash)
      render json: { error: 'invalid stock' }, status: :bad_request
      return nil
    end

    stock_hash = {}
    stock.each do |item_id, quantity|
      unless INVENTORY_ITEM_IDS.include?(item_id) && valid_integer?(quantity) && quantity.to_i.positive?
        render json: { error: 'invalid stock' }, status: :bad_request
        return nil
      end
      stock_hash[item_id] = quantity.to_i
    end

    if stock_hash.empty?
      render json: { error: 'invalid stock' }, status: :bad_request
      return nil
    end

    unless valid_integer?(buy_price) && buy_price.to_i.positive?
      render json: { error: 'invalid buy_price' }, status: :bad_request
      return nil
    end

    unless valid_integer?(sell_price) && sell_price.to_i >= 0
      render json: { error: 'invalid sell_price' }, status: :bad_request
      return nil
    end

    stock_hash
  end

  # Builds the exact public shop representation.
  def shop_json(shop)
    {
      shop_id: shop[:shop_id],
      name: shop[:name],
      stock: shop[:stock],
      buy_price: shop[:buy_price],
      sell_price: shop[:sell_price]
    }
  end

  # Looks up the given recipe by params[:recipe_id] within a campaign
  # already loaded via load_campaign_or_404, rendering 404 and returning
  # nil on a miss so callers can `return unless recipe`.
  def load_recipe_or_404(campaign)
    recipe = (campaign[:recipes] || []).find { |r| r[:recipe_id] == params[:recipe_id] }
    render json: { error: 'not found' }, status: :not_found if recipe.nil?
    recipe
  end

  # Validates recipe creation fields: ingredients a nonempty object of
  # valid catalog item IDs to positive integer quantities, output_item a
  # valid catalog item ID, output_quantity a positive integer. Returns the
  # normalized ingredients hash (String keys, Integer values) on success,
  # or nil after rendering an error.
  def require_valid_recipe_fields!(ingredients, output_item, output_quantity)
    unless ingredients.is_a?(ActionController::Parameters) || ingredients.is_a?(Hash)
      render json: { error: 'invalid ingredients' }, status: :bad_request
      return nil
    end

    ingredients_hash = {}
    ingredients.each do |item_id, quantity|
      unless INVENTORY_ITEM_IDS.include?(item_id) && valid_integer?(quantity) && quantity.to_i.positive?
        render json: { error: 'invalid ingredients' }, status: :bad_request
        return nil
      end
      ingredients_hash[item_id] = quantity.to_i
    end

    if ingredients_hash.empty?
      render json: { error: 'invalid ingredients' }, status: :bad_request
      return nil
    end

    unless INVENTORY_ITEM_IDS.include?(output_item)
      render json: { error: 'invalid output_item' }, status: :bad_request
      return nil
    end

    unless valid_integer?(output_quantity) && output_quantity.to_i.positive?
      render json: { error: 'invalid output_quantity' }, status: :bad_request
      return nil
    end

    ingredients_hash
  end

  # Builds the exact public recipe representation.
  def recipe_json(recipe)
    {
      recipe_id: recipe[:recipe_id],
      name: recipe[:name],
      ingredients: recipe[:ingredients],
      output_item: recipe[:output_item],
      output_quantity: recipe[:output_quantity]
    }
  end

  # Validates cycles_required is an integer from 1 through 10.
  def require_valid_cycles_required!(cycles_required)
    unless valid_integer?(cycles_required) && (1..10).cover?(cycles_required.to_i)
      render json: { error: 'invalid cycles_required' }, status: :bad_request
      return false
    end

    true
  end

  # Looks up the given downtime activity by params[:activity_id] within a
  # campaign already loaded via load_campaign_or_404, rendering 404 and
  # returning nil on a miss so callers can `return unless activity`.
  def load_downtime_activity_or_404(campaign)
    activity = (campaign[:downtime_activities] || []).find { |a| a[:activity_id] == params[:activity_id] }
    render json: { error: 'not found' }, status: :not_found if activity.nil?
    activity
  end

  # Looks up the given downtime allocation by params[:activity_id] within a
  # member already resolved from find_member_by_character_id, rendering 404
  # and returning nil on a miss so callers can `return unless allocation`.
  def load_downtime_allocation_or_404(member)
    allocation = (member[:downtime_allocations] || {})[params[:activity_id]]
    render json: { error: 'not found' }, status: :not_found if allocation.nil?
    allocation
  end

  # Builds the exact public downtime activity representation.
  def downtime_activity_json(activity)
    {
      activity_id: activity[:activity_id],
      name: activity[:name],
      cycles_required: activity[:cycles_required]
    }
  end

  # Builds the exact public downtime allocation representation.
  def downtime_allocation_json(character_id, allocation)
    {
      character_id: character_id,
      activity_id: allocation[:activity_id],
      cycles_completed: allocation[:cycles_completed],
      completions: allocation[:completions]
    }
  end

  # The set of valid relationship endpoint IDs for a campaign: current
  # party member character IDs and NPC IDs.
  def campaign_entity_ids(campaign)
    character_ids = (campaign[:members] || {}).values.map { |m| m[:character_id] }
    npc_ids = (campaign[:npcs] || {}).keys
    character_ids + npc_ids
  end

  # Looks up the given faction by params[:faction_id] within a campaign
  # already loaded via load_campaign_or_404, rendering 404 and returning
  # nil on a miss so callers can `return unless faction`.
  def load_play_faction_or_404(campaign)
    faction = (campaign[:factions] || {})[params[:faction_id]]
    render json: { error: 'not found' }, status: :not_found if faction.nil?
    faction
  end

  # Looks up the given NPC by params[:npc_id] within a campaign already
  # loaded via load_campaign_or_404, rendering 404 and returning nil on a
  # miss so callers can `return unless npc`.
  def load_play_npc_or_404(campaign)
    npc = (campaign[:npcs] || {})[params[:npc_id]]
    render json: { error: 'not found' }, status: :not_found if npc.nil?
    npc
  end

  # Looks up the given quest by params[:quest_id] within a campaign already
  # loaded via load_campaign_or_404, rendering 404 and returning nil on a
  # miss so callers can `return unless quest`.
  def load_play_quest_or_404(campaign)
    quest = (campaign[:quests] || []).find { |q| q[:quest_id] == params[:quest_id] }
    render json: { error: 'not found' }, status: :not_found if quest.nil?
    quest
  end

  # Looks up PLAY_CAMPAIGNS by the given campaign id (defaults to
  # params[:id]), rendering 404 and returning nil on a miss so callers can
  # `return unless campaign`.
  def load_campaign_or_404(campaign_id = params[:id])
    campaign = PLAY_CAMPAIGNS[campaign_id]
    render json: { error: 'not found' }, status: :not_found if campaign.nil?
    campaign
  end

  def require_owner_username!(username, expected)
    return true if username == expected

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  def require_owner!(username, campaign)
    return true if username == campaign[:owner]

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  # A "participant" is the campaign owner or any current party member.
  def require_participant!(username, campaign)
    members = campaign[:members] || {}
    return true if username == campaign[:owner] || members.key?(username)

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  # True for the campaign owner, or an active delegate granted the given
  # power (e.g. 'narrate').
  def require_owner_or_delegate!(username, campaign, power)
    return true if username == campaign[:owner]

    delegation = (campaign[:delegations] || {})[username]
    return true if delegation && delegation[:active] && delegation[:powers].include?(power)

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  def valid_delegation_powers?(powers)
    return false unless powers.is_a?(Array) && !powers.empty?
    return false unless powers.uniq.length == powers.length

    powers.all? { |p| VALID_DELEGATION_POWERS.include?(p) }
  end

  # Appends an immutable grant/revoke entry to the campaign's delegation
  # audit trail.
  def append_delegation_audit(campaign, **fields)
    campaign[:delegation_audit] ||= []
    campaign[:delegation_audit] << fields
  end

  # A campaign player is a joined party member (role player, per
  # join_play_campaign). The DM/owner is not a player.
  def require_player_member!(username, campaign)
    members = campaign[:members] || {}
    return true if members.key?(username)

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  def require_nonempty_string!(value, field)
    return true if value.is_a?(String) && !value.empty?

    render json: { error: "invalid #{field}" }, status: :bad_request
    false
  end

  def valid_tag_array?(tags, allow_empty:)
    return false unless tags.is_a?(Array)
    return false if tags.empty? && !allow_empty

    tags.all? { |t| t.is_a?(String) && !t.empty? } && tags.uniq.length == tags.length
  end

  def require_valid_integer!(value, field)
    return true if valid_integer?(value)

    render json: { error: "invalid #{field}" }, status: :bad_request
    false
  end

  # Looks up the given encounter by params[:encounter_id] within a campaign
  # already loaded via load_campaign_or_404, rendering 404 and returning nil
  # on a miss so callers can `return unless encounter`.
  def load_encounter_or_404(campaign)
    encounter = (campaign[:encounters] || {})[params[:encounter_id]]
    render json: { error: 'not found' }, status: :not_found if encounter.nil?
    encounter
  end

  # Looks up the party member owning params[:char_id] within a campaign
  # already loaded via load_campaign_or_404, rendering 404 and returning nil
  # on a miss so callers can `return unless member`.
  def load_character_member_or_404(campaign)
    member = find_member_by_character_id(campaign, params[:char_id])
    render json: { error: 'not found' }, status: :not_found if member.nil?
    member
  end

  # Defaults a character's owner to its original claiming username (for
  # characters created before ownership could be reassigned), then requires
  # the acting username to match it. Renders 403 and returns false otherwise.
  def require_character_owner!(member, username)
    member[:owner] ||= member[:username]
    return true if member[:owner] == username

    render json: { error: 'forbidden' }, status: :forbidden
    false
  end

  # Builds the encounter's deterministic initiative order from its current
  # combatants/monsters: highest initiative first, ties broken by name.
  # Also initializes round/turn_index. Safe to call repeatedly; combatants
  # or monsters bound after the initial build are appended (sorted among
  # themselves) without disturbing already-ordered entries or the current
  # turn position.
  def ensure_encounter_turn_order!(campaign, encounter)
    encounter[:turn_order] ||= []
    encounter[:round] ||= 1
    encounter[:turn_index] ||= 0

    known_target_ids = encounter[:turn_order].map { |e| e[:target_id] }

    new_entries = []
    (encounter[:combatants] || []).each do |c|
      next if known_target_ids.include?(c[:member])
      new_entries << { name: c[:name], kind: 'player', initiative: c[:initiative], member: c[:member], target_id: c[:member] }
    end
    (encounter[:monsters] || {}).each do |monster_id, m|
      next if known_target_ids.include?(monster_id)
      new_entries << { name: m[:name], kind: 'monster', initiative: m[:initiative], member: nil, target_id: monster_id }
    end

    return if new_entries.empty?

    new_entries.sort! do |a, b|
      cmp = b[:initiative] <=> a[:initiative]
      cmp = a[:name] <=> b[:name] if cmp == 0
      cmp
    end

    encounter[:turn_order].concat(new_entries)
    PLAY_CAMPAIGNS.persist(params[:campaign_id])
  end

  def encounter_turn_json(encounter)
    active = encounter[:turn_order][encounter[:turn_index]]
    {
      round: encounter[:round],
      turn_index: encounter[:turn_index],
      active: { name: active[:name], kind: active[:kind], initiative: active[:initiative] }
    }
  end

  # Maps the encounter's initiative order into its public representation.
  def encounter_order_json(encounter)
    encounter[:turn_order].map do |e|
      { name: e[:name], kind: e[:kind], initiative: e[:initiative], target_id: e[:target_id] }
    end
  end

  # Full encounter state for the status endpoint: round/turn_index/active
  # plus the initiative order and a target_id-keyed conditions map.
  def encounter_status_json(encounter)
    active = encounter[:turn_order][encounter[:turn_index]]
    order = encounter_order_json(encounter)
    conditions = (encounter[:conditions] || {}).each_with_object({}) do |(target, list), acc|
      acc[target] = list.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    end
    {
      round: encounter[:round],
      turn_index: encounter[:turn_index],
      active: { name: active[:name], kind: active[:kind], initiative: active[:initiative] },
      order: order,
      conditions: conditions
    }
  end

  # True if the target id refers to a monster or bound party member in the
  # encounter.
  def combat_target_exists?(encounter, target)
    return true if (encounter[:monsters] || {}).key?(target)

    (encounter[:combatants] || []).any? { |c| c[:member] == target }
  end

  # Decrements remaining_rounds for every condition on the given target
  # (called at the start of that target's turn) and drops any that expire.
  def decrement_conditions_for_target!(encounter, target_id)
    return if target_id.nil?

    conditions = (encounter[:conditions] || {})[target_id]
    return if conditions.nil?

    conditions.each { |c| c[:remaining_rounds] -= 1 }
    conditions.reject! { |c| c[:remaining_rounds] <= 0 }
  end

  # Resolves a damage/heal target id to its hp-bearing hash: either a
  # monster entry keyed by monster_id, or the campaign member backing a
  # bound party combatant. Returns nil if the target is not found in the
  # encounter.
  def resolve_combat_target(campaign, encounter, target)
    monsters = encounter[:monsters] || {}
    return monsters[target] if monsters.key?(target)

    combatants = encounter[:combatants] || []
    if combatants.any? { |c| c[:member] == target }
      member = (campaign[:members] || {})[target]
      if member
        member[:hp_max] ||= 20
        member[:hp_current] ||= 20
        return member
      end
    end

    nil
  end

  # Looks up the given loot record by params[:loot_id] within a campaign
  # already loaded via load_campaign_or_404, rendering 404 and returning nil
  # on a miss so callers can `return unless loot`.
  def load_loot_or_404(campaign)
    loot = (campaign[:loot] || {})[params[:loot_id]]
    render json: { error: 'not found' }, status: :not_found if loot.nil?
    loot
  end

  # Finds the campaign member backing a given character_id.
  def find_member_by_character_id(campaign, character_id)
    (campaign[:members] || {}).values.find { |m| m[:character_id] == character_id }
  end

  # Appends a sequenced event to the campaign's event log and returns it.
  # Callers are responsible for persisting the campaign afterward.
  def append_event(campaign, **fields)
    campaign[:events] ||= []
    event = { sequence: campaign[:events].length + 1 }.merge(fields)
    campaign[:events] << event
    event
  end
end
