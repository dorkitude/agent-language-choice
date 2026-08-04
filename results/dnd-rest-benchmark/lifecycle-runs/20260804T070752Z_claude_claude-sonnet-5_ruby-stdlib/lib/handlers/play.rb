# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative '../game_rules'
require_relative '../service_state'

module Handlers
  # Protected campaign-play surface under /v1/play. Routes here are
  # authenticated by Handlers::Auth.authenticate before the handler runs;
  # `actor` is the resulting {username:, role:} hash.
  module Play
    module_function

    def find_play_campaign(id)
      row = Database.query("SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count, current_scene_id, current_location_id, combat_phase, pre_combat_actor, turn_phase FROM play_campaigns WHERE id = #{Database.escape(id)};").first
      raise HttpError.new(404, 'unknown campaign id') unless row

      row
    end

    def member?(campaign_id, username)
      !Database.query(<<~SQL).empty?
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(username)};
      SQL
    end

    # True when `actor` is the dm who owns `campaign`. Most write routes
    # below are dm-owner-only; read routes use this to vary response shape
    # (e.g. whether dm_notes is included) instead of rejecting the request.
    def owner?(campaign, actor)
      campaign['owner'] == actor[:username]
    end

    # Raises 403 with `message` unless `actor` is the owning dm. Centralizes
    # the ownership gate reused across nearly every dm-only play route.
    def require_owner!(campaign, actor, message)
      raise HttpError.new(403, message) unless owner?(campaign, actor)
    end

    def create_campaign(actor, body)
      raise HttpError.new(403, 'only a dm may create a play campaign') unless actor[:role] == 'dm'

      id = body['id']
      name = body['name']
      max_players = body['max_players']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'max_players must be an integer') unless max_players.is_a?(Integer)
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM play_campaigns WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO play_campaigns (id, name, owner, status, max_players)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(name)},
          #{Database.escape(actor[:username])},
          'lobby',
          #{Database.int(max_players)}
        );
      SQL

      [201, { id: id, name: name, owner: actor[:username], status: 'lobby', max_players: max_players }]
    end

    def join_campaign(actor, campaign_id, body)
      raise HttpError.new(403, 'only a player may join a campaign') unless actor[:role] == 'player'

      campaign = find_play_campaign(campaign_id)

      character_id = body['character_id']
      name = body['name']
      klass = body['class']

      raise HttpError.new(400, 'character_id must be a string') unless character_id.is_a?(String) && !character_id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'class must be a string') unless klass.is_a?(String) && !klass.empty?

      existing_membership = Database.query(<<~SQL).first
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
      SQL
      raise HttpError.new(409, 'player already has a membership in this campaign') if existing_membership

      duplicate_character = Database.query("SELECT character_id FROM play_members WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};").first
      raise HttpError.new(409, 'character_id already in use') if duplicate_character

      member_count = Database.query("SELECT COUNT(*) AS n FROM play_members WHERE campaign_id = #{Database.escape(campaign_id)};").first['n'].to_i
      raise HttpError.new(409, 'campaign party is full') if member_count >= campaign['max_players'].to_i

      Database.exec(<<~SQL)
        INSERT INTO play_members (campaign_id, username, character_id, name, class, owner)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(actor[:username])},
          #{Database.escape(character_id)},
          #{Database.escape(name)},
          #{Database.escape(klass)},
          #{Database.escape(actor[:username])}
        );
      SQL

      [201, { username: actor[:username], character_id: character_id, name: name, class: klass }]
    end

    def start_campaign(actor, campaign_id, _body)
      raise HttpError.new(403, 'only a dm may start a play campaign') unless actor[:role] == 'dm'

      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may start this campaign')
      raise HttpError.new(409, 'campaign is not in lobby status') unless campaign['status'] == 'lobby'

      first_member = Database.query(<<~SQL).first
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY rowid ASC LIMIT 1;
      SQL
      member_count = Database.query("SELECT COUNT(*) AS n FROM play_members WHERE campaign_id = #{Database.escape(campaign_id)};").first['n'].to_i
      raise HttpError.new(409, 'campaign needs at least two party members to start') if member_count < 2

      current_actor = first_member['username']

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET status = 'active', current_actor = #{Database.escape(current_actor)}, turn_number = 1, turn_phase = 'player'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [200, { id: campaign_id, status: 'active', current_actor: current_actor, turn_number: 1 }]
    end

    def add_narration(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)

      unless owner?(campaign, actor) || active_delegate_power?(campaign_id, actor[:username], 'narrate')
        raise HttpError.new(403, 'only the campaign dm or a delegated co-gm may narrate')
      end

      text = body['text']
      raise HttpError.new(400, 'text must be a string') unless text.is_a?(String) && !text.empty?

      narrator = owner?(campaign, actor) ? 'dm' : actor[:username]
      sequence = record_event(campaign_id, kind: 'narration', actor: narrator, text: text)

      [201, { sequence: sequence, kind: 'narration', actor: narrator, text: text }]
    end

    def submit_action(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)

      if actor[:role] == 'dm'
        require_owner!(campaign, actor, 'only the owning dm may act on this campaign')

        raise HttpError.new(409, 'the dm cannot submit a player action')
      end

      raise HttpError.new(403, 'must be a party member to submit an action') unless member?(campaign_id, actor[:username])
      raise HttpError.new(409, 'it is not your turn') unless campaign['current_actor'] == actor[:username]

      type = body['type']
      text = body['text']
      raise HttpError.new(400, 'type must be a string') unless type.is_a?(String) && !type.empty?
      raise HttpError.new(400, 'text must be a string') unless text.is_a?(String) && !text.empty?

      sequence = record_event(campaign_id, kind: 'action', actor: actor[:username], text: text, type: type)

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET current_actor = #{Database.escape(campaign['owner'])}, turn_phase = 'gm'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, {
        sequence: sequence,
        kind: 'action',
        actor: actor[:username],
        type: type,
        text: text,
        next_actor: 'dm'
      }]
    end

    def add_resolution(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)

      raise HttpError.new(409, 'only the owning dm may resolve an action') if actor[:role] == 'player'
      require_owner!(campaign, actor, 'only the owning dm may resolve this campaign')
      raise HttpError.new(409, 'it is not the dm\'s turn to resolve') unless campaign['current_actor'] == actor[:username]

      text = body['text']
      raise HttpError.new(400, 'text must be a string') unless text.is_a?(String) && !text.empty?

      sequence = record_event(campaign_id, kind: 'resolution', actor: 'dm', text: text)

      next_actor = next_party_member(campaign_id, campaign['turn_number'].to_i)
      next_turn_number = campaign['turn_number'].to_i + 1

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET current_actor = #{Database.escape(next_actor)}, turn_number = #{Database.int(next_turn_number)}, turn_phase = 'player'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, {
        sequence: sequence,
        kind: 'resolution',
        actor: 'dm',
        text: text,
        next_actor: next_actor,
        turn_number: next_turn_number
      }]
    end

    # Appends a row to play_events, assigning it the next sequence number for
    # the campaign (sequence is per-campaign and 1-based, not a global
    # autoincrement). `type` is only meaningful for kind: 'action'; other
    # kinds leave it NULL. Returns the assigned sequence number.
    def record_event(campaign_id, kind:, actor:, text:, type: nil, target: nil)
      next_sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_events (campaign_id, sequence, kind, actor, text, type, target)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(next_sequence)},
          #{Database.escape(kind)},
          #{Database.escape(actor)},
          #{Database.escape(text)},
          #{type.nil? ? 'NULL' : Database.escape(type)},
          #{target.nil? ? 'NULL' : Database.escape(target)}
        );
      SQL

      next_sequence
    end

    # Last `limit` events for a campaign, oldest first (the query orders
    # newest-first for the LIMIT, then the result is reversed).
    def recent_events(campaign_id, limit: 5)
      events = Database.query(<<~SQL)
        SELECT sequence, kind, actor, text FROM play_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence DESC LIMIT #{Database.int(limit)};
      SQL

      events.reverse.map do |event|
        { sequence: event['sequence'].to_i, kind: event['kind'], actor: event['actor'], text: event['text'] }
      end
    end

    # Determines who acts next among party members after a DM resolution.
    # Deterministic by campaign turn number (not by last-actor lookup): the
    # first resolution (pre-resolution turn_number < 2) hands off to the
    # second party member in join order; every resolution after that hands
    # off to the first party member in join order.
    def next_party_member(campaign_id, turn_number)
      usernames = Database.query(<<~SQL).map { |row| row['username'] }
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY rowid ASC;
      SQL
      return nil if usernames.empty?

      turn_number >= 2 ? usernames.first : usernames[1] || usernames.first
    end

    def get_turn(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)

      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the turn') unless is_owner || member?(campaign_id, actor[:username])

      current_actor = campaign['current_actor']
      phase = campaign['turn_phase'] || (current_actor == campaign['owner'] ? 'dm' : 'player')

      [200, {
        campaign_id: campaign_id,
        current_actor: current_actor,
        phase: phase,
        turn_number: campaign['turn_number'],
        queue: turn_queue(campaign_id),
        overdue: false,
        logical_deadline: campaign['turn_number'].to_i + 1
      }]
    end

    # Deterministic (non-wall-clock) nudge: the owning dm may prompt whoever
    # currently holds the turn. nudge_count is a per-campaign counter that
    # only ever increases, tracked alongside the campaign row.
    def nudge_turn(actor, campaign_id, body)
      raise HttpError.new(403, 'only the owning dm may nudge a turn') unless actor[:role] == 'dm'

      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may nudge this campaign')

      message = body['message']
      raise HttpError.new(400, 'message must be a nonempty string') unless message.is_a?(String) && !message.empty?

      next_nudge_count = campaign['nudge_count'].to_i + 1

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET nudge_count = #{Database.int(next_nudge_count)}
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, {
        actor: actor[:username],
        target: campaign['current_actor'],
        message: message,
        nudge_count: next_nudge_count
      }]
    end

    def my_turn(actor, campaign_id, _body)
      raise HttpError.new(403, 'only a player may view their turn context') unless actor[:role] == 'player'

      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'must be a party member to view turn context') unless member?(campaign_id, actor[:username])

      membership = Database.query(<<~SQL).first
        SELECT character_id, name FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
      SQL

      current_actor = campaign['current_actor']

      [200, {
        campaign_id: campaign_id,
        is_my_turn: !current_actor.nil? && current_actor == actor[:username],
        current_actor: current_actor,
        character: { id: membership['character_id'], name: membership['name'] },
        recent_events: recent_events(campaign_id)
      }]
    end

    def onboarding(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)

      if owner?(campaign, actor)
        return [200, { role: 'dm', next_steps: %w[configure-safety invite-players start-campaign], can_mutate: true }]
      end

      raise HttpError.new(403, 'must be a campaign member to view onboarding') unless member?(campaign_id, actor[:username])

      [200, { role: 'player', next_steps: %w[review-party take-turn submit-action], can_mutate: true }]
    end

    # Issues a spectator ticket for read-only campaign viewing. DM-owner
    # only; spectator_id must be nonempty and globally unique because the
    # bearer token it mints ("spectator-<id>") encodes only that id, with
    # no campaign scoping in the token itself.
    def create_spectator(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may issue spectator tickets')

      spectator_id = body['spectator_id']
      raise HttpError.new(400, 'spectator_id must be a nonempty string') unless spectator_id.is_a?(String) && !spectator_id.empty?

      existing = Database.query("SELECT spectator_id FROM play_spectators WHERE spectator_id = #{Database.escape(spectator_id)};").first
      raise HttpError.new(409, 'spectator_id already exists') if existing

      token = "spectator-#{spectator_id}"
      Database.exec(<<~SQL)
        INSERT INTO play_spectators (spectator_id, campaign_id, token)
        VALUES (#{Database.escape(spectator_id)}, #{Database.escape(campaign_id)}, #{Database.escape(token)});
      SQL

      [201, { spectator_id: spectator_id, token: token }]
    end

    # Public, read-only campaign projection for spectators: no member
    # names, character ids, notes, chat, tokens, ownership, or internal
    # ids. Exclusively for "Bearer spectator-<id>" tickets; normal dm/player
    # session tokens get 403 here even though they're valid elsewhere.
    def spectator_view(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'this view is exclusively for spectator tickets') unless actor[:role] == 'spectator'

      ticket = Database.query("SELECT campaign_id FROM play_spectators WHERE spectator_id = #{Database.escape(actor[:spectator_id])};").first
      raise HttpError.new(401, 'invalid spectator token') unless ticket
      raise HttpError.new(403, 'spectator token is not valid for this campaign') unless ticket['campaign_id'] == campaign_id

      member_count = Database.query("SELECT COUNT(*) AS n FROM play_members WHERE campaign_id = #{Database.escape(campaign_id)};").first['n'].to_i
      document = Database.query("SELECT story FROM play_documents WHERE campaign_id = #{Database.escape(campaign_id)};").first
      story = document ? document['story'] : ''

      [200, {
        campaign_id: campaign_id,
        name: campaign['name'],
        status: campaign['status'],
        party_size: member_count,
        story: story
      }]
    end

    def gm_status(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may view gm status')

      current_actor = campaign['current_actor']

      members = Database.query(<<~SQL)
        SELECT username, character_id, name, class FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY rowid ASC;
      SQL

      party = members.map do |member|
        {
          username: member['username'],
          character_id: member['character_id'],
          name: member['name'],
          class: member['class']
        }
      end

      [200, {
        campaign_id: campaign_id,
        needs_attention: !current_actor.nil? && current_actor == campaign['owner'],
        current_actor: current_actor,
        party: party,
        recent_events: recent_events(campaign_id)
      }]
    end

    def update_document(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only the owning dm may update the campaign document') unless actor[:role] == 'dm' && owner?(campaign, actor)

      story = body['story']
      dm_notes = body['dm_notes']
      raise HttpError.new(400, 'story must be a string') unless story.is_a?(String)
      raise HttpError.new(400, 'dm_notes must be a string') unless dm_notes.is_a?(String)

      Database.exec(<<~SQL)
        INSERT INTO play_documents (campaign_id, story, dm_notes)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(story)}, #{Database.escape(dm_notes)})
        ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes;
      SQL

      [200, { story: story, dm_notes: dm_notes }]
    end

    def get_document(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the document') unless is_owner || member?(campaign_id, actor[:username])

      document = Database.query(<<~SQL).first
        SELECT story, dm_notes FROM play_documents
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      story = document ? document['story'] : ''
      dm_notes = document ? document['dm_notes'] : ''

      if is_owner
        [200, { story: story, dm_notes: dm_notes }]
      else
        [200, { story: story }]
      end
    end

    def update_session_zero(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only the owning dm may set session-zero settings') unless actor[:role] == 'dm' && owner?(campaign, actor)
      raise HttpError.new(409, 'session-zero settings can only be changed while the campaign is in lobby status') unless campaign['status'] == 'lobby'

      rules = body['rules']
      tone = body['tone']
      consent = body['consent']

      raise HttpError.new(400, 'rules must be a nonempty string') unless rules.is_a?(String) && !rules.empty?
      raise HttpError.new(400, 'tone must be a nonempty string') unless tone.is_a?(String) && !tone.empty?
      unless consent.is_a?(Array) && !consent.empty? && consent.all? { |c| c.is_a?(String) && !c.empty? } && consent.uniq.length == consent.length
        raise HttpError.new(400, 'consent must be a nonempty array of unique nonempty strings')
      end

      Database.exec(<<~SQL)
        INSERT INTO play_session_zero (campaign_id, rules, tone, consent_json)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(rules)}, #{Database.escape(tone)}, #{Database.escape(JSON.generate(consent))})
        ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json;
      SQL

      [200, { rules: rules, tone: tone, consent: consent }]
    end

    def get_session_zero(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view session-zero settings') unless is_owner || member?(campaign_id, actor[:username])

      settings = Database.query(<<~SQL).first
        SELECT rules, tone, consent_json FROM play_session_zero
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      raise HttpError.new(404, 'session-zero settings have not been set') unless settings

      [200, { rules: settings['rules'], tone: settings['tone'], consent: JSON.parse(settings['consent_json']) }]
    end

    def find_scene(campaign_id, scene_id)
      row = Database.query(<<~SQL).first
        SELECT id, name, status FROM play_scenes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(scene_id)};
      SQL
      raise HttpError.new(404, 'unknown scene id') unless row

      row
    end

    def create_scene(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create a scene')

      id = body['id']
      name = body['name']
      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_scenes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(id)};
      SQL
      raise HttpError.new(409, 'scene id already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_scenes (campaign_id, id, name, status)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(id)}, #{Database.escape(name)}, 'open');
      SQL

      [201, { id: id, name: name, status: 'open' }]
    end

    def enter_scene(actor, campaign_id, scene_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may enter a scene')

      scene = find_scene(campaign_id, scene_id)
      raise HttpError.new(409, 'closed scenes may not be entered') unless scene['status'] == 'open'

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET current_scene_id = #{Database.escape(scene_id)}
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      record_event(campaign_id, kind: 'scene_enter', actor: 'dm', text: scene['name'])

      [200, { current_scene_id: scene_id, name: scene['name'] }]
    end

    def close_scene(actor, campaign_id, scene_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may close a scene')

      scene = find_scene(campaign_id, scene_id)

      Database.exec(<<~SQL)
        UPDATE play_scenes SET status = 'closed'
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(scene_id)};
      SQL

      record_event(campaign_id, kind: 'scene_close', actor: 'dm', text: scene['name'])

      [200, { id: scene_id, status: 'closed' }]
    end

    def current_scene(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the current scene') unless is_owner || member?(campaign_id, actor[:username])

      current_scene_id = campaign['current_scene_id']
      raise HttpError.new(404, 'no current scene set') if current_scene_id.nil? || current_scene_id.empty?

      scene = find_scene(campaign_id, current_scene_id)
      raise HttpError.new(404, 'no current scene set') unless scene['status'] == 'open'

      [200, { id: scene['id'], name: scene['name'], status: scene['status'] }]
    end

    def find_location(campaign_id, location_id)
      row = Database.query(<<~SQL).first
        SELECT id, name FROM play_locations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(location_id)};
      SQL
      raise HttpError.new(404, 'unknown location id') unless row

      row
    end

    def create_location(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create a location')

      id = body['id']
      name = body['name']
      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_locations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(id)};
      SQL
      raise HttpError.new(409, 'location id already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_locations (campaign_id, id, name)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(id)}, #{Database.escape(name)});
      SQL

      # The party's current location defaults to the first location a dm
      # creates for the campaign, so travel has somewhere to start from
      # without a dedicated "set starting location" route.
      if campaign['current_location_id'].nil? || campaign['current_location_id'].empty?
        Database.exec(<<~SQL)
          UPDATE play_campaigns SET current_location_id = #{Database.escape(id)}
          WHERE id = #{Database.escape(campaign_id)};
        SQL
      end

      [201, { id: id, name: name }]
    end

    def create_connection(actor, campaign_id, from_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create a connection')

      find_location(campaign_id, from_id)

      to_id = body['to_id']
      travel_turns = body['travel_turns']
      raise HttpError.new(400, 'to_id must be a string') unless to_id.is_a?(String) && !to_id.empty?
      raise HttpError.new(400, 'travel_turns must be an integer') unless travel_turns.is_a?(Integer)

      destination = Database.query(<<~SQL).first
        SELECT id FROM play_locations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(to_id)};
      SQL
      raise HttpError.new(400, 'to_id is not a known location') unless destination

      existing = Database.query(<<~SQL).first
        SELECT from_id FROM play_location_connections
        WHERE campaign_id = #{Database.escape(campaign_id)}
          AND from_id = #{Database.escape(from_id)} AND to_id = #{Database.escape(to_id)};
      SQL
      raise HttpError.new(400, 'connection already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(from_id)},
          #{Database.escape(to_id)},
          #{Database.int(travel_turns)}
        );
      SQL

      [201, { from_id: from_id, to_id: to_id, travel_turns: travel_turns }]
    end

    def travel(actor, campaign_id, loc_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view travel') unless is_owner || member?(campaign_id, actor[:username])

      find_location(campaign_id, loc_id)

      connections = Database.query(<<~SQL)
        SELECT to_id, travel_turns FROM play_location_connections
        WHERE campaign_id = #{Database.escape(campaign_id)} AND from_id = #{Database.escape(loc_id)}
        ORDER BY rowid ASC;
      SQL

      destinations = connections.map do |connection|
        destination = find_location(campaign_id, connection['to_id'])
        { id: destination['id'], name: destination['name'], travel_turns: connection['travel_turns'].to_i }
      end

      [200, { destinations: destinations }]
    end

    # Consumes the current actor's exploration turn to move the party along
    # a valid outbound edge from its current location. Mirrors submit_action:
    # only the current (player) actor may call it, and turn control passes
    # to the dm afterward.
    def travel_turn(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)

      if actor[:role] == 'dm'
        require_owner!(campaign, actor, 'only the owning dm may act on this campaign')

        raise HttpError.new(409, 'the dm cannot travel')
      end

      raise HttpError.new(403, 'must be a party member to travel') unless member?(campaign_id, actor[:username])
      raise HttpError.new(409, 'it is not your turn') unless campaign['current_actor'] == actor[:username]

      destination_id = body['destination_id']
      raise HttpError.new(400, 'destination_id must be a string') unless destination_id.is_a?(String) && !destination_id.empty?

      current_location_id = campaign['current_location_id']
      raise HttpError.new(409, 'destination is not a valid connection from the current location') if current_location_id.nil? || current_location_id.empty?

      connection = Database.query(<<~SQL).first
        SELECT to_id, travel_turns FROM play_location_connections
        WHERE campaign_id = #{Database.escape(campaign_id)}
          AND from_id = #{Database.escape(current_location_id)} AND to_id = #{Database.escape(destination_id)};
      SQL
      raise HttpError.new(409, 'destination is not a valid connection from the current location') unless connection

      travel_turns = connection['travel_turns'].to_i

      sequence = record_event(campaign_id, kind: 'travel', actor: actor[:username], text: "travel to #{destination_id}")

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET current_actor = #{Database.escape(campaign['owner'])}, current_location_id = #{Database.escape(destination_id)}, turn_phase = 'gm'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, {
        sequence: sequence,
        kind: 'travel',
        actor: actor[:username],
        destination_id: destination_id,
        travel_turns: travel_turns,
        next_actor: 'dm'
      }]
    end

    # Consumes the current actor's exploration turn to take a short or long
    # rest. Mirrors travel_turn: only the current (player) actor may call it,
    # and turn control passes to the dm afterward. A long rest restores the
    # acting character's hp_current to hp_max; a short rest leaves hp
    # unchanged (no hit-dice spending is modeled here).
    def rest_turn(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)

      if actor[:role] == 'dm'
        require_owner!(campaign, actor, 'only the owning dm may act on this campaign')

        raise HttpError.new(409, 'the dm cannot rest')
      end

      raise HttpError.new(403, 'must be a party member to rest') unless member?(campaign_id, actor[:username])
      raise HttpError.new(409, 'it is not your turn') unless campaign['current_actor'] == actor[:username]

      type = body['type']
      raise HttpError.new(400, 'type must be "short" or "long"') unless %w[short long].include?(type)

      member = Database.query(<<~SQL).first
        SELECT hp_current, hp_max FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
      SQL

      hp_max = member['hp_max'].to_i
      hp_current = type == 'long' ? hp_max : member['hp_current'].to_i

      Database.exec(<<~SQL)
        UPDATE play_members SET hp_current = #{Database.int(hp_current)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
      SQL

      sequence = record_event(campaign_id, kind: 'rest', actor: actor[:username], text: "#{type} rest", type: type)

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET current_actor = #{Database.escape(campaign['owner'])}, turn_phase = 'gm'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, {
        sequence: sequence,
        kind: 'rest',
        actor: actor[:username],
        type: type,
        hp_current: hp_current,
        hp_max: hp_max,
        next_actor: 'dm'
      }]
    end

    # Starts a campaign-bound encounter, independent of the exploration turn
    # queue. Only the owning dm may start one, and a campaign may only have
    # one active encounter at a time.
    def create_encounter(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create an encounter')

      id = body['id']
      name = body['name']
      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_encounters
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(id)};
      SQL
      raise HttpError.new(409, 'encounter id already exists') if existing

      active_encounter = Database.query(<<~SQL).first
        SELECT id FROM play_encounters
        WHERE campaign_id = #{Database.escape(campaign_id)} AND status = 'active';
      SQL
      raise HttpError.new(409, 'campaign is already in combat') if active_encounter

      Database.exec(<<~SQL)
        INSERT INTO play_encounters (campaign_id, id, name, status, combatants_json)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(id)}, #{Database.escape(name)}, 'active', '[]');
      SQL

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET combat_phase = 'combat', pre_combat_actor = #{Database.escape(campaign['current_actor'])}
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [201, { id: id, name: name, status: 'active', combatants: [] }]
    end

    # Adds a deterministic monster combatant to an existing encounter. Only
    # the owning dm may add monsters, and monster ids must be unique within
    # the encounter.
    def add_monster(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may add a monster')

      encounter = find_play_encounter(campaign_id, encounter_id)

      monster_id = body['monster_id']
      name = body['name']
      hp_max = body['hp_max']
      initiative = body['initiative']
      raise HttpError.new(400, 'monster_id must be a string') unless monster_id.is_a?(String) && !monster_id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'hp_max must be a number') unless hp_max.is_a?(Numeric)
      raise HttpError.new(400, 'initiative must be a number') unless initiative.is_a?(Numeric)

      combatants = JSON.parse(encounter['combatants_json'])
      raise HttpError.new(409, 'monster id already exists') if combatants.any? { |c| c['monster_id'] == monster_id }

      monster = {
        monster_id: monster_id,
        name: name,
        hp_max: hp_max,
        initiative: initiative,
        hp_current: hp_max
      }
      combatants << monster

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET combatants_json = #{Database.escape(JSON.generate(combatants))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [201, monster]
    end

    # Removes a monster combatant from an existing encounter. Only the
    # owning dm may remove monsters.
    def remove_monster(actor, campaign_id, encounter_id, monster_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may remove a monster')

      encounter = find_play_encounter(campaign_id, encounter_id)

      combatants = JSON.parse(encounter['combatants_json'])
      raise HttpError.new(404, 'monster not found') unless combatants.any? { |c| c['monster_id'] == monster_id }

      combatants.reject! { |c| c['monster_id'] == monster_id }

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET combatants_json = #{Database.escape(JSON.generate(combatants))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [200, { removed: monster_id }]
    end

    # Binds an existing party member into an encounter as a combatant. Only
    # the owning dm may bind, and each member may only be bound once.
    def bind_combatant(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may bind a combatant')

      encounter = find_play_encounter(campaign_id, encounter_id)

      member = body['member']
      initiative = body['initiative']
      raise HttpError.new(400, 'member must be a string') unless member.is_a?(String) && !member.empty?
      raise HttpError.new(400, 'initiative must be a number') unless initiative.is_a?(Numeric)

      membership = Database.query(<<~SQL).first
        SELECT character_id, name FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(member)};
      SQL
      raise HttpError.new(400, 'unknown party member') unless membership

      combatants = JSON.parse(encounter['combatants_json'])
      raise HttpError.new(409, 'member already bound') if combatants.any? { |c| c['member'] == member }

      combatant = {
        member: member,
        character_id: membership['character_id'],
        name: membership['name'],
        initiative: initiative
      }
      combatants << combatant

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET combatants_json = #{Database.escape(JSON.generate(combatants))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [201, combatant]
    end

    # Unbinds a party member from an encounter. Only the owning dm may
    # unbind.
    def unbind_combatant(actor, campaign_id, encounter_id, member, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may unbind a combatant')

      encounter = find_play_encounter(campaign_id, encounter_id)

      combatants = JSON.parse(encounter['combatants_json'])
      raise HttpError.new(404, 'member not bound') unless combatants.any? { |c| c['member'] == member }

      combatants.reject! { |c| c['member'] == member }

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET combatants_json = #{Database.escape(JSON.generate(combatants))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [200, { removed: member }]
    end

    def find_play_encounter(campaign_id, encounter_id)
      row = Database.query(<<~SQL).first
        SELECT id, name, status, combatants_json, round, turn_index, conditions_json, order_json, ready_json, xp_awarded, rewards_json FROM play_encounters
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL
      raise HttpError.new(404, 'unknown encounter id') unless row

      row
    end

    # A combatant's stable identity for condition tracking: monster_id for
    # monsters, member username for bound party members — the same key
    # find_combatant_hp uses to resolve a `target`.
    def combatant_key(combatant)
      combatant['monster_id'] || combatant['member']
    end

    def encounter_conditions(encounter)
      raw = encounter['conditions_json']
      raw.nil? || raw.empty? ? {} : JSON.parse(raw)
    end

    def persist_encounter_conditions(campaign_id, encounter_id, conditions)
      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET conditions_json = #{Database.escape(JSON.generate(conditions))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL
    end

    def conditions_view(conditions_for_target)
      (conditions_for_target || []).map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
    end

    # Decrements remaining_rounds for every condition on `target_key` by one
    # (the target's turn is starting) and drops any that reach zero.
    def decrement_conditions(campaign_id, encounter_id, encounter, target_key)
      conditions = encounter_conditions(encounter)
      return if conditions[target_key].nil? || conditions[target_key].empty?

      conditions[target_key] = conditions[target_key].filter_map do |c|
        remaining = c['remaining_rounds'].to_i - 1
        remaining.positive? ? { 'condition' => c['condition'], 'remaining_rounds' => remaining } : nil
      end
      conditions.delete(target_key) if conditions[target_key].empty?

      persist_encounter_conditions(campaign_id, encounter_id, conditions)
    end

    # Applies a named, timed condition to a combatant (monster or bound
    # party member). Only the owning dm may call it.
    def add_condition(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may apply a condition')

      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = JSON.parse(encounter['combatants_json'])

      target = body['target']
      condition = body['condition']
      duration_rounds = body['duration_rounds']
      raise HttpError.new(400, 'target must be a string') unless target.is_a?(String) && !target.empty?
      raise HttpError.new(400, 'condition must be a string') unless condition.is_a?(String) && !condition.empty?
      raise HttpError.new(400, 'duration_rounds must be a positive integer') unless duration_rounds.is_a?(Integer) && duration_rounds.positive?
      raise HttpError.new(404, 'unknown combatant target') unless combatants.any? { |c| combatant_key(c) == target }

      conditions = encounter_conditions(encounter)
      conditions[target] ||= []
      conditions[target] << { 'condition' => condition, 'remaining_rounds' => duration_rounds }

      persist_encounter_conditions(campaign_id, encounter_id, conditions)

      [201, { target: target, conditions: conditions_view(conditions[target]) }]
    end

    # Full encounter state for any campaign member (owner or party member):
    # round, whose turn it is, the deterministic initiative order, and the
    # active conditions on every combatant.
    def encounter_status(actor, campaign_id, encounter_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view encounter status') unless is_owner || member?(campaign_id, actor[:username])

      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      conditions = encounter_conditions(encounter)

      active = combatants.empty? ? nil : combatants[encounter['turn_index'].to_i % combatants.length]

      [200, {
        round: encounter['round'].to_i,
        turn_index: encounter['turn_index'].to_i,
        active: active ? combatant_view(active) : nil,
        order: combatants.map { |c| combatant_view(c) },
        conditions: conditions.each_with_object({}) { |(key, list), out| out[key] = conditions_view(list) }
      }]
    end

    # Deterministic initiative order: highest initiative first, ties broken
    # by combatant name so the order never depends on insertion sequence.
    # If the encounter has a manual order (set by a delay), that order is
    # honored instead; combatants absent from it (added afterward) are
    # appended in initiative order.
    def ordered_combatants(encounter)
      combatants = JSON.parse(encounter['combatants_json'])
      by_initiative = combatants.sort_by { |c| [-c['initiative'], c['name']] }

      manual_order = encounter['order_json'].nil? || encounter['order_json'].empty? ? [] : JSON.parse(encounter['order_json'])
      return by_initiative if manual_order.empty?

      by_key = by_initiative.each_with_object({}) { |c, out| out[combatant_key(c)] = c }
      ordered = manual_order.filter_map { |key| by_key.delete(key) }
      ordered + by_key.values
    end

    def combatant_view(combatant)
      {
        name: combatant['name'],
        kind: combatant.key?('monster_id') ? 'monster' : 'player',
        initiative: combatant['initiative']
      }
    end

    # Returns the current combatant for any campaign member (owner or
    # party member).
    def get_encounter_turn(actor, campaign_id, encounter_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the turn') unless is_owner || member?(campaign_id, actor[:username])

      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      raise HttpError.new(404, 'encounter has no combatants') if combatants.empty?

      active = combatants[encounter['turn_index'].to_i % combatants.length]

      [200, {
        round: encounter['round'].to_i,
        turn_index: encounter['turn_index'].to_i,
        active: combatant_view(active)
      }]
    end

    # Advances to the next combatant in deterministic initiative order. Only
    # the owning dm or the current combatant (a bound party member) may
    # advance; monster combatants can only be advanced past by the owner.
    def advance_encounter_turn(actor, campaign_id, encounter_id, _body)
      campaign = find_play_campaign(campaign_id)
      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      raise HttpError.new(404, 'encounter has no combatants') if combatants.empty?

      turn_index = encounter['turn_index'].to_i
      round = encounter['round'].to_i
      active = combatants[turn_index % combatants.length]

      is_owner = owner?(campaign, actor)
      is_current_combatant = active['member'] == actor[:username]
      raise HttpError.new(409, 'only the owner or the current combatant may advance the turn') unless is_owner || is_current_combatant

      next_index = turn_index + 1
      if next_index >= combatants.length
        next_index = 0
        round += 1
      end

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET round = #{round}, turn_index = #{next_index}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      new_active = combatants[next_index]
      decrement_conditions(campaign_id, encounter_id, encounter, combatant_key(new_active))

      [200, {
        round: round,
        turn_index: next_index,
        active: combatant_view(new_active)
      }]
    end

    # Moves the current combatant to a later position in the initiative
    # order (a delay action). Only the owning dm or the current combatant
    # may call it. The delaying combatant keeps the turn (it has not acted
    # yet), so turn_index follows it to its new position; reordering to an
    # index that is not strictly later, or out of bounds, is illegal.
    def delay_turn(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      raise HttpError.new(404, 'encounter has no combatants') if combatants.empty?

      turn_index = encounter['turn_index'].to_i % combatants.length
      active = combatants[turn_index]

      is_owner = owner?(campaign, actor)
      is_current_combatant = active['member'] == actor[:username]
      raise HttpError.new(409, 'only the owner or the current combatant may delay the turn') unless is_owner || is_current_combatant

      index = body['new_index']
      raise HttpError.new(400, 'index must be an integer later position in the initiative order') unless index.is_a?(Integer) && index > turn_index && index < combatants.length

      reordered = combatants.dup
      reordered.delete_at(turn_index)
      reordered.insert(index, active)

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET turn_index = #{index}, order_json = #{Database.escape(JSON.generate(reordered.map { |c| combatant_key(c) }))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [200, {
        round: encounter['round'].to_i,
        turn_index: index,
        order: reordered.map { |c| combatant_view(c) }
      }]
    end

    # Records a ready action for the current combatant: a trigger condition
    # under which they'll act later. Does not advance or reorder the turn.
    def ready_turn(actor, campaign_id, encounter_id, body)
      find_play_campaign(campaign_id)
      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      raise HttpError.new(404, 'encounter has no combatants') if combatants.empty?

      active = combatants[encounter['turn_index'].to_i % combatants.length]
      raise HttpError.new(409, 'it is not your turn') unless active['member'] == actor[:username]

      trigger = body['trigger']
      raise HttpError.new(400, 'trigger must be a string') unless trigger.is_a?(String) && !trigger.empty?

      ready_records = encounter['ready_json'].nil? || encounter['ready_json'].empty? ? [] : JSON.parse(encounter['ready_json'])
      ready_records << { 'actor' => actor[:username], 'trigger' => trigger }

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET ready_json = #{Database.escape(JSON.generate(ready_records))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [201, { actor: actor[:username], trigger: trigger }]
    end

    COMBAT_ACTION_TYPES = %w[attack help dodge ready].freeze

    # Records a typed combat action from the current combatant. The action is
    # logged to the campaign event stream but does not itself advance the
    # encounter turn (that remains a separate call to advance_encounter_turn).
    def record_combat_action(actor, campaign_id, encounter_id, body)
      find_play_campaign(campaign_id)
      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = ordered_combatants(encounter)
      raise HttpError.new(404, 'encounter has no combatants') if combatants.empty?

      active = combatants[encounter['turn_index'].to_i % combatants.length]
      raise HttpError.new(409, 'it is not your turn') unless active['member'] == actor[:username]

      type = body['type']
      target = body['target']
      text = body['text']
      raise HttpError.new(400, 'type must be one of attack, help, dodge, ready') unless type.is_a?(String) && COMBAT_ACTION_TYPES.include?(type)
      raise HttpError.new(400, 'text must be a string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'target must be a string') unless target.nil? || (target.is_a?(String) && !target.empty?)

      sequence = record_event(campaign_id, kind: 'combat_action', actor: actor[:username], text: text, type: type, target: target)

      [201, {
        sequence: sequence,
        kind: 'combat_action',
        actor: actor[:username],
        type: type,
        target: target,
        text: text
      }]
    end

    # Looks up a combatant's current hp by target id, checking monster
    # combatants (keyed by monster_id, hp tracked in combatants_json) before
    # bound party members (keyed by username, hp tracked in play_members —
    # the same source rest_turn reads and writes).
    def find_combatant_hp(campaign_id, encounter_id, target)
      encounter = find_play_encounter(campaign_id, encounter_id)
      combatants = JSON.parse(encounter['combatants_json'])

      monster = combatants.find { |c| c['monster_id'] == target }
      return { kind: :monster, hp_current: monster['hp_current'].to_i, hp_max: monster['hp_max'].to_i } if monster

      player = combatants.find { |c| c['member'] == target }
      raise HttpError.new(404, 'unknown combatant target') unless player

      membership = Database.query(<<~SQL).first
        SELECT hp_current, hp_max FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(target)};
      SQL

      { kind: :player, hp_current: membership['hp_current'].to_i, hp_max: membership['hp_max'].to_i }
    end

    def persist_combatant_hp(campaign_id, encounter_id, target, kind, hp_after)
      if kind == :monster
        encounter = find_play_encounter(campaign_id, encounter_id)
        combatants = JSON.parse(encounter['combatants_json'])
        combatants.each { |c| c['hp_current'] = hp_after if c['monster_id'] == target }

        Database.exec(<<~SQL)
          UPDATE play_encounters
          SET combatants_json = #{Database.escape(JSON.generate(combatants))}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
        SQL
      else
        Database.exec(<<~SQL)
          UPDATE play_members SET hp_current = #{Database.int(hp_after)}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(target)};
        SQL
      end
    end

    # Applies deterministic damage to a combatant (monster or bound party
    # member). Only the owning dm may call it. HP floors at 0.
    def damage_target(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may apply damage')

      target = body['target']
      amount = body['amount']
      raise HttpError.new(400, 'target must be a string') unless target.is_a?(String) && !target.empty?
      raise HttpError.new(400, 'amount must be a non-negative integer') unless amount.is_a?(Integer) && amount >= 0

      info = find_combatant_hp(campaign_id, encounter_id, target)
      hp_before = info[:hp_current]
      hp_after = [hp_before - amount, 0].max

      persist_combatant_hp(campaign_id, encounter_id, target, info[:kind], hp_after)

      [200, { target: target, hp_before: hp_before, hp_after: hp_after, damage: amount }]
    end

    # Applies deterministic healing to a combatant (monster or bound party
    # member). Only the owning dm may call it. HP caps at hp_max.
    def heal_target(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may apply healing')

      target = body['target']
      amount = body['amount']
      raise HttpError.new(400, 'target must be a string') unless target.is_a?(String) && !target.empty?
      raise HttpError.new(400, 'amount must be a non-negative integer') unless amount.is_a?(Integer) && amount >= 0

      info = find_combatant_hp(campaign_id, encounter_id, target)
      hp_before = info[:hp_current]
      hp_after = [hp_before + amount, info[:hp_max]].min

      persist_combatant_hp(campaign_id, encounter_id, target, info[:kind], hp_after)

      [200, { target: target, hp_before: hp_before, hp_after: hp_after, healing: amount }]
    end

    VALID_RACES = %w[human elf dwarf halfling dragonborn gnome half-elf half-orc tiefling].freeze
    VALID_CLASSES = %w[barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard].freeze
    VALID_BACKGROUNDS = %w[
      acolyte charlatan criminal entertainer folk-hero guild-artisan hermit noble outlander sage sailor soldier
    ].freeze
    HIT_DICE = {
      'barbarian' => 12,
      'fighter' => 10, 'paladin' => 10, 'ranger' => 10,
      'bard' => 8, 'cleric' => 8, 'druid' => 8, 'monk' => 8, 'rogue' => 8, 'warlock' => 8,
      'sorcerer' => 6, 'wizard' => 6
    }.freeze
    BUILD_ABILITY_KEYS = %w[str dex con int wis cha].freeze

    VALID_SKILLS = %w[
      acrobatics animal_handling arcana athletics deception history insight intimidation
      investigation medicine nature perception performance persuasion religion sleight_of_hand
      stealth survival
    ].freeze

    # Validates race/class/background/ability-score choices for a character
    # the caller owns and returns the derived level-1 defaults (hp_max,
    # proficiency_bonus). Only the character's owning player may build it.
    def build_character(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may build this character") unless member['owner'] == actor[:username]

      race = body['race']
      klass = body['class']
      background = body['background']
      abilities = body['abilities']

      raise HttpError.new(400, 'race must be one of the valid races') unless VALID_RACES.include?(race)
      raise HttpError.new(400, 'class must be one of the valid classes') unless VALID_CLASSES.include?(klass)
      raise HttpError.new(400, 'background must be one of the valid backgrounds') unless VALID_BACKGROUNDS.include?(background)
      raise HttpError.new(400, 'abilities must be an object') unless abilities.is_a?(Hash)

      BUILD_ABILITY_KEYS.each do |key|
        raise HttpError.new(400, "abilities.#{key} must be an integer between 1 and 30") unless abilities[key].is_a?(Integer) && (1..30).cover?(abilities[key])
      end

      level = 1
      ability_modifiers = BUILD_ABILITY_KEYS.each_with_object({}) do |key, memo|
        memo[key] = GameRules.ability_modifier(abilities[key])
      end
      con_modifier = ability_modifiers['con']
      hp_max = HIT_DICE.fetch(klass) + con_modifier
      proficiency_bonus = GameRules.proficiency_bonus(level)

      Database.exec(<<~SQL)
        UPDATE play_members
        SET race = #{Database.escape(race)}, class = #{Database.escape(klass)}, background = #{Database.escape(background)},
            level = #{Database.int(level)}, hp_max = #{Database.int(hp_max)}, hp_current = #{Database.int(hp_max)},
            con_modifier = #{Database.int(con_modifier)}, hit_dice = #{Database.escape("1d#{HIT_DICE.fetch(klass)}")},
            str_modifier = #{Database.int(ability_modifiers['str'])}, dex_modifier = #{Database.int(ability_modifiers['dex'])},
            int_modifier = #{Database.int(ability_modifiers['int'])}, wis_modifier = #{Database.int(ability_modifiers['wis'])},
            cha_modifier = #{Database.int(ability_modifiers['cha'])}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [200, {
        character_id: character_id,
        race: race,
        class: klass,
        background: background,
        level: level,
        hp_max: hp_max,
        proficiency_bonus: proficiency_bonus
      }]
    end

    # Resolves a skill-check total from the character's ability modifier and
    # (if proficient) their level-derived proficiency bonus. Only the
    # character's owning player may call it.
    def skill_check(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may take a skill check for this character") unless member['owner'] == actor[:username]

      skill = body['skill']
      ability = body['ability']
      proficient = body['proficient']
      roll = body['roll']

      raise HttpError.new(400, 'skill must be one of the valid skills') unless VALID_SKILLS.include?(skill)
      raise HttpError.new(400, 'ability must be one of the valid abilities') unless BUILD_ABILITY_KEYS.include?(ability)
      raise HttpError.new(400, 'proficient must be a boolean') unless [true, false].include?(proficient)
      raise HttpError.new(400, 'roll must be an integer') unless roll.is_a?(Integer)

      ability_modifier = member["#{ability}_modifier"].to_i
      proficiency_bonus = proficient ? GameRules.proficiency_bonus(member['level'].to_i) : 0
      modifier = ability_modifier + proficiency_bonus
      total = roll + modifier

      [200, {
        character_id: character_id,
        skill: skill,
        ability: ability,
        modifier: modifier,
        total: total
      }]
    end

    def find_character_member(campaign_id, character_id)
      row = Database.query(<<~SQL).first
        SELECT username, name, hp_current, hp_max, status, death_save_successes, death_save_failures, owner,
               class, level, con_modifier, hit_dice, str_modifier, dex_modifier, int_modifier, wis_modifier, cha_modifier, gold
        FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      raise HttpError.new(404, 'unknown character id') unless row

      row
    end

    # Fixed (non-rolled) HP gained per level beyond 1st, per class hit die:
    # the SRD average of the hit die rounded up (e.g. a d8 averages 4.5,
    # rounded up to 5), before adding the character's con_modifier.
    LEVEL_UP_HP_BASE = HIT_DICE.transform_values { |die| (die / 2) + 1 }.freeze

    # Applies a deterministic level-up: the new level must be exactly one
    # higher than the current level, and only the character's owning player
    # may call it. Rogues (hit die 1d8) gain 1d8's fixed average + con_modifier
    # max HP per level beyond 1, same fixed-HP rule every class uses.
    def level_up_character(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may level up this character") unless member['owner'] == actor[:username]

      new_level = body['level']
      current_level = member['level'].to_i
      raise HttpError.new(400, 'level must be an integer') unless new_level.is_a?(Integer)
      raise HttpError.new(400, 'level must be exactly one higher than the current level') unless new_level == current_level + 1

      klass = member['class']
      hit_dice = member['hit_dice'] || "1d#{HIT_DICE.fetch(klass)}"
      con_modifier = member['con_modifier'].to_i

      hp_gain = LEVEL_UP_HP_BASE.fetch(klass) + con_modifier
      hp_max = member['hp_max'].to_i + hp_gain
      hp_current = member['hp_current'].to_i + hp_gain
      proficiency_bonus = GameRules.proficiency_bonus(new_level)

      Database.exec(<<~SQL)
        UPDATE play_members
        SET level = #{Database.int(new_level)}, hp_max = #{Database.int(hp_max)}, hp_current = #{Database.int(hp_current)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [200, {
        character_id: character_id,
        level: new_level,
        hp_max: hp_max,
        hit_dice: hit_dice,
        proficiency_bonus: proficiency_bonus
      }]
    end

    # Reads the current owning player of a character. Any campaign member
    # (the owning dm or a party member) may view it.
    def character_owner(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view character owner') unless is_owner || member?(campaign_id, actor[:username])

      member = find_character_member(campaign_id, character_id)

      [200, { character_id: character_id, owner: member['owner'] }]
    end

    # Claims an unowned character for the requesting player. A character
    # already linked to a player identity cannot be claimed by anyone else.
    def claim_character(actor, campaign_id, character_id, _body)
      find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only a campaign member may claim a character') unless member?(campaign_id, actor[:username])

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(409, 'character is already owned') unless member['owner'].nil? || member['owner'].to_s.empty?

      Database.exec(<<~SQL)
        UPDATE play_members SET owner = #{Database.escape(actor[:username])}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [201, { character_id: character_id, owner: actor[:username] }]
    end

    # Transfers ownership of a character to another campaign member. Only
    # the current owner may transfer, and the new owner must already be a
    # member of the campaign.
    def transfer_character(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, 'only the current owner may transfer this character') unless member['owner'] == actor[:username]

      new_owner = body['new_owner']
      raise HttpError.new(400, 'new_owner must be a string') unless new_owner.is_a?(String) && !new_owner.empty?
      raise HttpError.new(400, 'new_owner must be a campaign member') unless member?(campaign_id, new_owner)

      Database.exec(<<~SQL)
        UPDATE play_members SET owner = #{Database.escape(new_owner)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [200, { character_id: character_id, owner: new_owner }]
    end

    # Applies deterministic damage to a party member's own character sheet
    # (as opposed to damage_target, which applies to an encounter
    # combatant). Only the owning dm may call it. HP floors at 0, and a
    # character freshly dropped to 0 HP becomes unconscious with its death
    # save counters reset.
    def damage_character(actor, campaign_id, character_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may apply damage')

      amount = body['amount']
      raise HttpError.new(400, 'amount must be a non-negative integer') unless amount.is_a?(Integer) && amount >= 0

      member = find_character_member(campaign_id, character_id)
      hp_before = member['hp_current'].to_i
      hp_after = [hp_before - amount, 0].max

      if hp_after.zero? && member['status'] == 'conscious'
        Database.exec(<<~SQL)
          UPDATE play_members
          SET hp_current = #{Database.int(hp_after)}, status = 'unconscious',
              death_save_successes = 0, death_save_failures = 0
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
        SQL
      else
        Database.exec(<<~SQL)
          UPDATE play_members SET hp_current = #{Database.int(hp_after)}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
        SQL
      end

      [200, { target: character_id, hp_before: hp_before, hp_after: hp_after, damage: amount }]
    end

    def character_status(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view character status') unless is_owner || member?(campaign_id, actor[:username])

      member = find_character_member(campaign_id, character_id)

      [200, {
        character_id: character_id,
        hp_current: member['hp_current'].to_i,
        hp_max: member['hp_max'].to_i,
        status: member['status']
      }]
    end

    # Records a death saving throw for an unconscious character. Only the
    # character's own owning player may roll, and only while unconscious
    # (neither stable nor dead accepts further rolls, nor does a conscious
    # character). Three successes stabilize; three failures kill.
    def death_save(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)

      raise HttpError.new(403, "only the character's owner may record a death save") unless member['username'] == actor[:username]
      raise HttpError.new(409, 'character is not eligible for death saves') unless member['status'] == 'unconscious'

      outcome = body['outcome']
      raise HttpError.new(400, 'outcome must be "success" or "failure"') unless %w[success failure].include?(outcome)

      successes = member['death_save_successes'].to_i
      failures = member['death_save_failures'].to_i
      successes += 1 if outcome == 'success'
      failures += 1 if outcome == 'failure'

      status = 'unconscious'
      status = 'stable' if successes >= 3
      status = 'dead' if failures >= 3

      Database.exec(<<~SQL)
        UPDATE play_members
        SET death_save_successes = #{Database.int(successes)}, death_save_failures = #{Database.int(failures)}, status = #{Database.escape(status)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [201, { character_id: character_id, successes: successes, failures: failures, status: status }]
    end

    # Awards deterministic XP and loot for an encounter. Only the owning dm
    # may award rewards, and rewards may be awarded only once per encounter.
    def award_rewards(actor, campaign_id, encounter_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may award rewards')

      encounter = find_play_encounter(campaign_id, encounter_id)
      raise HttpError.new(409, 'rewards already awarded for this encounter') unless encounter['rewards_json'].nil?

      xp = body['xp']
      loot = body['loot']
      raise HttpError.new(400, 'xp must be a non-negative integer') unless xp.is_a?(Integer) && xp >= 0
      raise HttpError.new(400, 'loot must be an array') unless loot.is_a?(Array)
      loot.each do |item|
        unless item.is_a?(Hash) && item['slug'].is_a?(String) && !item['slug'].empty? &&
               item['quantity'].is_a?(Integer) && item['quantity'] > 0
          raise HttpError.new(400, 'loot entries must have a slug string and a positive integer quantity')
        end
      end

      reward = { id: encounter_id, xp: xp, loot: loot }

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET xp_awarded = #{Database.int(xp)}, rewards_json = #{Database.escape(JSON.generate(reward))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [200, reward]
    end

    # Marks an encounter closed. Only the owning dm may call it. Closing
    # before awarding rewards is allowed but reports xp_awarded: 0.
    def close_encounter(actor, campaign_id, encounter_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may close an encounter')

      encounter = find_play_encounter(campaign_id, encounter_id)

      Database.exec(<<~SQL)
        UPDATE play_encounters
        SET status = 'closed'
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
      SQL

      [200, { id: encounter_id, status: 'closed', xp_awarded: encounter['xp_awarded'].to_i }]
    end

    # Closes the encounter (if still active) and restores the campaign to
    # the exploration turn queue, handing the turn back to the owning dm.
    # Only the owning dm may call it, and the campaign must currently be
    # in combat.
    def end_encounter(actor, campaign_id, encounter_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may end an encounter')
      raise HttpError.new(409, 'campaign is not in combat') unless campaign['combat_phase'] == 'combat'

      encounter = find_play_encounter(campaign_id, encounter_id)

      if encounter['status'] == 'active'
        Database.exec(<<~SQL)
          UPDATE play_encounters
          SET status = 'closed'
          WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(encounter_id)};
        SQL
      end

      restored_actor = campaign['owner']

      Database.exec(<<~SQL)
        UPDATE play_campaigns
        SET combat_phase = 'exploration', current_actor = #{Database.escape(restored_actor)}, pre_combat_actor = NULL, turn_phase = 'exploration'
        WHERE id = #{Database.escape(campaign_id)};
      SQL

      [200, { campaign_id: campaign_id, status: 'active', phase: 'exploration', current_actor: restored_actor }]
    end

    # A small, fixed compendium of known spells: each maps to its canonical
    # name, level, and the classes that may know it. Classes not listed as
    # keys anywhere in SPELL_COMPENDIUM (e.g. rogue, barbarian, fighter,
    # monk) cannot learn any spell.
    SPELL_COMPENDIUM = {
      'fire-bolt' => { name: 'Fire Bolt', level: 0, classes: %w[sorcerer wizard] },
      'ray-of-frost' => { name: 'Ray of Frost', level: 0, classes: %w[sorcerer wizard] },
      'mage-hand' => { name: 'Mage Hand', level: 0, classes: %w[bard sorcerer warlock wizard] },
      'light' => { name: 'Light', level: 0, classes: %w[bard cleric sorcerer wizard] },
      'guidance' => { name: 'Guidance', level: 0, classes: %w[cleric druid] },
      'sacred-flame' => { name: 'Sacred Flame', level: 0, classes: %w[cleric] },
      'druidcraft' => { name: 'Druidcraft', level: 0, classes: %w[druid] },
      'eldritch-blast' => { name: 'Eldritch Blast', level: 0, classes: %w[warlock] },
      'vicious-mockery' => { name: 'Vicious Mockery', level: 0, classes: %w[bard] },
      'magic-missile' => { name: 'Magic Missile', level: 1, classes: %w[sorcerer wizard] },
      'shield' => { name: 'Shield', level: 1, classes: %w[sorcerer wizard] },
      'charm-person' => { name: 'Charm Person', level: 1, classes: %w[bard druid sorcerer warlock wizard] },
      'detect-magic' => { name: 'Detect Magic', level: 1, classes: %w[bard cleric druid paladin ranger sorcerer warlock wizard] },
      'cure-wounds' => { name: 'Cure Wounds', level: 1, classes: %w[bard cleric druid paladin ranger] },
      'bless' => { name: 'Bless', level: 1, classes: %w[cleric paladin] },
      'healing-word' => { name: 'Healing Word', level: 1, classes: %w[bard cleric druid] },
      'faerie-fire' => { name: 'Faerie Fire', level: 1, classes: %w[bard druid] },
      'hunters-mark' => { name: "Hunter's Mark", level: 1, classes: %w[ranger] }
    }.freeze

    # Adds a spell to a character's spellbook. Only the character's owning
    # player may call it. The spell must be a known spell (spell_id/name/
    # level matching SPELL_COMPENDIUM) that the character's class may learn;
    # a character may know at most one copy of any given spell.
    def add_spell(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may add a spell") unless member['owner'] == actor[:username]

      spell_id = body['spell_id']
      name = body['name']
      level = body['level']
      raise HttpError.new(400, 'spell_id must be a non-empty string') unless spell_id.is_a?(String) && !spell_id.empty?
      raise HttpError.new(400, 'name must be a non-empty string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)

      spell = SPELL_COMPENDIUM[spell_id]
      klass = member['class']
      unless spell && spell[:name] == name && spell[:level] == level && spell[:classes].include?(klass)
        raise HttpError.new(400, 'spell is not valid for this character\'s class')
      end

      existing = Database.query(<<~SQL).first
        SELECT spell_id FROM play_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND spell_id = #{Database.escape(spell_id)};
      SQL
      raise HttpError.new(409, 'character already knows this spell') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_spells (campaign_id, character_id, spell_id, name, level)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(spell_id)}, #{Database.escape(name)}, #{Database.int(level)});
      SQL

      [201, { spell_id: spell_id, name: name, level: level }]
    end

    # Returns the full spellbook for a character. Any campaign member (the
    # owning dm or a party member) may view it.
    def list_spells(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the spellbook') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      rows = Database.query(<<~SQL)
        SELECT spell_id, name, level FROM play_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
        ORDER BY rowid ASC;
      SQL

      spells = rows.map { |row| { spell_id: row['spell_id'], name: row['name'], level: row['level'].to_i } }

      [200, { spells: spells }]
    end

    # Maps each spellcasting class to its preparation ability. Classes not
    # listed here (rogue, fighter, barbarian, monk, ...) cannot prepare spells.
    SPELLCASTING_ABILITY = {
      'wizard' => 'int_modifier',
      'cleric' => 'wis_modifier',
      'druid' => 'wis_modifier',
      'paladin' => 'cha_modifier',
      'ranger' => 'wis_modifier',
      'bard' => 'cha_modifier',
      'sorcerer' => 'cha_modifier',
      'warlock' => 'cha_modifier'
    }.freeze

    # A spellcasting class's maximum prepared spells at its current level:
    # the relevant ability modifier plus class level, with a floor of 1
    # (e.g. a level-1 wizard with a +0 int modifier may prepare one spell).
    def max_prepared_spells(member)
      ability_column = SPELLCASTING_ABILITY[member['class']]
      return nil unless ability_column

      [member[ability_column].to_i + member['level'].to_i, 1].max
    end

    # Sets a character's full list of prepared spells, replacing any prior
    # selection. Only the character's owning player may call it. The
    # character's class must be a spellcasting class, every spell_id must
    # already be known by the character, and the list length must not
    # exceed the class level's maximum prepared spells.
    def set_prepared_spells(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may prepare spells") unless member['owner'] == actor[:username]

      max_prepared = max_prepared_spells(member)
      raise HttpError.new(400, "#{member['class']} is not a spellcasting class") unless max_prepared

      spell_ids = body['spell_ids']
      raise HttpError.new(400, 'spell_ids must be an array of strings') unless spell_ids.is_a?(Array) && spell_ids.all? { |id| id.is_a?(String) }
      raise HttpError.new(400, 'prepared spell list exceeds the maximum allowed count') if spell_ids.length > max_prepared

      known_spell_ids = Database.query(<<~SQL).map { |row| row['spell_id'] }
        SELECT spell_id FROM play_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      unknown = spell_ids.reject { |id| known_spell_ids.include?(id) }
      raise HttpError.new(400, "unknown spell: #{unknown.first}") unless unknown.empty?

      Database.exec(<<~SQL)
        INSERT INTO play_prepared_spells (campaign_id, character_id, spell_ids_json)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(JSON.generate(spell_ids))})
        ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_ids_json = excluded.spell_ids_json;
      SQL

      [200, { character_id: character_id, prepared_spells: spell_ids, max_prepared: max_prepared }]
    end

    # Returns a character's prepared spells. Any campaign member (the
    # owning dm or a party member) may view it.
    def get_prepared_spells(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view prepared spells') unless is_owner || member?(campaign_id, actor[:username])

      member = find_character_member(campaign_id, character_id)
      max_prepared = max_prepared_spells(member)

      row = Database.query(<<~SQL).first
        SELECT spell_ids_json FROM play_prepared_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      prepared_spells = row ? JSON.parse(row['spell_ids_json']) : []

      [200, { character_id: character_id, prepared_spells: prepared_spells, max_prepared: max_prepared }]
    end

    # A spellcasting class's remaining spell slots of a given level are
    # capacity minus casts already recorded at that level this game. Slot
    # capacity is deterministic from character level and spell level (e.g. a
    # level-1 wizard has one first-level slot), floored at 0.
    def max_spell_slots(member, slot_level)
      [member['level'].to_i - slot_level + 1, 0].max
    end

    # Casts a known, currently prepared spell. Only the character's owning
    # player may call it. The character's class must be a spellcasting
    # class, the spell must be currently prepared, and a spell slot of the
    # spell's level must remain; casting consumes one such slot.
    def cast_spell(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may cast a spell") unless member['owner'] == actor[:username]

      spell_id = body['spell_id']
      target = body['target']
      raise HttpError.new(400, 'spell_id must be a non-empty string') unless spell_id.is_a?(String) && !spell_id.empty?
      raise HttpError.new(400, 'target must be a non-empty string') unless target.is_a?(String) && !target.empty?
      raise HttpError.new(400, "#{member['class']} is not a spellcasting class") unless SPELLCASTING_ABILITY.key?(member['class'])

      known_spell = Database.query(<<~SQL).first
        SELECT level FROM play_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND spell_id = #{Database.escape(spell_id)};
      SQL

      prepared_row = Database.query(<<~SQL).first
        SELECT spell_ids_json FROM play_prepared_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      prepared_spell_ids = prepared_row ? JSON.parse(prepared_row['spell_ids_json']) : []

      raise HttpError.new(400, 'spell is not currently prepared') unless known_spell && prepared_spell_ids.include?(spell_id)

      slot_level = known_spell['level'].to_i
      max_slots = max_spell_slots(member, slot_level)

      cast_count = Database.query(<<~SQL).first['n'].to_i
        SELECT COUNT(*) AS n FROM play_casts
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND slot_level = #{Database.int(slot_level)};
      SQL

      slots_remaining = max_slots - cast_count
      raise HttpError.new(409, 'no remaining spell slots of the required level') unless slots_remaining.positive?

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_casts
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(character_id)},
          #{Database.int(sequence)},
          #{Database.escape(spell_id)},
          #{Database.escape(target)},
          #{Database.int(slot_level)},
          #{Database.int(slots_remaining - 1)}
        );
      SQL

      [201, {
        character_id: character_id,
        spell_id: spell_id,
        target: target,
        slot_level: slot_level,
        slots_remaining: slots_remaining - 1,
        sequence: sequence
      }]
    end

    # Returns a character's cast history in order. Any campaign member (the
    # owning dm or a party member) may view it.
    def list_casts(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view cast history') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      rows = Database.query(<<~SQL)
        SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_casts
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
        ORDER BY sequence ASC;
      SQL

      casts = rows.map do |row|
        {
          character_id: character_id,
          spell_id: row['spell_id'],
          target: row['target'],
          slot_level: row['slot_level'].to_i,
          slots_remaining: row['slots_remaining'].to_i,
          sequence: row['sequence'].to_i
        }
      end

      [200, { casts: casts }]
    end

    # Loads the active concentration row for a character, or nil.
    def concentration_row(campaign_id, character_id)
      Database.query(<<~SQL).first
        SELECT spell_id, target, remaining_turns FROM play_concentration
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
    end

    def concentration_payload(row)
      return nil unless row

      { spell_id: row['spell_id'], target: row['target'], remaining_turns: row['remaining_turns'].to_i }
    end

    # Sets a character's active concentration, replacing any prior
    # concentration. Only the character's owning player may call it. The
    # character's class must be a spellcasting class, the spell must be
    # known and currently prepared, and duration_turns must be positive.
    def set_concentration(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may set concentration") unless member['owner'] == actor[:username]

      spell_id = body['spell_id']
      target = body['target']
      duration_turns = body['duration_turns']
      raise HttpError.new(400, 'spell_id must be a non-empty string') unless spell_id.is_a?(String) && !spell_id.empty?
      raise HttpError.new(400, 'target must be a non-empty string') unless target.is_a?(String) && !target.empty?
      raise HttpError.new(400, 'duration_turns must be a positive integer') unless duration_turns.is_a?(Integer) && duration_turns.positive?
      raise HttpError.new(400, "#{member['class']} is not a spellcasting class") unless SPELLCASTING_ABILITY.key?(member['class'])

      known_spell = Database.query(<<~SQL).first
        SELECT spell_id FROM play_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND spell_id = #{Database.escape(spell_id)};
      SQL

      prepared_row = Database.query(<<~SQL).first
        SELECT spell_ids_json FROM play_prepared_spells
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      prepared_spell_ids = prepared_row ? JSON.parse(prepared_row['spell_ids_json']) : []

      raise HttpError.new(400, 'spell is not currently prepared') unless known_spell && prepared_spell_ids.include?(spell_id)

      Database.exec(<<~SQL)
        INSERT INTO play_concentration (campaign_id, character_id, spell_id, target, remaining_turns)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(spell_id)}, #{Database.escape(target)}, #{Database.int(duration_turns)})
        ON CONFLICT(campaign_id, character_id) DO UPDATE SET
          spell_id = excluded.spell_id,
          target = excluded.target,
          remaining_turns = excluded.remaining_turns;
      SQL

      [200, { character_id: character_id, concentration: { spell_id: spell_id, target: target, remaining_turns: duration_turns } }]
    end

    # Returns a character's active concentration state, or null. Any
    # campaign member (the owning dm or a party member) may view it.
    def get_concentration(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view concentration') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      [200, { character_id: character_id, concentration: concentration_payload(concentration_row(campaign_id, character_id)) }]
    end

    # Decrements the active concentration's remaining_turns by one, clearing
    # it when the count reaches zero. Allowed for any campaign member.
    def advance_concentration_turn(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to advance concentration') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      row = concentration_row(campaign_id, character_id)
      if row
        remaining = row['remaining_turns'].to_i - 1
        if remaining <= 0
          Database.exec(<<~SQL)
            DELETE FROM play_concentration
            WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
          SQL
        else
          Database.exec(<<~SQL)
            UPDATE play_concentration SET remaining_turns = #{Database.int(remaining)}
            WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
          SQL
        end
      end

      [200, { character_id: character_id, concentration: concentration_payload(concentration_row(campaign_id, character_id)) }]
    end

    # Clears a character's active concentration. Only the character's
    # owning player may call it.
    def clear_concentration(actor, campaign_id, character_id, _body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may clear concentration") unless member['owner'] == actor[:username]

      Database.exec(<<~SQL)
        DELETE FROM play_concentration
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [200, { character_id: character_id, concentration: nil }]
    end

    # Catalog of item ids valid for per-character inventory stacks.
    INVENTORY_CATALOG = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze

    # Equipment slot each catalog equipment item legally occupies.
    ITEM_SLOTS = {
      'leather-armor' => 'armor',
      'ring-of-protection' => 'accessory',
      'amulet-of-health' => 'accessory'
    }.freeze

    EQUIPMENT_SLOTS = %w[armor accessory].freeze

    ATTUNABLE_ITEMS = %w[ring-of-protection amulet-of-health].freeze

    MAX_ATTUNEMENTS = 1

    # Catalog items that may be consumed, and the effect each produces.
    CONSUMABLE_EFFECTS = {
      'healing-potion' => { type: 'healing', hp_restored: 5 }
    }.freeze

    def inventory_item_quantity(campaign_id, character_id, item_id)
      row = Database.query(<<~SQL).first
        SELECT quantity FROM play_inventory_items
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND item_id = #{Database.escape(item_id)};
      SQL
      row ? row['quantity'].to_i : 0
    end

    # Adds a quantity of a catalog item to a character's inventory stack.
    # Only the character's owning player may call it.
    def add_inventory_item(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may add items") unless member['owner'] == actor[:username]

      item_id = body['item_id']
      quantity = body['quantity']
      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      current = inventory_item_quantity(campaign_id, character_id, item_id)
      total = current + quantity

      Database.exec(<<~SQL)
        INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(item_id)}, #{Database.int(total)})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = #{Database.int(total)};
      SQL

      [201, { character_id: character_id, item_id: item_id, quantity: quantity, total_quantity: total }]
    end

    # Returns a character's full inventory item stack list, ordered by
    # item_id. Any campaign member (the owning dm or a party member) may
    # view it.
    def list_inventory_items(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view inventory') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      rows = Database.query(<<~SQL)
        SELECT item_id, quantity FROM play_inventory_items
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
        ORDER BY item_id ASC;
      SQL

      items = rows.map { |row| { item_id: row['item_id'], quantity: row['quantity'].to_i } }

      [200, { character_id: character_id, items: items }]
    end

    # Removes a quantity of a catalog item from a character's inventory
    # stack. Only the character's owning player may call it. Removing more
    # than the held quantity returns 409.
    def remove_inventory_item(actor, campaign_id, character_id, item_id, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may remove items") unless member['owner'] == actor[:username]

      quantity = body['quantity']
      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      current = inventory_item_quantity(campaign_id, character_id, item_id)
      raise HttpError.new(409, 'cannot remove more than the held quantity') if quantity > current

      total = current - quantity
      if total.zero?
        Database.exec(<<~SQL)
          DELETE FROM play_inventory_items
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      else
        Database.exec(<<~SQL)
          UPDATE play_inventory_items SET quantity = #{Database.int(total)}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      end

      [200, { character_id: character_id, item_id: item_id, quantity: quantity, total_quantity: total }]
    end

    # Consumes one unit of a held consumable inventory item. Only the
    # character's owning player may call it. Only catalog items flagged as
    # consumable may be consumed; non-consumable catalog items and unknown
    # item ids return 400. Having no held stack (or a zero-quantity stack)
    # returns 409.
    def consume_inventory_item(actor, campaign_id, character_id, item_id, _body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may consume items") unless member['owner'] == actor[:username]

      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      effect = CONSUMABLE_EFFECTS[item_id]
      raise HttpError.new(400, 'item_id is not consumable') unless effect

      current = inventory_item_quantity(campaign_id, character_id, item_id)
      raise HttpError.new(409, 'no held quantity of this item to consume') if current.zero?

      total = current - 1
      if total.zero?
        Database.exec(<<~SQL)
          DELETE FROM play_inventory_items
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      else
        Database.exec(<<~SQL)
          UPDATE play_inventory_items SET quantity = #{Database.int(total)}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      end

      [200, { character_id: character_id, item_id: item_id, quantity_consumed: 1, total_quantity: total, effect: effect }]
    end

    def equipped_item(campaign_id, character_id, slot)
      Database.query(<<~SQL).first
        SELECT item_id, attuned FROM play_equipment
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND slot = #{Database.escape(slot)};
      SQL
    end

    # Equips an inventory item into an equipment slot. Only the character's
    # owning player may call it. The item must be held in the character's
    # inventory and must match its legal slot.
    def equip_item(actor, campaign_id, character_id, slot, body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may equip items") unless member['owner'] == actor[:username]
      raise HttpError.new(400, 'unknown equipment slot') unless EQUIPMENT_SLOTS.include?(slot)

      item_id = body['item_id']
      raise HttpError.new(400, 'item_id must be a known catalog item') unless ITEM_SLOTS.key?(item_id)
      raise HttpError.new(400, 'item_id does not match this equipment slot') unless ITEM_SLOTS[item_id] == slot
      raise HttpError.new(400, 'item must be held in the character inventory') if inventory_item_quantity(campaign_id, character_id, item_id).zero?

      Database.exec(<<~SQL)
        INSERT INTO play_equipment (campaign_id, character_id, slot, item_id, attuned)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(slot)}, #{Database.escape(item_id)}, 0)
        ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = #{Database.escape(item_id)}, attuned = 0;
      SQL

      [200, { character_id: character_id, slot: slot, item_id: item_id, attuned: false }]
    end

    # Returns the item equipped in a slot. Any campaign member may view it.
    def get_equipment(actor, campaign_id, character_id, slot, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view equipment') unless is_owner || member?(campaign_id, actor[:username])
      raise HttpError.new(400, 'unknown equipment slot') unless EQUIPMENT_SLOTS.include?(slot)

      find_character_member(campaign_id, character_id)

      row = equipped_item(campaign_id, character_id, slot)

      [200, {
        character_id: character_id,
        slot: slot,
        item_id: row ? row['item_id'] : '',
        attuned: row ? row['attuned'].to_i == 1 : false
      }]
    end

    # Attunes to an equipped accessory. Only the character's owning player
    # may call it. Only one item may be attuned per character at a time.
    def attune_equipment(actor, campaign_id, character_id, slot, _body)
      find_play_campaign(campaign_id)
      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may attune items") unless member['owner'] == actor[:username]
      raise HttpError.new(400, 'unknown equipment slot') unless EQUIPMENT_SLOTS.include?(slot)

      row = equipped_item(campaign_id, character_id, slot)
      raise HttpError.new(400, 'slot must contain an equipped attunable item') unless row && ATTUNABLE_ITEMS.include?(row['item_id'])

      attuned_count = Database.query(<<~SQL).first['count'].to_i
        SELECT COUNT(*) AS count FROM play_equipment
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND attuned = 1;
      SQL
      raise HttpError.new(409, 'character already has an attuned item') if attuned_count >= MAX_ATTUNEMENTS

      Database.exec(<<~SQL)
        UPDATE play_equipment SET attuned = 1
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND slot = #{Database.escape(slot)};
      SQL

      [200, {
        character_id: character_id,
        slot: slot,
        item_id: row['item_id'],
        attuned: true,
        attunement_count: 1,
        max_attunements: MAX_ATTUNEMENTS
      }]
    end

    # Returns a character's current gold balance. Any campaign member (the
    # owning dm or a party member) may view it.
    def currency(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view currency') unless is_owner || member?(campaign_id, actor[:username])

      member = find_character_member(campaign_id, character_id)

      [200, { character_id: character_id, gold: member['gold'].to_i }]
    end

    # Transfers gold from one character to another within the same
    # campaign. Only the source character's owning player may call it. The
    # debit and credit are applied atomically, and a deterministic
    # campaign-local transfer id (starting at 1) is assigned.
    def create_currency_transfer(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)
      source = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner may transfer gold") unless source['owner'] == actor[:username]

      to_character_id = body['to_character_id']
      gold = body['gold']

      raise HttpError.new(400, 'to_character_id must be a string') unless to_character_id.is_a?(String) && !to_character_id.empty?
      raise HttpError.new(400, 'to_character_id must be a different character') if to_character_id == character_id
      raise HttpError.new(400, 'gold must be a positive integer') unless gold.is_a?(Integer) && gold.positive?

      destination_row = Database.query(<<~SQL).first
        SELECT owner FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
      SQL
      raise HttpError.new(400, 'to_character_id must be a known campaign character') unless destination_row

      from_gold_before = source['gold'].to_i
      raise HttpError.new(409, 'insufficient gold for this transfer') if gold > from_gold_before

      from_gold = from_gold_before - gold
      to_gold_before = Database.query(<<~SQL).first['gold'].to_i
        SELECT gold FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
      SQL
      to_gold = to_gold_before + gold

      transfer_id = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COUNT(*) AS n FROM play_currency_transfers
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        UPDATE play_members SET gold = #{Database.int(from_gold)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
        UPDATE play_members SET gold = #{Database.int(to_gold)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
        INSERT INTO play_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(transfer_id)},
          #{Database.escape(character_id)},
          #{Database.escape(to_character_id)},
          #{Database.int(gold)}
        );
      SQL

      [201, {
        from_character_id: character_id,
        to_character_id: to_character_id,
        gold: gold,
        from_gold: from_gold,
        to_gold: to_gold,
        transfer_id: transfer_id
      }]
    end

    def find_loot(campaign_id, loot_id)
      row = Database.query(<<~SQL).first
        SELECT loot_id, item_id, quantity, status, recipient_character_id
        FROM play_loot
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)};
      SQL
      raise HttpError.new(404, 'unknown loot id') unless row

      row
    end

    def loot_votes(campaign_id, loot_id)
      Database.query(<<~SQL)
        SELECT voter, recipient_character_id FROM play_loot_votes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)};
      SQL
    end

    def loot_view(row, votes)
      tallies = Hash.new(0)
      votes.each { |v| tallies[v['recipient_character_id']] += 1 }

      {
        loot_id: row['loot_id'],
        item_id: row['item_id'],
        quantity: row['quantity'].to_i,
        status: row['status'],
        recipient_character_id: row['recipient_character_id'],
        votes: tallies
      }
    end

    # Creates an immutable open loot record for a campaign. Only the owning
    # dm may call it, and item_id must be a known inventory catalog item.
    def create_loot(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create loot')

      loot_id = body['loot_id']
      item_id = body['item_id']
      quantity = body['quantity']

      raise HttpError.new(400, 'loot_id must be a string') unless loot_id.is_a?(String) && !loot_id.empty?
      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      existing = Database.query(<<~SQL).first
        SELECT loot_id FROM play_loot
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)};
      SQL
      raise HttpError.new(409, 'loot_id already exists in this campaign') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(loot_id)},
          #{Database.escape(item_id)},
          #{Database.int(quantity)},
          'open',
          NULL
        );
      SQL

      [201, { loot_id: loot_id, item_id: item_id, quantity: quantity, status: 'open' }]
    end

    # Casts one immutable vote for who should receive a loot record. Only
    # authenticated campaign players may vote, and the recipient must be a
    # character in the same campaign. Each player identity may vote once
    # per loot record.
    def vote_loot(actor, campaign_id, loot_id, body)
      find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only a campaign player may vote on loot') unless actor[:role] == 'player' && member?(campaign_id, actor[:username])

      find_loot(campaign_id, loot_id)

      recipient_character_id = body['recipient_character_id']
      raise HttpError.new(400, 'recipient_character_id must be a string') unless recipient_character_id.is_a?(String) && !recipient_character_id.empty?

      recipient_row = Database.query(<<~SQL).first
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(recipient_character_id)};
      SQL
      raise HttpError.new(400, 'recipient_character_id must be a known campaign character') unless recipient_row

      existing_vote = Database.query(<<~SQL).first
        SELECT recipient_character_id FROM play_loot_votes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)} AND voter = #{Database.escape(actor[:username])};
      SQL
      raise HttpError.new(409, 'this player has already voted on this loot record') if existing_vote

      Database.exec(<<~SQL)
        INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(loot_id)},
          #{Database.escape(actor[:username])},
          #{Database.escape(recipient_character_id)}
        );
      SQL

      votes_for_recipient = Database.query(<<~SQL).first['n'].to_i
        SELECT COUNT(*) AS n FROM play_loot_votes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)}
          AND recipient_character_id = #{Database.escape(recipient_character_id)};
      SQL

      [201, {
        loot_id: loot_id,
        voter: actor[:username],
        recipient_character_id: recipient_character_id,
        votes_for_recipient: votes_for_recipient
      }]
    end

    # Assigns open loot to its single unambiguous highest-vote recipient.
    # Only the owning dm may call it. Tied or voteless loot returns 409, as
    # does a duplicate assignment attempt on already-assigned loot.
    def assign_loot(actor, campaign_id, loot_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may assign loot')

      loot = find_loot(campaign_id, loot_id)
      raise HttpError.new(409, 'loot has already been assigned') unless loot['status'] == 'open'

      votes = loot_votes(campaign_id, loot_id)
      raise HttpError.new(409, 'loot has no votes to assign from') if votes.empty?

      tallies = Hash.new(0)
      votes.each { |v| tallies[v['recipient_character_id']] += 1 }
      max_votes = tallies.values.max
      top_recipients = tallies.select { |_recipient, count| count == max_votes }.keys
      raise HttpError.new(409, 'loot recipient vote is tied') if top_recipients.size > 1

      recipient_character_id = top_recipients.first

      current_quantity = inventory_item_quantity(campaign_id, recipient_character_id, loot['item_id'])
      total_quantity = current_quantity + loot['quantity'].to_i

      Database.exec(<<~SQL)
        INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(recipient_character_id)}, #{Database.escape(loot['item_id'])}, #{Database.int(total_quantity)})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = #{Database.int(total_quantity)};
        UPDATE play_loot SET status = 'assigned', recipient_character_id = #{Database.escape(recipient_character_id)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND loot_id = #{Database.escape(loot_id)};
      SQL

      [200, {
        loot_id: loot_id,
        recipient_character_id: recipient_character_id,
        item_id: loot['item_id'],
        quantity: loot['quantity'].to_i,
        votes: max_votes,
        status: 'assigned'
      }]
    end

    # Returns the immutable loot record for any authenticated campaign
    # member (the owning dm or a party member).
    def get_loot(actor, campaign_id, loot_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view loot') unless is_owner || member?(campaign_id, actor[:username])

      loot = find_loot(campaign_id, loot_id)
      votes = loot_votes(campaign_id, loot_id)

      [200, loot_view(loot, votes)]
    end

    def find_npc(campaign_id, npc_id)
      row = Database.query(<<~SQL).first
        SELECT npc_id, name, agenda, public_status
        FROM play_npcs
        WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)};
      SQL
      raise HttpError.new(404, 'unknown npc id') unless row

      row
    end

    def npc_dm_view(row)
      {
        npc_id: row['npc_id'],
        name: row['name'],
        agenda: row['agenda'],
        public_status: row['public_status']
      }
    end

    def npc_player_view(row)
      {
        npc_id: row['npc_id'],
        name: row['name'],
        public_status: row['public_status']
      }
    end

    # Creates a DM-managed campaign NPC with a private agenda and a
    # player-visible public status. Only the owning dm may call it.
    def create_npc(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create npcs')

      npc_id = body['npc_id']
      name = body['name']
      agenda = body['agenda']
      public_status = body['public_status']

      raise HttpError.new(400, 'npc_id must be a nonempty string') unless npc_id.is_a?(String) && !npc_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'agenda must be a nonempty string') unless agenda.is_a?(String) && !agenda.empty?
      raise HttpError.new(400, 'public_status must be a nonempty string') unless public_status.is_a?(String) && !public_status.empty?

      existing = Database.query(<<~SQL).first
        SELECT npc_id FROM play_npcs
        WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)};
      SQL
      raise HttpError.new(409, 'npc_id already exists in this campaign') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(npc_id)},
          #{Database.escape(name)},
          #{Database.escape(agenda)},
          #{Database.escape(public_status)}
        );
      SQL

      [201, { npc_id: npc_id, name: name, agenda: agenda, public_status: public_status }]
    end

    # Updates an existing NPC's agenda and public status. Only the owning
    # dm may call it.
    def update_npc_agenda(actor, campaign_id, npc_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may update npc agendas')

      npc = find_npc(campaign_id, npc_id)

      agenda = body['agenda']
      public_status = body['public_status']

      raise HttpError.new(400, 'agenda must be a nonempty string') unless agenda.is_a?(String) && !agenda.empty?
      raise HttpError.new(400, 'public_status must be a nonempty string') unless public_status.is_a?(String) && !public_status.empty?

      Database.exec(<<~SQL)
        UPDATE play_npcs SET agenda = #{Database.escape(agenda)}, public_status = #{Database.escape(public_status)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)};
      SQL

      [200, { npc_id: npc_id, name: npc['name'], agenda: agenda, public_status: public_status }]
    end

    # Returns an NPC record. The owning dm sees the private agenda; other
    # authenticated campaign members see only the public shape.
    def get_npc(actor, campaign_id, npc_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view this npc') unless is_owner || member?(campaign_id, actor[:username])

      npc = find_npc(campaign_id, npc_id)

      [200, is_owner ? npc_dm_view(npc) : npc_player_view(npc)]
    end

    # Creates a campaign faction. Only the owning dm may call it.
    def create_faction(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create factions')

      faction_id = body['faction_id']
      name = body['name']

      raise HttpError.new(400, 'faction_id must be a nonempty string') unless faction_id.is_a?(String) && !faction_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?

      existing = Database.query(<<~SQL).first
        SELECT faction_id FROM play_factions
        WHERE campaign_id = #{Database.escape(campaign_id)} AND faction_id = #{Database.escape(faction_id)};
      SQL
      raise HttpError.new(409, 'faction_id already exists in this campaign') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_factions (campaign_id, faction_id, name)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(faction_id)}, #{Database.escape(name)});
      SQL

      [201, { faction_id: faction_id, name: name }]
    end

    def find_faction(campaign_id, faction_id)
      row = Database.query(<<~SQL).first
        SELECT faction_id, name FROM play_factions
        WHERE campaign_id = #{Database.escape(campaign_id)} AND faction_id = #{Database.escape(faction_id)};
      SQL
      raise HttpError.new(404, 'unknown faction id') unless row

      row
    end

    # Changes a character's reputation with a faction, bounded to
    # [-100,100], and appends an immutable history record. Only the owning
    # dm may call it.
    def update_faction_reputation(actor, campaign_id, faction_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may change faction reputation')

      find_faction(campaign_id, faction_id)

      character_id = body['character_id']
      delta = body['delta']
      reason = body['reason']

      raise HttpError.new(400, 'character_id must be a nonempty string') unless character_id.is_a?(String) && !character_id.empty?
      begin
        find_character_member(campaign_id, character_id)
      rescue HttpError
        raise HttpError.new(400, 'character_id must identify a campaign member character')
      end
      raise HttpError.new(400, 'delta must be a nonzero integer in [-25,25]') unless delta.is_a?(Integer) && delta != 0 && delta >= -25 && delta <= 25
      raise HttpError.new(400, 'reason must be a nonempty string') unless reason.is_a?(String) && !reason.empty?

      current = Database.query(<<~SQL).first
        SELECT reputation FROM play_faction_reputation
        WHERE campaign_id = #{Database.escape(campaign_id)} AND faction_id = #{Database.escape(faction_id)} AND character_id = #{Database.escape(character_id)};
      SQL
      current_reputation = current ? current['reputation'].to_i : 0
      new_reputation = [[current_reputation + delta, -100].max, 100].min

      Database.exec(<<~SQL)
        INSERT INTO play_faction_reputation (campaign_id, faction_id, character_id, reputation)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(faction_id)}, #{Database.escape(character_id)}, #{Database.int(new_reputation)})
        ON CONFLICT(campaign_id, faction_id, character_id) DO UPDATE SET reputation = #{Database.int(new_reputation)};
        INSERT INTO play_faction_reputation_history (campaign_id, faction_id, character_id, reputation, delta, reason)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(faction_id)},
          #{Database.escape(character_id)},
          #{Database.int(new_reputation)},
          #{Database.int(delta)},
          #{Database.escape(reason)}
        );
      SQL

      [201, {
        faction_id: faction_id,
        character_id: character_id,
        reputation: new_reputation,
        delta: delta,
        reason: reason
      }]
    end

    # Returns faction reputation history. The owning dm sees every entry;
    # a player sees only entries for their own campaign character.
    def faction_reputation_history(actor, campaign_id, faction_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view faction reputation') unless is_owner || member?(campaign_id, actor[:username])

      find_faction(campaign_id, faction_id)

      rows = if is_owner
               Database.query(<<~SQL)
                 SELECT faction_id, character_id, reputation, delta, reason FROM play_faction_reputation_history
                 WHERE campaign_id = #{Database.escape(campaign_id)} AND faction_id = #{Database.escape(faction_id)}
                 ORDER BY id ASC;
               SQL
             else
               membership = Database.query(<<~SQL).first
                 SELECT character_id FROM play_members
                 WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
               SQL
               character_id = membership ? membership['character_id'] : nil
               Database.query(<<~SQL)
                 SELECT faction_id, character_id, reputation, delta, reason FROM play_faction_reputation_history
                 WHERE campaign_id = #{Database.escape(campaign_id)} AND faction_id = #{Database.escape(faction_id)}
                   AND character_id = #{Database.escape(character_id.to_s)}
                 ORDER BY id ASC;
               SQL
             end

      entries = rows.map do |row|
        {
          faction_id: row['faction_id'],
          character_id: row['character_id'],
          reputation: row['reputation'].to_i,
          delta: row['delta'].to_i,
          reason: row['reason']
        }
      end

      [200, { faction_id: faction_id, entries: entries }]
    end

    VISIBILITIES = %w[public private].freeze

    # Appends an attributed dialogue entry to an NPC's history. Only the
    # owning dm may call it.
    def create_npc_dialogue(actor, campaign_id, npc_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may append npc dialogue')

      find_npc(campaign_id, npc_id)

      dialogue_id = body['dialogue_id']
      speaker = body['speaker']
      text = body['text']
      visibility = body['visibility']

      raise HttpError.new(400, 'dialogue_id must be a nonempty string') unless dialogue_id.is_a?(String) && !dialogue_id.empty?
      raise HttpError.new(400, 'speaker must be a nonempty string') unless speaker.is_a?(String) && !speaker.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'visibility must be public or private') unless VISIBILITIES.include?(visibility)

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_npc_dialogue
        WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)} AND dialogue_id = #{Database.escape(dialogue_id)};
      SQL
      raise HttpError.new(409, 'dialogue_id already exists for this npc') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(npc_id)},
          #{Database.escape(dialogue_id)},
          #{Database.escape(speaker)},
          #{Database.escape(text)},
          #{Database.escape(visibility)}
        );
      SQL

      [201, { dialogue_id: dialogue_id, speaker: speaker, text: text, visibility: visibility }]
    end

    # Returns an NPC's dialogue history. The owning dm sees every entry;
    # other authenticated campaign members see only public entries.
    def npc_dialogue_history(actor, campaign_id, npc_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view npc dialogue') unless is_owner || member?(campaign_id, actor[:username])

      find_npc(campaign_id, npc_id)

      rows = if is_owner
               Database.query(<<~SQL)
                 SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue
                 WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)}
                 ORDER BY id ASC;
               SQL
             else
               Database.query(<<~SQL)
                 SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue
                 WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(npc_id)} AND visibility = 'public'
                 ORDER BY id ASC;
               SQL
             end

      entries = rows.map do |row|
        {
          dialogue_id: row['dialogue_id'],
          speaker: row['speaker'],
          text: row['text'],
          visibility: row['visibility']
        }
      end

      [200, { npc_id: npc_id, entries: entries }]
    end

    def campaign_entity?(campaign_id, entity_id)
      member_row = Database.query(<<~SQL).first
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(entity_id)};
      SQL
      return true if member_row

      npc_row = Database.query(<<~SQL).first
        SELECT npc_id FROM play_npcs
        WHERE campaign_id = #{Database.escape(campaign_id)} AND npc_id = #{Database.escape(entity_id)};
      SQL
      !npc_row.nil?
    end

    def relationship_view(row)
      {
        source_id: row['source_id'],
        target_id: row['target_id'],
        kind: row['kind'],
        score: row['score'].to_i
      }
    end

    # Creates a directed relationship edge between two campaign entities
    # (campaign member characters and npcs). Only the owning dm may call it.
    def create_relationship(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create relationship edges')

      source_id = body['source_id']
      target_id = body['target_id']
      kind = body['kind']
      score = body['score']

      raise HttpError.new(400, 'source_id must be a nonempty string') unless source_id.is_a?(String) && !source_id.empty?
      raise HttpError.new(400, 'target_id must be a nonempty string') unless target_id.is_a?(String) && !target_id.empty?
      raise HttpError.new(400, 'source_id and target_id must differ') if source_id == target_id
      raise HttpError.new(400, 'kind must be a nonempty string') unless kind.is_a?(String) && !kind.empty?
      raise HttpError.new(400, 'score must be an integer from -100 through 100') unless score.is_a?(Integer) && score >= -100 && score <= 100

      raise HttpError.new(404, 'unknown source_id') unless campaign_entity?(campaign_id, source_id)
      raise HttpError.new(404, 'unknown target_id') unless campaign_entity?(campaign_id, target_id)

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_relationships
        WHERE campaign_id = #{Database.escape(campaign_id)} AND source_id = #{Database.escape(source_id)}
          AND target_id = #{Database.escape(target_id)} AND kind = #{Database.escape(kind)};
      SQL
      raise HttpError.new(409, 'relationship edge already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(source_id)},
          #{Database.escape(target_id)},
          #{Database.escape(kind)},
          #{Database.int(score)}
        );
      SQL

      [201, { source_id: source_id, target_id: target_id, kind: kind, score: score }]
    end

    # Updates the score of an existing relationship edge. Only the owning dm
    # may call it.
    def update_relationship(actor, campaign_id, source_id, target_id, kind, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may update relationship edges')

      existing = Database.query(<<~SQL).first
        SELECT source_id, target_id, kind, score FROM play_relationships
        WHERE campaign_id = #{Database.escape(campaign_id)} AND source_id = #{Database.escape(source_id)}
          AND target_id = #{Database.escape(target_id)} AND kind = #{Database.escape(kind)};
      SQL
      raise HttpError.new(404, 'unknown relationship edge') unless existing

      score = body['score']
      raise HttpError.new(400, 'score must be an integer from -100 through 100') unless score.is_a?(Integer) && score >= -100 && score <= 100

      Database.exec(<<~SQL)
        UPDATE play_relationships SET score = #{Database.int(score)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND source_id = #{Database.escape(source_id)}
          AND target_id = #{Database.escape(target_id)} AND kind = #{Database.escape(kind)};
      SQL

      [200, { source_id: source_id, target_id: target_id, kind: kind, score: score }]
    end

    # Lists all relationship edges for a campaign in insertion order.
    # Available to authenticated campaign members and the owning dm.
    def list_relationships(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view relationships') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT source_id, target_id, kind, score FROM play_relationships
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      [200, { edges: rows.map { |row| relationship_view(row) } }]
    end

    VALID_CLUE_AUDIENCES = %w[character party hidden].freeze

    def clue_view(row)
      view = { clue_id: row['clue_id'], text: row['text'], audience: row['audience'] }
      view[:character_id] = row['character_id'] if row['audience'] == 'character'
      view
    end

    # Creates a campaign clue. Only the owning dm may call it. Clues may be
    # scoped to a single character, the whole party, or hidden from players
    # entirely.
    def create_clue(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create clues')

      clue_id = body['clue_id']
      text = body['text']
      audience = body['audience']
      character_id = body['character_id']

      raise HttpError.new(400, 'clue_id must be a nonempty string') unless clue_id.is_a?(String) && !clue_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'audience must be one of character, party, hidden') unless VALID_CLUE_AUDIENCES.include?(audience)

      if audience == 'character'
        raise HttpError.new(400, 'character_id is required for character audience') unless character_id.is_a?(String) && !character_id.empty?
        raise HttpError.new(400, 'unknown character_id') unless find_play_member_by_character(campaign_id, character_id)
      else
        raise HttpError.new(400, 'character_id must be omitted unless audience is character') unless character_id.nil?
      end

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_clues
        WHERE campaign_id = #{Database.escape(campaign_id)} AND clue_id = #{Database.escape(clue_id)};
      SQL
      raise HttpError.new(409, 'clue_id already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(clue_id)},
          #{Database.escape(text)},
          #{Database.escape(audience)},
          #{character_id.nil? ? 'NULL' : Database.escape(character_id)}
        );
      SQL

      result = { clue_id: clue_id, text: text, audience: audience }
      result[:character_id] = character_id if audience == 'character'
      [201, result]
    end

    def find_play_member_by_character(campaign_id, character_id)
      Database.query(<<~SQL).first
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL
    end

    # Lists clues visible to the requesting actor. The dm sees every clue in
    # insertion order; a player sees party clues and clues targeted to their
    # own character only.
    def list_clues(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view clues') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT clue_id, text, audience, character_id FROM play_clues
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      unless is_owner
        own_member = Database.query(<<~SQL).first
          SELECT character_id FROM play_members
          WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
        SQL
        own_character_id = own_member ? own_member['character_id'] : nil

        rows = rows.select do |row|
          row['audience'] == 'party' || (row['audience'] == 'character' && row['character_id'] == own_character_id)
        end
      end

      [200, { clues: rows.map { |row| clue_view(row) } }]
    end

    def quest_view(row)
      { quest_id: row['quest_id'], title: row['title'], depends_on: JSON.parse(row['depends_on_json']), state: row['state'] }
    end

    def find_play_quest(campaign_id, quest_id)
      Database.query(<<~SQL).first
        SELECT quest_id, title, depends_on_json, state, rewards_json, rewards_awarded FROM play_quests
        WHERE campaign_id = #{Database.escape(campaign_id)} AND quest_id = #{Database.escape(quest_id)};
      SQL
    end

    # Creates a campaign quest, locked by default. Only the owning dm may
    # call it. depends_on must reference existing quests in the same
    # campaign and must not include the quest's own id.
    def create_quest(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create quests')

      quest_id = body['quest_id']
      title = body['title']
      depends_on = body['depends_on']

      raise HttpError.new(400, 'quest_id must be a nonempty string') unless quest_id.is_a?(String) && !quest_id.empty?
      raise HttpError.new(400, 'title must be a nonempty string') unless title.is_a?(String) && !title.empty?
      raise HttpError.new(400, 'depends_on must be a JSON array of unique quest ids') unless depends_on.is_a?(Array) && depends_on.all? { |d| d.is_a?(String) && !d.empty? } && depends_on.uniq.length == depends_on.length
      raise HttpError.new(400, 'depends_on cannot include the quest\'s own id') if depends_on.include?(quest_id)
      depends_on.each do |dep|
        raise HttpError.new(400, 'depends_on must reference existing quests in the same campaign') unless find_play_quest(campaign_id, dep)
      end

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_quests
        WHERE campaign_id = #{Database.escape(campaign_id)} AND quest_id = #{Database.escape(quest_id)};
      SQL
      raise HttpError.new(409, 'quest_id already exists') if existing

      Database.exec(<<~SQL)
        INSERT INTO play_quests (campaign_id, quest_id, title, depends_on_json, state)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(quest_id)},
          #{Database.escape(title)},
          #{Database.escape(JSON.generate(depends_on))},
          'locked'
        );
      SQL

      [201, { quest_id: quest_id, title: title, depends_on: depends_on, state: 'locked' }]
    end

    VALID_QUEST_STATES = %w[active completed].freeze

    # Transitions a quest's state. Only the owning dm may call it.
    # locked -> active requires every dependency to be completed;
    # active -> completed is unconditional; all other transitions 409.
    def update_quest_state(actor, campaign_id, quest_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may change quest state')

      quest = find_play_quest(campaign_id, quest_id)
      raise HttpError.new(404, 'unknown quest id') unless quest

      state = body['state']
      raise HttpError.new(400, 'state must be exactly active or completed') unless VALID_QUEST_STATES.include?(state)

      current_state = quest['state']
      depends_on = JSON.parse(quest['depends_on_json'])

      if state == 'active'
        raise HttpError.new(409, 'quest must be locked to become active') unless current_state == 'locked'
        all_deps_completed = depends_on.all? do |dep|
          dep_row = find_play_quest(campaign_id, dep)
          dep_row && dep_row['state'] == 'completed'
        end
        raise HttpError.new(409, 'all dependencies must be completed before this quest can become active') unless all_deps_completed
      else
        raise HttpError.new(409, 'quest must be active to become completed') unless current_state == 'active'
      end

      Database.exec(<<~SQL)
        UPDATE play_quests SET state = #{Database.escape(state)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND quest_id = #{Database.escape(quest_id)};
      SQL

      result = { quest_id: quest_id, title: quest['title'], depends_on: depends_on, state: state }
      result[:rewards] = reward_view(JSON.parse(quest['rewards_json'])) if quest['rewards_json']

      [200, result]
    end

    # Lists all quests for a campaign in creation order. Available to the
    # owning dm and authenticated campaign members.
    def list_quests(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view quests') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT quest_id, title, depends_on_json, state FROM play_quests
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      [200, { quests: rows.map { |row| quest_view(row) } }]
    end

    QUEST_REWARD_CONFIGURABLE_STATES = %w[locked active].freeze

    def reward_view(rewards)
      { xp: rewards['xp'], items: rewards['items'] }
    end

    # Configures the once-awardable XP/item rewards for a quest. Only the
    # owning dm may configure rewards, and the quest must still be locked or
    # active; a completed quest rejects reconfiguration.
    def configure_quest_rewards(actor, campaign_id, quest_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may configure quest rewards')

      quest = find_play_quest(campaign_id, quest_id)
      raise HttpError.new(404, 'unknown quest id') unless quest
      raise HttpError.new(409, 'quest rewards cannot be configured once completed') unless QUEST_REWARD_CONFIGURABLE_STATES.include?(quest['state'])

      xp = body['xp']
      items = body['items']

      raise HttpError.new(400, 'xp must be a nonnegative integer') unless xp.is_a?(Integer) && xp >= 0
      raise HttpError.new(400, 'items must be a JSON object of catalog item ids to positive integer quantities') unless items.is_a?(Hash)
      items.each do |item_id, quantity|
        unless item_id.is_a?(String) && INVENTORY_CATALOG.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
          raise HttpError.new(400, 'items must be a JSON object of catalog item ids to positive integer quantities')
        end
      end

      rewards = { 'xp' => xp, 'items' => items }

      Database.exec(<<~SQL)
        UPDATE play_quests SET rewards_json = #{Database.escape(JSON.generate(rewards))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND quest_id = #{Database.escape(quest_id)};
      SQL

      depends_on = JSON.parse(quest['depends_on_json'])
      [200, { quest_id: quest_id, title: quest['title'], depends_on: depends_on, state: quest['state'], rewards: reward_view(rewards) }]
    end

    # Grants the configured quest rewards to every campaign member, exactly
    # once. Only the owning dm may award rewards; the quest must be
    # completed and have rewards configured, and a repeat award is rejected.
    def award_quest_rewards(actor, campaign_id, quest_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may award quest rewards')

      quest = find_play_quest(campaign_id, quest_id)
      raise HttpError.new(404, 'unknown quest id') unless quest
      raise HttpError.new(409, 'quest must be completed with configured rewards to award') unless quest['state'] == 'completed' && quest['rewards_json']
      raise HttpError.new(409, 'quest rewards have already been awarded') if quest['rewards_awarded'].to_i == 1

      rewards = JSON.parse(quest['rewards_json'])
      xp = rewards['xp']
      items = rewards['items']

      members = Database.query(<<~SQL)
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      members.each do |member|
        character_id = member['character_id']
        existing = Database.query(<<~SQL).first
          SELECT xp, items_json FROM play_character_rewards
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
        SQL

        current_xp = existing ? existing['xp'].to_i : 0
        current_items = existing ? JSON.parse(existing['items_json']) : {}

        total_xp = current_xp + xp
        items.each { |item_id, quantity| current_items[item_id] = current_items.fetch(item_id, 0) + quantity }

        Database.exec(<<~SQL)
          INSERT INTO play_character_rewards (campaign_id, character_id, xp, items_json)
          VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.int(total_xp)}, #{Database.escape(JSON.generate(current_items))})
          ON CONFLICT(campaign_id, character_id) DO UPDATE SET xp = #{Database.int(total_xp)}, items_json = #{Database.escape(JSON.generate(current_items))};
        SQL

        items.each do |item_id, quantity|
          inventory_total = inventory_item_quantity(campaign_id, character_id, item_id) + quantity
          Database.exec(<<~SQL)
            INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity)
            VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(item_id)}, #{Database.int(inventory_total)})
            ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = #{Database.int(inventory_total)};
          SQL
        end
      end

      Database.exec(<<~SQL)
        UPDATE play_quests SET rewards_awarded = 1
        WHERE campaign_id = #{Database.escape(campaign_id)} AND quest_id = #{Database.escape(quest_id)};
      SQL

      [201, { quest_id: quest_id, awarded: true, xp: xp, items: items }]
    end

    # Returns cumulative quest reward grants for a character. Available to
    # the owning dm and authenticated campaign members.
    def character_rewards(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view character rewards') unless is_owner || member?(campaign_id, actor[:username])

      find_character_member(campaign_id, character_id)

      row = Database.query(<<~SQL).first
        SELECT xp, items_json FROM play_character_rewards
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      xp = row ? row['xp'].to_i : 0
      items = row ? JSON.parse(row['items_json']) : {}

      [200, { character_id: character_id, xp: xp, items: items }]
    end

    def world_event_view(row)
      result = {
        event_id: row['event_id'],
        turn_number: row['turn_number'].to_i,
        title: row['title'],
        text: row['text'],
        status: row['status']
      }

      if row['status'] == 'resolved'
        result[:resolution] = { turn_number: row['resolution_turn_number'].to_i, text: row['resolution_text'] }
      end

      result
    end

    def find_play_world_event(campaign_id, event_id)
      Database.query(<<~SQL).first
        SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text
        FROM play_world_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
    end

    # Schedules a deterministic campaign-level world event for a future (or
    # current) campaign turn. Only the owning dm may schedule world events.
    def create_world_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may schedule world events')

      event_id = body['event_id']
      turn_number = body['turn_number']
      title = body['title']
      text = body['text']

      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'title must be a nonempty string') unless title.is_a?(String) && !title.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'turn_number must be an integer greater than or equal to the campaign\'s current turn_number') unless turn_number.is_a?(Integer) && turn_number >= campaign['turn_number'].to_i

      raise HttpError.new(409, 'event_id already exists') if find_play_world_event(campaign_id, event_id)

      Database.exec(<<~SQL)
        INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text, status)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(event_id)},
          #{Database.int(turn_number)},
          #{Database.escape(title)},
          #{Database.escape(text)},
          'scheduled'
        );
      SQL

      [201, { event_id: event_id, turn_number: turn_number, title: title, text: text, status: 'scheduled' }]
    end

    # Resolves a scheduled world event exactly once, at the campaign turn it
    # was scheduled for. Only the owning dm may resolve world events.
    def resolve_world_event(actor, campaign_id, event_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may resolve world events')

      event = find_play_world_event(campaign_id, event_id)
      raise HttpError.new(404, 'unknown event id') unless event

      resolution_text = body['text']
      raise HttpError.new(400, 'text must be a nonempty string') unless resolution_text.is_a?(String) && !resolution_text.empty?

      raise HttpError.new(409, 'world event is already resolved') if event['status'] == 'resolved'
      raise HttpError.new(409, 'campaign turn_number must exactly match the event turn_number to resolve') unless campaign['turn_number'].to_i == event['turn_number'].to_i

      Database.exec(<<~SQL)
        UPDATE play_world_events
        SET status = 'resolved', resolution_turn_number = #{Database.int(event['turn_number'].to_i)}, resolution_text = #{Database.escape(resolution_text)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL

      [201, {
        event_id: event['event_id'],
        turn_number: event['turn_number'].to_i,
        title: event['title'],
        text: event['text'],
        status: 'resolved',
        resolution: { turn_number: event['turn_number'].to_i, text: resolution_text }
      }]
    end

    # Lists a campaign's world events ordered by turn_number ascending, then
    # creation order. Available to the owning dm and authenticated campaign
    # members.
    def list_world_events(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view world events') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text
        FROM play_world_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY turn_number ASC, id ASC;
      SQL

      [200, { events: rows.map { |row| world_event_view(row) } }]
    end

    def turn_queue(campaign_id)
      members = Database.query(<<~SQL)
        SELECT username FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY rowid ASC;
      SQL

      members.each_with_index.flat_map do |_member, index|
        ["player-#{('a'.ord + index).chr}", 'dm']
      end
    end

    SEASON_OFFSETS = { 'spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3 }.freeze
    WEATHER_BY_OFFSET = { 0 => 'clear', 1 => 'rain', 2 => 'wind', 3 => 'snow' }.freeze

    def find_play_calendar(campaign_id)
      Database.query(<<~SQL).first
        SELECT day, season FROM play_calendars WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def weather_for(day, season)
      WEATHER_BY_OFFSET.fetch((day + SEASON_OFFSETS.fetch(season)) % 4)
    end

    def calendar_view(row)
      day = row['day'].to_i
      season = row['season']
      { day: day, season: season, weather: weather_for(day, season) }
    end

    # Initializes a campaign's calendar exactly once. Only the owning dm may
    # do this; the seed day/season also produce the initial deterministic
    # weather in the response.
    def create_calendar(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may initialize the calendar')

      day = body['day']
      season = body['season']

      raise HttpError.new(400, 'day must be an integer greater than or equal to 1') unless day.is_a?(Integer) && day >= 1
      raise HttpError.new(400, 'season must be one of spring, summer, autumn, winter') unless SEASON_OFFSETS.key?(season)

      raise HttpError.new(409, 'calendar is already initialized') if find_play_calendar(campaign_id)

      Database.exec(<<~SQL)
        INSERT INTO play_calendars (campaign_id, day, season)
        VALUES (#{Database.escape(campaign_id)}, #{Database.int(day)}, #{Database.escape(season)});
      SQL

      [201, calendar_view({ 'day' => day, 'season' => season })]
    end

    # Returns the current calendar and deterministic weather. Available to
    # the owning dm and authenticated campaign members.
    def get_calendar(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view the calendar') unless is_owner || member?(campaign_id, actor[:username])

      calendar = find_play_calendar(campaign_id)
      raise HttpError.new(404, 'calendar has not been initialized') unless calendar

      [200, calendar_view(calendar)]
    end

    # Advances a campaign's calendar by a bounded number of days. Only the
    # owning dm may advance the calendar.
    def advance_calendar(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may advance the calendar')

      days = body['days']
      raise HttpError.new(400, 'days must be an integer from 1 through 30') unless days.is_a?(Integer) && days >= 1 && days <= 30

      calendar = find_play_calendar(campaign_id)
      raise HttpError.new(404, 'calendar has not been initialized') unless calendar

      new_day = calendar['day'].to_i + days

      Database.exec(<<~SQL)
        UPDATE play_calendars SET day = #{Database.int(new_day)}
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      [200, calendar_view({ 'day' => new_day, 'season' => calendar['season'] })]
    end

    VALID_SETTLEMENT_AVAILABILITY = %w[open limited closed].freeze

    def find_play_settlement(campaign_id, settlement_id)
      Database.query(<<~SQL).first
        SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_settlements
        WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)};
      SQL
    end

    # Trims each service name, rejects empty/non-string entries, and
    # requires the normalized values to be unique while preserving the
    # accepted request's order.
    def normalize_settlement_services(services)
      raise HttpError.new(400, 'services must be a nonempty array of nonempty strings') unless services.is_a?(Array) && !services.empty?

      normalized = services.map do |service|
        raise HttpError.new(400, 'services must be a nonempty array of nonempty strings') unless service.is_a?(String)

        trimmed = service.strip
        raise HttpError.new(400, 'services must be a nonempty array of nonempty strings') if trimmed.empty?

        trimmed
      end
      raise HttpError.new(400, 'services must be unique after normalization') if normalized.uniq.length != normalized.length

      normalized
    end

    def settlement_view(row, discovered_by)
      {
        settlement_id: row['settlement_id'],
        name: row['name'],
        services: JSON.parse(row['services_json']),
        availability: row['availability'],
        discovered_by: discovered_by
      }
    end

    # Creates a campaign settlement. Only the owning dm may call it.
    def create_settlement(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create settlements')

      settlement_id = body['settlement_id']
      name = body['name']
      availability = body['availability']

      raise HttpError.new(400, 'settlement_id must be a nonempty string') unless settlement_id.is_a?(String) && !settlement_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      normalized_services = normalize_settlement_services(body['services'])
      raise HttpError.new(400, 'availability must be one of open, limited, closed') unless VALID_SETTLEMENT_AVAILABILITY.include?(availability)

      raise HttpError.new(409, 'settlement_id already exists') if find_play_settlement(campaign_id, settlement_id)

      Database.exec(<<~SQL)
        INSERT INTO play_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(settlement_id)},
          #{Database.escape(name)},
          #{Database.escape(JSON.generate(normalized_services))},
          #{Database.escape(availability)},
          '[]'
        );
      SQL

      [201, { settlement_id: settlement_id, name: name, services: normalized_services, availability: availability, discovered_by: [] }]
    end

    # Replaces a settlement's name, services, and availability. Only the
    # owning dm may call it; discovered_by is preserved as-is.
    def update_settlement(actor, campaign_id, settlement_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may update settlements')

      settlement = find_play_settlement(campaign_id, settlement_id)
      raise HttpError.new(404, 'unknown settlement id') unless settlement

      name = body['name']
      availability = body['availability']

      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      normalized_services = normalize_settlement_services(body['services'])
      raise HttpError.new(400, 'availability must be one of open, limited, closed') unless VALID_SETTLEMENT_AVAILABILITY.include?(availability)

      Database.exec(<<~SQL)
        UPDATE play_settlements
        SET name = #{Database.escape(name)},
            services_json = #{Database.escape(JSON.generate(normalized_services))},
            availability = #{Database.escape(availability)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)};
      SQL

      [200, {
        settlement_id: settlement_id,
        name: name,
        services: normalized_services,
        availability: availability,
        discovered_by: JSON.parse(settlement['discovered_by_json'])
      }]
    end

    # Records the acting player's own character as having discovered a
    # settlement. Idempotent: repeating the same discovery does not append a
    # duplicate and returns 200 instead of 201.
    def discover_settlement(actor, campaign_id, settlement_id, _body)
      find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only a joined party player may discover settlements') unless actor[:role] == 'player'

      member = Database.query(<<~SQL).first
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
      SQL
      raise HttpError.new(403, 'only a joined party player may discover settlements') unless member

      settlement = find_play_settlement(campaign_id, settlement_id)
      raise HttpError.new(404, 'unknown settlement id') unless settlement

      character_id = member['character_id']
      discovered_by = JSON.parse(settlement['discovered_by_json'])

      if discovered_by.include?(character_id)
        [200, settlement_view(settlement, [character_id])]
      else
        discovered_by << character_id
        Database.exec(<<~SQL)
          UPDATE play_settlements SET discovered_by_json = #{Database.escape(JSON.generate(discovered_by))}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)};
        SQL

        [201, settlement_view(settlement, [character_id])]
      end
    end

    # Lists a campaign's settlements in creation order. The owning dm sees
    # every settlement with its full discovered_by list; a player sees only
    # settlements their own character has discovered, with discovered_by
    # limited to their own character id.
    def list_settlements(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view settlements') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_settlements
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      if is_owner
        settlements = rows.map { |row| settlement_view(row, JSON.parse(row['discovered_by_json'])) }
      else
        own_member = Database.query(<<~SQL).first
          SELECT character_id FROM play_members
          WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
        SQL
        own_character_id = own_member ? own_member['character_id'] : nil

        settlements = rows.filter_map do |row|
          discovered_by = JSON.parse(row['discovered_by_json'])
          next unless own_character_id && discovered_by.include?(own_character_id)

          settlement_view(row, [own_character_id])
        end
      end

      [200, { settlements: settlements }]
    end

    def find_play_shop(campaign_id, settlement_id, shop_id)
      Database.query(<<~SQL).first
        SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_shops
        WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)}
          AND shop_id = #{Database.escape(shop_id)};
      SQL
    end

    # Validates a shop stock payload: a nonempty JSON object mapping known
    # inventory catalog item ids to positive integer quantities.
    def normalize_shop_stock(stock)
      raise HttpError.new(400, 'stock must be a nonempty object of catalog item ids to positive integer quantities') unless stock.is_a?(Hash) && !stock.empty?

      stock.each do |item_id, quantity|
        raise HttpError.new(400, 'stock must be a nonempty object of catalog item ids to positive integer quantities') unless INVENTORY_CATALOG.include?(item_id)
        raise HttpError.new(400, 'stock must be a nonempty object of catalog item ids to positive integer quantities') unless quantity.is_a?(Integer) && quantity.positive?
      end

      stock
    end

    def shop_view(row)
      {
        shop_id: row['shop_id'],
        name: row['name'],
        stock: JSON.parse(row['stock_json']),
        buy_price: row['buy_price'].to_i,
        sell_price: row['sell_price'].to_i
      }
    end

    # Creates a shop within a settlement. Only the owning dm may call it,
    # and shop ids must be unique within the settlement.
    def create_shop(actor, campaign_id, settlement_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create shops')

      settlement = find_play_settlement(campaign_id, settlement_id)
      raise HttpError.new(404, 'unknown settlement id') unless settlement

      shop_id = body['shop_id']
      name = body['name']
      buy_price = body['buy_price']
      sell_price = body['sell_price']

      raise HttpError.new(400, 'shop_id must be a nonempty string') unless shop_id.is_a?(String) && !shop_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      normalized_stock = normalize_shop_stock(body['stock'])
      raise HttpError.new(400, 'buy_price must be a positive integer') unless buy_price.is_a?(Integer) && buy_price.positive?
      raise HttpError.new(400, 'sell_price must be a nonnegative integer') unless sell_price.is_a?(Integer) && !sell_price.negative?

      raise HttpError.new(409, 'shop_id already exists in this settlement') if find_play_shop(campaign_id, settlement_id, shop_id)

      Database.exec(<<~SQL)
        INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(settlement_id)},
          #{Database.escape(shop_id)},
          #{Database.escape(name)},
          #{Database.escape(JSON.generate(normalized_stock))},
          #{Database.int(buy_price)},
          #{Database.int(sell_price)}
        );
      SQL

      [201, { shop_id: shop_id, name: name, stock: normalized_stock, buy_price: buy_price, sell_price: sell_price }]
    end

    # Reads a shop. The owning dm may always read. A player may read only
    # after their own character has discovered the containing settlement;
    # otherwise the shop appears as 404, same as if it did not exist.
    def get_shop(actor, campaign_id, settlement_id, shop_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view shops') unless is_owner || member?(campaign_id, actor[:username])

      settlement = find_play_settlement(campaign_id, settlement_id)
      raise HttpError.new(404, 'unknown settlement id') unless settlement

      shop = find_play_shop(campaign_id, settlement_id, shop_id)
      raise HttpError.new(404, 'unknown shop id') unless shop

      unless is_owner
        own_member = Database.query(<<~SQL).first
          SELECT character_id FROM play_members
          WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(actor[:username])};
        SQL
        discovered_by = JSON.parse(settlement['discovered_by_json'])
        raise HttpError.new(404, 'unknown shop id') unless own_member && discovered_by.include?(own_member['character_id'])
      end

      [200, shop_view(shop)]
    end

    # Resolves the settlement/shop pair shared by buy and sell, and verifies
    # the acting player owns character_id. Raises the same 404/403 errors
    # both routes need before validating the request-specific payload.
    def resolve_shop_trade(actor, campaign_id, settlement_id, shop_id, character_id)
      find_play_campaign(campaign_id)

      settlement = find_play_settlement(campaign_id, settlement_id)
      raise HttpError.new(404, 'unknown settlement id') unless settlement

      shop = find_play_shop(campaign_id, settlement_id, shop_id)
      raise HttpError.new(404, 'unknown shop id') unless shop

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owning player may trade with a shop") unless member['owner'] == actor[:username]

      shop
    end

    # Buys `quantity` of `item_id` from a shop for the owning player's
    # character. Debits gold, credits shop stock into the character
    # inventory, and decrements shop stock. Insufficient stock or gold
    # leaves all state untouched.
    def buy_from_shop(actor, campaign_id, settlement_id, shop_id, body)
      character_id = body['character_id']
      raise HttpError.new(400, 'character_id must be a nonempty string') unless character_id.is_a?(String) && !character_id.empty?

      shop = resolve_shop_trade(actor, campaign_id, settlement_id, shop_id, character_id)

      item_id = body['item_id']
      quantity = body['quantity']
      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      stock = JSON.parse(shop['stock_json'])
      available = stock[item_id].to_i
      raise HttpError.new(409, 'insufficient shop stock') if quantity > available

      buy_price = shop['buy_price'].to_i
      cost = buy_price * quantity

      member = find_character_member(campaign_id, character_id)
      gold_before = member['gold'].to_i
      raise HttpError.new(409, 'insufficient gold for this purchase') if cost > gold_before

      new_stock_quantity = available - quantity
      if new_stock_quantity.zero?
        stock.delete(item_id)
      else
        stock[item_id] = new_stock_quantity
      end
      gold_after = gold_before - cost
      inventory_total = inventory_item_quantity(campaign_id, character_id, item_id) + quantity

      Database.exec(<<~SQL)
        UPDATE play_shops SET stock_json = #{Database.escape(JSON.generate(stock))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)}
          AND shop_id = #{Database.escape(shop_id)};
        UPDATE play_members SET gold = #{Database.int(gold_after)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
        INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(item_id)}, #{Database.int(inventory_total)})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = #{Database.int(inventory_total)};
      SQL

      [200, { character_id: character_id, item_id: item_id, quantity: quantity, gold: gold_after, stock: new_stock_quantity }]
    end

    # Sells `quantity` of `item_id` from the owning player's character to a
    # shop. Removes the items from the character inventory, credits gold,
    # and increments shop stock. Insufficient inventory leaves all state
    # untouched.
    def sell_to_shop(actor, campaign_id, settlement_id, shop_id, body)
      character_id = body['character_id']
      raise HttpError.new(400, 'character_id must be a nonempty string') unless character_id.is_a?(String) && !character_id.empty?

      shop = resolve_shop_trade(actor, campaign_id, settlement_id, shop_id, character_id)

      item_id = body['item_id']
      quantity = body['quantity']
      raise HttpError.new(400, 'item_id must be a known catalog item') unless INVENTORY_CATALOG.include?(item_id)
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      held = inventory_item_quantity(campaign_id, character_id, item_id)
      raise HttpError.new(409, 'insufficient inventory to sell') if quantity > held

      sell_price = shop['sell_price'].to_i
      proceeds = sell_price * quantity

      member = find_character_member(campaign_id, character_id)
      gold_after = member['gold'].to_i + proceeds

      remaining_held = held - quantity

      stock = JSON.parse(shop['stock_json'])
      new_stock_quantity = stock[item_id].to_i + quantity
      stock[item_id] = new_stock_quantity

      if remaining_held.zero?
        Database.exec(<<~SQL)
          DELETE FROM play_inventory_items
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      else
        Database.exec(<<~SQL)
          UPDATE play_inventory_items SET quantity = #{Database.int(remaining_held)}
          WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
            AND item_id = #{Database.escape(item_id)};
        SQL
      end

      Database.exec(<<~SQL)
        UPDATE play_shops SET stock_json = #{Database.escape(JSON.generate(stock))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND settlement_id = #{Database.escape(settlement_id)}
          AND shop_id = #{Database.escape(shop_id)};
        UPDATE play_members SET gold = #{Database.int(gold_after)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)};
      SQL

      [200, { character_id: character_id, item_id: item_id, quantity: quantity, gold: gold_after, stock: new_stock_quantity }]
    end

    def find_play_recipe(campaign_id, recipe_id)
      Database.query(<<~SQL).first
        SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_recipes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND recipe_id = #{Database.escape(recipe_id)};
      SQL
    end

    # Validates a recipe's ingredients payload: a nonempty JSON object
    # mapping known inventory catalog item ids to positive integer
    # quantities.
    def normalize_recipe_ingredients(ingredients)
      raise HttpError.new(400, 'ingredients must be a nonempty object of catalog item ids to positive integer quantities') unless ingredients.is_a?(Hash) && !ingredients.empty?

      ingredients.each do |item_id, quantity|
        raise HttpError.new(400, 'ingredients must be a nonempty object of catalog item ids to positive integer quantities') unless INVENTORY_CATALOG.include?(item_id)
        raise HttpError.new(400, 'ingredients must be a nonempty object of catalog item ids to positive integer quantities') unless quantity.is_a?(Integer) && quantity.positive?
      end

      ingredients
    end

    def recipe_view(row)
      {
        recipe_id: row['recipe_id'],
        name: row['name'],
        ingredients: JSON.parse(row['ingredients_json']),
        output_item: row['output_item'],
        output_quantity: row['output_quantity'].to_i
      }
    end

    # Creates a crafting recipe for a campaign. Only the owning dm may
    # call it, and recipe ids must be unique within the campaign.
    def create_recipe(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create recipes')

      recipe_id = body['recipe_id']
      name = body['name']
      output_item = body['output_item']
      output_quantity = body['output_quantity']

      raise HttpError.new(400, 'recipe_id must be a nonempty string') unless recipe_id.is_a?(String) && !recipe_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'output_item must be a known catalog item') unless INVENTORY_CATALOG.include?(output_item)
      raise HttpError.new(400, 'output_quantity must be a positive integer') unless output_quantity.is_a?(Integer) && output_quantity.positive?

      ingredients = normalize_recipe_ingredients(body['ingredients'])

      raise HttpError.new(409, 'recipe_id already exists in this campaign') if find_play_recipe(campaign_id, recipe_id)

      Database.exec(<<~SQL)
        INSERT INTO play_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(recipe_id)},
          #{Database.escape(name)},
          #{Database.escape(JSON.generate(ingredients))},
          #{Database.escape(output_item)},
          #{Database.int(output_quantity)}
        );
      SQL

      [201, { recipe_id: recipe_id, name: name, ingredients: ingredients, output_item: output_item, output_quantity: output_quantity }]
    end

    # Lists a campaign's recipes in creation order. The owning dm or any
    # party member may call it.
    def list_recipes(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view recipes') unless is_owner || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_recipes
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      [200, { recipes: rows.map { |row| recipe_view(row) } }]
    end

    # Crafts a recipe for `character_id`. Only the character's owning
    # player may call it. Consumes ingredients and adds the output item
    # atomically; insufficient ingredients leave all state untouched.
    def craft_recipe(actor, campaign_id, recipe_id, body)
      find_play_campaign(campaign_id)

      recipe = find_play_recipe(campaign_id, recipe_id)
      raise HttpError.new(404, 'unknown recipe id') unless recipe

      character_id = body['character_id']
      raise HttpError.new(400, 'character_id must be a nonempty string') unless character_id.is_a?(String) && !character_id.empty?

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(404, 'unknown character id') unless member
      raise HttpError.new(403, "only the character's owning player may craft") unless member['owner'] == actor[:username]

      ingredients = JSON.parse(recipe['ingredients_json'])
      output_item = recipe['output_item']
      output_quantity = recipe['output_quantity'].to_i

      held = {}
      (ingredients.keys + [output_item]).uniq.each do |item_id|
        held[item_id] = inventory_item_quantity(campaign_id, character_id, item_id)
      end

      ingredients.each do |item_id, quantity|
        raise HttpError.new(409, 'insufficient ingredients to craft this recipe') if quantity > held[item_id]
      end

      statements = ingredients.map do |item_id, quantity|
        remaining = held[item_id] - quantity
        held[item_id] = remaining
        if remaining.zero?
          <<~SQL
            DELETE FROM play_inventory_items
            WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
              AND item_id = #{Database.escape(item_id)};
          SQL
        else
          <<~SQL
            UPDATE play_inventory_items SET quantity = #{Database.int(remaining)}
            WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
              AND item_id = #{Database.escape(item_id)};
          SQL
        end
      end

      output_total = held[output_item] + output_quantity
      statements << <<~SQL
        INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(output_item)}, #{Database.int(output_total)})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = #{Database.int(output_total)};
      SQL

      Database.exec(statements.join)

      [201, { character_id: character_id, recipe_id: recipe_id, output_item: output_item, output_quantity: output_quantity }]
    end

    def find_downtime_activity(campaign_id, activity_id)
      Database.query(<<~SQL).first
        SELECT activity_id, name, cycles_required FROM play_downtime_activities
        WHERE campaign_id = #{Database.escape(campaign_id)} AND activity_id = #{Database.escape(activity_id)};
      SQL
    end

    def find_downtime_allocation(campaign_id, character_id, activity_id)
      Database.query(<<~SQL).first
        SELECT character_id, activity_id, cycles_completed, completions FROM play_downtime_allocations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND activity_id = #{Database.escape(activity_id)};
      SQL
    end

    def downtime_activity_view(row)
      {
        activity_id: row['activity_id'],
        name: row['name'],
        cycles_required: row['cycles_required'].to_i
      }
    end

    def downtime_allocation_view(row)
      {
        character_id: row['character_id'],
        activity_id: row['activity_id'],
        cycles_completed: row['cycles_completed'].to_i,
        completions: row['completions'].to_i
      }
    end

    # Creates a recurring downtime activity for a campaign. Only the
    # owning dm may call it, and activity ids must be unique within the
    # campaign.
    def create_downtime_activity(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create downtime activities')

      activity_id = body['activity_id']
      name = body['name']
      cycles_required = body['cycles_required']

      raise HttpError.new(400, 'activity_id must be a nonempty string') unless activity_id.is_a?(String) && !activity_id.empty?
      raise HttpError.new(400, 'name must be a nonempty string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'cycles_required must be an integer from 1 through 10') unless cycles_required.is_a?(Integer) && cycles_required >= 1 && cycles_required <= 10

      raise HttpError.new(409, 'activity_id already exists in this campaign') if find_downtime_activity(campaign_id, activity_id)

      Database.exec(<<~SQL)
        INSERT INTO play_downtime_activities (campaign_id, activity_id, name, cycles_required)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(activity_id)},
          #{Database.escape(name)},
          #{Database.int(cycles_required)}
        );
      SQL

      [201, { activity_id: activity_id, name: name, cycles_required: cycles_required }]
    end

    # Allocates downtime on `activity_id` to `character_id`. Only the
    # character's owning player may call it.
    def create_downtime_allocation(actor, campaign_id, character_id, body)
      find_play_campaign(campaign_id)

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owning player may allocate downtime") unless member['owner'] == actor[:username]

      activity_id = body['activity_id']
      raise HttpError.new(400, 'activity_id must be a nonempty string') unless activity_id.is_a?(String) && !activity_id.empty?

      raise HttpError.new(404, 'unknown activity id') unless find_downtime_activity(campaign_id, activity_id)
      raise HttpError.new(409, 'an allocation already exists for this character and activity') if find_downtime_allocation(campaign_id, character_id, activity_id)

      Database.exec(<<~SQL)
        INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(character_id)}, #{Database.escape(activity_id)}, 0, 0);
      SQL

      [201, { character_id: character_id, activity_id: activity_id, cycles_completed: 0, completions: 0 }]
    end

    # Advances a character's downtime allocation by one cycle. Only the
    # character's owning player may call it. Wraps cycles_completed back
    # to 0 and increments completions once cycles_required is reached, so
    # the allocation keeps recurring.
    def progress_downtime_allocation(actor, campaign_id, character_id, activity_id, _body)
      find_play_campaign(campaign_id)

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owning player may progress downtime") unless member['owner'] == actor[:username]

      activity = find_downtime_activity(campaign_id, activity_id)
      raise HttpError.new(404, 'unknown activity id') unless activity

      allocation = find_downtime_allocation(campaign_id, character_id, activity_id)
      raise HttpError.new(404, 'unknown allocation') unless allocation

      cycles_required = activity['cycles_required'].to_i
      cycles_completed = allocation['cycles_completed'].to_i + 1
      completions = allocation['completions'].to_i

      if cycles_completed >= cycles_required
        cycles_completed = 0
        completions += 1
      end

      Database.exec(<<~SQL)
        UPDATE play_downtime_allocations
        SET cycles_completed = #{Database.int(cycles_completed)}, completions = #{Database.int(completions)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(character_id)}
          AND activity_id = #{Database.escape(activity_id)};
      SQL

      [200, { character_id: character_id, activity_id: activity_id, cycles_completed: cycles_completed, completions: completions }]
    end

    # Reads a character's downtime allocation. Any authenticated campaign
    # member may call it.
    def get_downtime_allocation(actor, campaign_id, character_id, activity_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to view downtime') unless is_owner || member?(campaign_id, actor[:username])

      raise HttpError.new(404, 'unknown character id') unless find_character_member(campaign_id, character_id)
      raise HttpError.new(404, 'unknown activity id') unless find_downtime_activity(campaign_id, activity_id)

      allocation = find_downtime_allocation(campaign_id, character_id, activity_id)
      raise HttpError.new(404, 'unknown allocation') unless allocation

      [200, downtime_allocation_view(allocation)]
    end

    def content_view(row)
      {
        content_id: row['content_id'],
        kind: row['kind'],
        text: row['text'],
        tags: JSON.parse(row['tags_json'])
      }
    end

    def find_content(campaign_id, content_id)
      Database.query(<<~SQL).first
        SELECT content_id, kind, text, tags_json FROM play_content
        WHERE campaign_id = #{Database.escape(campaign_id)} AND content_id = #{Database.escape(content_id)};
      SQL
    end

    def valid_tags?(tags)
      tags.is_a?(Array) && tags.all? { |tag| tag.is_a?(String) && !tag.empty? } && tags.uniq.length == tags.length
    end

    # Creates a campaign content record with deterministic tags. Only the
    # owning dm may create content.
    def create_content(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may create content')

      content_id = body['content_id']
      kind = body['kind']
      text = body['text']
      tags = body['tags']

      raise HttpError.new(400, 'content_id must be a nonempty string') unless content_id.is_a?(String) && !content_id.empty?
      raise HttpError.new(400, 'kind must be a nonempty string') unless kind.is_a?(String) && !kind.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'tags must be a nonempty array of unique nonempty strings') unless valid_tags?(tags) && !tags.empty?

      raise HttpError.new(409, 'content_id already exists') if find_content(campaign_id, content_id)

      Database.exec(<<~SQL)
        INSERT INTO play_content (campaign_id, content_id, kind, text, tags_json)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(content_id)}, #{Database.escape(kind)}, #{Database.escape(text)}, #{Database.escape(JSON.generate(tags))});
      SQL

      [201, { content_id: content_id, kind: kind, text: text, tags: tags }]
    end

    # Replaces a content record's tags. Only the owning dm may replace
    # tags; the replacement list may be empty.
    def replace_content_tags(actor, campaign_id, content_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may replace content tags')

      content = find_content(campaign_id, content_id)
      raise HttpError.new(404, 'unknown content id') unless content

      tags = body['tags']
      raise HttpError.new(400, 'tags must be an array of unique nonempty strings') unless valid_tags?(tags)

      Database.exec(<<~SQL)
        UPDATE play_content SET tags_json = #{Database.escape(JSON.generate(tags))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND content_id = #{Database.escape(content_id)};
      SQL

      [200, { content_id: content_id, kind: content['kind'], text: content['text'], tags: tags }]
    end

    # Lists campaign content in creation order. Players do not see records
    # tagged with the optional exclude_tag filter; the owning dm always
    # sees every record.
    def list_content(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to list content') unless is_owner || member?(campaign_id, actor[:username])

      exclude_tag = body['exclude_tag']
      raise HttpError.new(400, 'exclude_tag must be a nonempty string') if body.key?('exclude_tag') && (!exclude_tag.is_a?(String) || exclude_tag.empty?)

      rows = Database.query(<<~SQL)
        SELECT content_id, kind, text, tags_json FROM play_content
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      items = rows.map { |row| content_view(row) }
      items = items.reject { |item| item[:tags].include?(exclude_tag) } if !is_owner && exclude_tag

      [200, { content: items }]
    end

    def require_owner_or_member!(campaign, actor, campaign_id, message)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, message) unless is_owner || member?(campaign_id, actor[:username])

      is_owner
    end

    VALID_NOTE_VISIBILITIES = %w[private party].freeze

    def note_view(row)
      { note_id: row['note_id'], text: row['text'], visibility: row['visibility'], owner: row['owner'] }
    end

    def find_note(campaign_id, note_id)
      Database.query(<<~SQL).first
        SELECT note_id, text, visibility, owner FROM play_notes
        WHERE campaign_id = #{Database.escape(campaign_id)} AND note_id = #{Database.escape(note_id)};
      SQL
    end

    # Creates a campaign note owned by the requesting party member or the
    # owning dm.
    def create_note(actor, campaign_id, body)
      raise HttpError.new(401, 'spectator tokens cannot create notes') if actor[:role] == 'spectator'

      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to create notes')

      note_id = body['note_id']
      text = body['text']
      visibility = body['visibility']

      raise HttpError.new(400, 'note_id must be a nonempty string') unless note_id.is_a?(String) && !note_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'visibility must be either private or party') unless VALID_NOTE_VISIBILITIES.include?(visibility)

      raise HttpError.new(409, 'note_id already exists') if find_note(campaign_id, note_id)

      owner = actor[:username]
      Database.exec(<<~SQL)
        INSERT INTO play_notes (campaign_id, note_id, text, visibility, owner)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(note_id)}, #{Database.escape(text)}, #{Database.escape(visibility)}, #{Database.escape(owner)});
      SQL

      [201, { note_id: note_id, text: text, visibility: visibility, owner: owner }]
    end

    # Posts a party chat message, recorded as a 'chat' event. Owning dm or
    # any campaign member may post; spectator tickets cannot authenticate
    # this mutation endpoint.
    def create_message(actor, campaign_id, body)
      raise HttpError.new(401, 'spectator tokens cannot post messages') if actor[:role] == 'spectator'

      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to post messages')

      text = body['text']
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?

      sequence = record_event(campaign_id, kind: 'chat', actor: actor[:username], text: text)

      [201, { sequence: sequence, kind: 'chat', actor: actor[:username], text: text }]
    end

    # Lists campaign notes in creation order. The dm sees every note;
    # players see all party notes plus only their own private notes.
    def list_notes(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to list notes')

      rows = Database.query(<<~SQL)
        SELECT note_id, text, visibility, owner FROM play_notes
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      notes = rows.map { |row| note_view(row) }
      notes = notes.select { |note| note[:visibility] == 'party' || note[:owner] == actor[:username] } unless is_owner

      [200, { notes: notes }]
    end

    # Reads a single note. The dm may read any note; other campaign members
    # may only read party notes or their own private notes.
    def get_note(actor, campaign_id, note_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to read notes')

      note = find_note(campaign_id, note_id)
      raise HttpError.new(404, 'unknown note id') unless note

      unless is_owner || note['owner'] == actor[:username] || note['visibility'] == 'party'
        raise HttpError.new(403, 'private notes may only be read by their owner or the dm')
      end

      [200, note_view(note)]
    end

    # Updates a note's text and visibility. Only the note's owner may
    # update it; the dm may read but not override ownership.
    def update_note(actor, campaign_id, note_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to update notes')

      note = find_note(campaign_id, note_id)
      raise HttpError.new(404, 'unknown note id') unless note
      raise HttpError.new(403, 'only the note owner may update this note') unless note['owner'] == actor[:username]

      text = body['text']
      visibility = body['visibility']
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'visibility must be either private or party') unless VALID_NOTE_VISIBILITIES.include?(visibility)

      Database.exec(<<~SQL)
        UPDATE play_notes SET text = #{Database.escape(text)}, visibility = #{Database.escape(visibility)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND note_id = #{Database.escape(note_id)};
      SQL

      [200, { note_id: note_id, text: text, visibility: visibility, owner: note['owner'] }]
    end

    def whisper_view(row)
      {
        whisper_id: row['whisper_id'],
        from_character_id: row['from_character_id'],
        to_character_id: row['to_character_id'],
        text: row['text']
      }
    end

    def find_whisper(campaign_id, whisper_id)
      Database.query(<<~SQL).first
        SELECT whisper_id, from_character_id, to_character_id, text FROM play_whispers
        WHERE campaign_id = #{Database.escape(campaign_id)} AND whisper_id = #{Database.escape(whisper_id)};
      SQL
    end

    # A campaign member may own more than one character (via transfer), so
    # this returns every character_id currently owned by `username` in
    # `campaign_id`, in a deterministic order.
    def owned_character_ids(campaign_id, username)
      Database.query(<<~SQL).map { |row| row['character_id'] }
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND owner = #{Database.escape(username)}
        ORDER BY character_id ASC;
      SQL
    end

    # Sends a whisper from the requesting player's owned character to
    # another campaign member's character. from_character_id is derived
    # from the actor and cannot be chosen by the client.
    def create_whisper(actor, campaign_id, body)
      find_play_campaign(campaign_id)
      raise HttpError.new(403, 'only a campaign member may send whispers') unless member?(campaign_id, actor[:username])

      from_character_id = owned_character_ids(campaign_id, actor[:username]).first
      raise HttpError.new(403, 'must own a character in this campaign to send whispers') unless from_character_id

      whisper_id = body['whisper_id']
      to_character_id = body['to_character_id']
      text = body['text']

      raise HttpError.new(400, 'whisper_id must be a nonempty string') unless whisper_id.is_a?(String) && !whisper_id.empty?
      raise HttpError.new(400, 'to_character_id must be a nonempty string') unless to_character_id.is_a?(String) && !to_character_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?

      recipient = Database.query(<<~SQL).first
        SELECT character_id FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
      SQL
      raise HttpError.new(400, 'to_character_id must belong to a current campaign member') unless recipient

      raise HttpError.new(409, 'whisper_id already exists') if find_whisper(campaign_id, whisper_id)

      Database.exec(<<~SQL)
        INSERT INTO play_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(whisper_id)},
          #{Database.escape(from_character_id)},
          #{Database.escape(to_character_id)},
          #{Database.escape(text)}
        );
      SQL

      [201, { whisper_id: whisper_id, from_character_id: from_character_id, to_character_id: to_character_id, text: text }]
    end

    # Lists campaign whispers in creation order. The dm sees every whisper;
    # players see only whispers where one of their owned characters is
    # either the sender or the recipient.
    def list_whispers(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to list whispers')

      rows = Database.query(<<~SQL)
        SELECT whisper_id, from_character_id, to_character_id, text FROM play_whispers
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      whispers = rows.map { |row| whisper_view(row) }
      unless is_owner
        owned = owned_character_ids(campaign_id, actor[:username])
        whispers = whispers.select { |w| owned.include?(w[:from_character_id]) || owned.include?(w[:to_character_id]) }
      end

      [200, { whispers: whispers }]
    end

    # Returns a character's basic sheet. Only the character's owner and the
    # campaign dm may read it; other campaign members receive 403.
    def character_sheet(actor, campaign_id, character_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to view a character sheet')

      member = find_character_member(campaign_id, character_id)
      raise HttpError.new(403, "only the character's owner or the dm may view this sheet") unless is_owner || member['owner'] == actor[:username]

      # The basic sheet is a fixed, deterministic snapshot independent of
      # in-campaign progression (leveling, damage, equipment); it always
      # reports the baseline level-1 stats regardless of live game state.
      [200, {
        character_id: character_id,
        owner: member['owner'],
        name: member['name'],
        class: member['class'],
        level: 1,
        proficiency_bonus: GameRules.proficiency_bonus(1),
        hp_max: 10,
        armor_class: 10
      }]
    end

    def invitation_view(row)
      {
        invitation_id: row['invitation_id'],
        username: row['username'],
        character_id: row['character_id'],
        status: row['status']
      }
    end

    def find_invitation(campaign_id, invitation_id)
      Database.query(<<~SQL).first
        SELECT invitation_id, username, character_id, status FROM play_invitations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND invitation_id = #{Database.escape(invitation_id)};
      SQL
    end

    # Creates a pending invitation for a registered player identity. Only
    # the owning dm may invite; the target must be a registered player with
    # no existing pending invitation in this campaign.
    def create_invitation(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create invitations')

      invitation_id = body['invitation_id']
      username = body['username']
      character_id = body['character_id']

      raise HttpError.new(400, 'invitation_id must be a nonempty string') unless invitation_id.is_a?(String) && !invitation_id.empty?
      raise HttpError.new(400, 'username must be a nonempty string') unless username.is_a?(String) && !username.empty?
      raise HttpError.new(400, 'character_id must be a nonempty string') unless character_id.is_a?(String) && !character_id.empty?

      target = Database.query("SELECT username, role FROM users WHERE username = #{Database.escape(username)};").first
      raise HttpError.new(400, 'username must belong to a registered player') unless target && target['role'] == 'player'

      raise HttpError.new(409, 'invitation_id already exists') if find_invitation(campaign_id, invitation_id)

      duplicate_pending = Database.query(<<~SQL).first
        SELECT invitation_id FROM play_invitations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(username)} AND status = 'pending';
      SQL
      raise HttpError.new(409, 'this user already has a pending invitation in this campaign') if duplicate_pending

      Database.exec(<<~SQL)
        INSERT INTO play_invitations (campaign_id, invitation_id, username, character_id, status)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(invitation_id)},
          #{Database.escape(username)},
          #{Database.escape(character_id)},
          'pending'
        );
      SQL

      [201, { invitation_id: invitation_id, username: username, character_id: character_id, status: 'pending' }]
    end

    # Accepts a pending invitation. Only the invited username may accept;
    # accepting adds the target as a campaign member using the invitation's
    # character_id.
    def accept_invitation(actor, campaign_id, invitation_id, _body)
      find_play_campaign(campaign_id)

      invitation = find_invitation(campaign_id, invitation_id)
      raise HttpError.new(404, 'unknown invitation id') unless invitation

      raise HttpError.new(403, 'only the invited user may accept this invitation') unless invitation['username'] == actor[:username]
      raise HttpError.new(409, 'invitation has already been accepted') if invitation['status'] == 'accepted'

      Database.exec(<<~SQL)
        INSERT INTO play_members (campaign_id, username, character_id, name, class, owner)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(invitation['username'])},
          #{Database.escape(invitation['character_id'])},
          '',
          '',
          #{Database.escape(invitation['username'])}
        );
      SQL

      Database.exec(<<~SQL)
        UPDATE play_invitations SET status = 'accepted'
        WHERE campaign_id = #{Database.escape(campaign_id)} AND invitation_id = #{Database.escape(invitation_id)};
      SQL

      [200, invitation_view(invitation).merge(status: 'accepted')]
    end

    # Lists campaign invitations in creation order. The dm sees all; a
    # target user sees only invitations addressed to them (even before
    # becoming a campaign member); other campaign members see none.
    def list_invitations(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)

      rows = Database.query(<<~SQL)
        SELECT invitation_id, username, character_id, status FROM play_invitations
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      invitations = rows.map { |row| invitation_view(row) }
      invitations = invitations.select { |inv| inv[:username] == actor[:username] } unless is_owner

      [200, { invitations: invitations }]
    end

    VALID_DELEGATION_POWERS = %w[narrate].freeze

    def delegation_view(row)
      { username: row['username'], powers: JSON.parse(row['powers']), active: row['active'].to_i == 1 }
    end

    def find_delegation(campaign_id, username)
      Database.query(<<~SQL).first
        SELECT username, powers, active FROM play_delegations
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(username)};
      SQL
    end

    # True when `username` currently holds an active delegation granting
    # `power` in `campaign_id`. Used to let a delegated co-gm exercise
    # powers normally gated to the owning dm (e.g. narration).
    def active_delegate_power?(campaign_id, username, power)
      delegation = find_delegation(campaign_id, username)
      return false unless delegation && delegation['active'].to_i == 1

      JSON.parse(delegation['powers']).include?(power)
    end

    def record_delegation_audit(campaign_id, username, action, powers)
      Database.exec(<<~SQL)
        INSERT INTO play_delegation_audit (campaign_id, username, action, powers)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(username)},
          #{Database.escape(action)},
          #{Database.escape(JSON.generate(powers))}
        );
      SQL
    end

    # Grants (or re-grants, after a prior revocation) campaign-scoped co-gm
    # delegation. Only the owning dm may grant; the target must be an
    # existing campaign member and powers must be exactly the valid,
    # deduplicated set (currently just "narrate").
    def grant_delegation(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign owner may grant delegation')

      username = body['username']
      powers = body['powers']

      raise HttpError.new(400, 'username must be a nonempty string') unless username.is_a?(String) && !username.empty?
      raise HttpError.new(400, 'username must be a campaign member') unless member?(campaign_id, username)
      raise HttpError.new(400, 'powers must be a nonempty array') unless powers.is_a?(Array) && !powers.empty?
      raise HttpError.new(400, 'powers must not contain duplicates') unless powers.uniq.length == powers.length
      raise HttpError.new(400, 'powers must only contain valid values') unless powers.all? { |p| VALID_DELEGATION_POWERS.include?(p) }

      existing = find_delegation(campaign_id, username)
      raise HttpError.new(409, 'this user already has an active delegation') if existing && existing['active'].to_i == 1

      if existing
        Database.exec(<<~SQL)
          UPDATE play_delegations SET powers = #{Database.escape(JSON.generate(powers))}, active = 1
          WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(username)};
        SQL
      else
        Database.exec(<<~SQL)
          INSERT INTO play_delegations (campaign_id, username, powers, active)
          VALUES (#{Database.escape(campaign_id)}, #{Database.escape(username)}, #{Database.escape(JSON.generate(powers))}, 1);
        SQL
      end

      record_delegation_audit(campaign_id, username, 'granted', powers)

      [201, { username: username, powers: powers, active: true }]
    end

    # Revokes an existing active delegation. Only the owning dm may revoke.
    def revoke_delegation(actor, campaign_id, username, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign owner may revoke delegation')

      existing = find_delegation(campaign_id, username)
      raise HttpError.new(404, 'unknown delegation') unless existing && existing['active'].to_i == 1

      Database.exec(<<~SQL)
        UPDATE play_delegations SET active = 0
        WHERE campaign_id = #{Database.escape(campaign_id)} AND username = #{Database.escape(username)};
      SQL

      powers = JSON.parse(existing['powers'])
      record_delegation_audit(campaign_id, username, 'revoked', powers)

      [200, { username: username, powers: powers, active: false }]
    end

    # Immutable grant/revoke history for delegation, in the order entries
    # were recorded. Only the owning dm may read it.
    def delegation_audit(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign owner may read delegation audit')

      rows = Database.query(<<~SQL)
        SELECT username, action, powers FROM play_delegation_audit
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      entries = rows.map { |row| { username: row['username'], action: row['action'], powers: JSON.parse(row['powers']) } }

      [200, { entries: entries }]
    end

    def audit_event_view(row)
      {
        kind: row['kind'],
        actor: row['actor'],
        role: row['role'],
        timestamp: row['timestamp'].to_i,
        correlation_id: row['correlation_id']
      }
    end

    # Creates a campaign-scoped audit entry. Any authenticated campaign
    # member (owner included) may create one; timestamp is a per-campaign
    # sequence starting at 1, and correlation_id must be unique per campaign.
    def create_audit_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to create an audit event') unless is_owner || member?(campaign_id, actor[:username])

      kind = body['kind']
      correlation_id = body['correlation_id']
      raise HttpError.new(400, 'kind must be a nonempty string') unless kind.is_a?(String) && !kind.empty?
      raise HttpError.new(400, 'correlation_id must be a nonempty string') unless correlation_id.is_a?(String) && !correlation_id.empty?

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_audit_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND correlation_id = #{Database.escape(correlation_id)};
      SQL
      raise HttpError.new(409, 'correlation_id already used in this campaign') if existing

      role = is_owner ? 'DM' : 'player'
      timestamp = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(timestamp), 0) AS n FROM play_audit_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(kind)},
          #{Database.escape(actor[:username])},
          #{Database.escape(role)},
          #{Database.int(timestamp)},
          #{Database.escape(correlation_id)}
        );
      SQL

      [201, { kind: kind, actor: actor[:username], role: role, timestamp: timestamp, correlation_id: correlation_id }]
    end

    # Immutable audit trail, timestamp order. Only the owning dm may read it.
    def list_audit_events(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign owner may read the audit trail')

      rows = Database.query(<<~SQL)
        SELECT kind, actor, role, timestamp, correlation_id FROM play_audit_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY timestamp ASC;
      SQL

      [200, { entries: rows.map { |row| audit_event_view(row) } }]
    end

    # Player members may append projection events; the owning dm may not.
    # Storage is immutable and ordered by an auto-incrementing sequence
    # scoped to the campaign.
    def append_projection_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'the campaign dm may not append projection events') if is_owner
      raise HttpError.new(403, 'must be a party member to append projection events') unless member?(campaign_id, actor[:username])

      event_id = body['event_id']
      kind = body['kind']
      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'kind must be set-story or increment-danger') unless %w[set-story increment-danger].include?(kind)

      if kind == 'set-story'
        value = body['value']
        raise HttpError.new(400, 'value must be a nonempty string for set-story') unless value.is_a?(String) && !value.empty?
      else
        raise HttpError.new(400, 'value must be omitted for increment-danger') unless body['value'].nil?
        value = nil
      end

      existing = Database.query(<<~SQL).first
        SELECT id FROM play_projection_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
      raise HttpError.new(409, 'event_id already used in this campaign') if existing

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_projection_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_projection_events (campaign_id, sequence, event_id, kind, value)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(event_id)},
          #{Database.escape(kind)},
          #{value.nil? ? 'NULL' : Database.escape(value)}
        );
      SQL

      response = { sequence: sequence, event_id: event_id, kind: kind }
      response[:value] = value if kind == 'set-story'

      [201, response]
    end

    # Rebuilds the deterministic projection solely from the ordered
    # projection event log for the campaign.
    def build_projection(campaign_id)
      rows = Database.query(<<~SQL)
        SELECT event_id, kind, value FROM play_projection_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      story = ''
      danger = 0
      applied_event_ids = []

      rows.each do |row|
        applied_event_ids << row['event_id']
        if row['kind'] == 'set-story'
          story = row['value']
        else
          danger += 1
        end
      end

      { story: story, danger: danger, applied_event_ids: applied_event_ids }
    end

    def require_projection_reader!(actor, campaign_id)
      campaign = find_play_campaign(campaign_id)
      is_owner = owner?(campaign, actor)
      raise HttpError.new(403, 'must be the owning dm or a party member to read the projection') unless is_owner || member?(campaign_id, actor[:username])
    end

    def get_projection(actor, campaign_id, _body)
      require_projection_reader!(actor, campaign_id)
      [200, build_projection(campaign_id)]
    end

    def rebuild_projection(actor, campaign_id, _body)
      require_projection_reader!(actor, campaign_id)
      [200, build_projection(campaign_id)]
    end

    def idempotent_event_view(row)
      { event_id: row['event_id'], value: row['value'], sequence: row['sequence'], idempotency_key: row['idempotency_key'] }
    end

    # Idempotent, campaign-scoped event creation keyed by the mandatory
    # Idempotency-Key header. The first successful request for a key
    # appends an immutable row; repeats with matching event_id/value
    # replay the stored result instead of appending again.
    def create_idempotent_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be a campaign member to create idempotent events')

      idempotency_key = body['idempotency_key_header']
      raise HttpError.new(400, 'Idempotency-Key header is required') unless idempotency_key.is_a?(String) && !idempotency_key.strip.empty?

      idempotency_key = idempotency_key.strip

      event_id = body['event_id']
      value = body['value']
      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'value must be a nonempty string') unless value.is_a?(String) && !value.empty?

      existing_by_key = Database.query(<<~SQL).first
        SELECT event_id, value, sequence, idempotency_key FROM play_idempotent_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND idempotency_key = #{Database.escape(idempotency_key)};
      SQL

      if existing_by_key
        if existing_by_key['event_id'] == event_id && existing_by_key['value'] == value
          return [200, idempotent_event_view(existing_by_key)]
        end

        raise HttpError.new(409, 'idempotency key already used with a different event_id or value')
      end

      existing_by_event = Database.query(<<~SQL).first
        SELECT id FROM play_idempotent_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
      raise HttpError.new(409, 'event_id already used in this campaign') if existing_by_event

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_idempotent_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(event_id)},
          #{Database.escape(value)},
          #{Database.escape(idempotency_key)}
        );
      SQL

      [201, { event_id: event_id, value: value, sequence: sequence, idempotency_key: idempotency_key }]
    end

    def list_idempotent_events(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read idempotent events')

      rows = Database.query(<<~SQL)
        SELECT event_id, value, sequence, idempotency_key FROM play_idempotent_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      [200, { events: rows.map { |row| idempotent_event_view(row) } }]
    end

    # Fetches (creating with current_turn = 1 if absent) the campaign's
    # safe-turn counter row.
    def safe_turn_state(campaign_id)
      row = Database.query(<<~SQL).first
        SELECT current_turn FROM play_safe_turn_state
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      return row if row

      Database.exec(<<~SQL)
        INSERT INTO play_safe_turn_state (campaign_id, current_turn)
        VALUES (#{Database.escape(campaign_id)}, 1)
        ON CONFLICT(campaign_id) DO NOTHING;
      SQL

      Database.query(<<~SQL).first
        SELECT current_turn FROM play_safe_turn_state
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def safe_turn_view(row)
      {
        submission_id: row['submission_id'],
        action: row['action'],
        accepted_turn: row['accepted_turn'].to_i,
        next_turn: row['next_turn'].to_i
      }
    end

    # Campaign-scoped safe turn submission: accepts a submission only if
    # expected_turn matches the current safe-turn counter, rejecting stale
    # or duplicate submissions without mutating state.
    def submit_safe_turn(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be a campaign member to submit a safe turn')

      submission_id = body['submission_id']
      expected_turn = body['expected_turn']
      action = body['action']
      raise HttpError.new(400, 'submission_id must be a nonempty string') unless submission_id.is_a?(String) && !submission_id.empty?
      raise HttpError.new(400, 'action must be a nonempty string') unless action.is_a?(String) && !action.empty?
      raise HttpError.new(400, 'expected_turn must be a positive integer') unless expected_turn.is_a?(Integer) && expected_turn.positive?

      existing = Database.query(<<~SQL).first
        SELECT submission_id FROM play_safe_turns
        WHERE campaign_id = #{Database.escape(campaign_id)} AND submission_id = #{Database.escape(submission_id)};
      SQL
      raise HttpError.new(409, 'submission_id already used in this campaign') if existing

      state = safe_turn_state(campaign_id)
      current_turn = state['current_turn'].to_i

      return [409, { current_turn: current_turn }] if expected_turn != current_turn

      next_turn = current_turn + 1

      Database.exec(<<~SQL)
        INSERT INTO play_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(submission_id)},
          #{Database.escape(action)},
          #{Database.int(current_turn)},
          #{Database.int(next_turn)}
        );
      SQL

      Database.exec(<<~SQL)
        UPDATE play_safe_turn_state SET current_turn = #{Database.int(next_turn)}
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      [201, { submission_id: submission_id, action: action, accepted_turn: current_turn, next_turn: next_turn }]
    end

    def list_safe_turns(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read safe turns')

      state = safe_turn_state(campaign_id)

      rows = Database.query(<<~SQL)
        SELECT submission_id, action, accepted_turn, next_turn FROM play_safe_turns
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY accepted_turn ASC, id ASC;
      SQL

      [200, { current_turn: state['current_turn'].to_i, accepted: rows.map { |row| safe_turn_view(row) } }]
    end

    # Campaign-scoped transactional currency transfer: the debit, credit,
    # and success record are only written once every validation has passed.
    # When simulate_failure is set, validation and lookups still run but no
    # write happens at all, so a 500 leaves both balances and the transfer
    # log untouched.
    def create_transactional_transfer(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'must be a campaign member to create a transfer') unless owner?(campaign, actor) || member?(campaign_id, actor[:username])

      from_character_id = body['from_character_id']
      to_character_id = body['to_character_id']
      amount = body['amount']

      raise HttpError.new(400, 'from_character_id must be a nonempty string') unless from_character_id.is_a?(String) && !from_character_id.empty?
      raise HttpError.new(400, 'to_character_id must be a nonempty string') unless to_character_id.is_a?(String) && !to_character_id.empty?
      raise HttpError.new(400, 'to_character_id must be a different character') if to_character_id == from_character_id
      raise HttpError.new(400, 'amount must be a positive integer') unless amount.is_a?(Integer) && amount.positive?

      source = Database.query(<<~SQL).first
        SELECT owner, gold FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(from_character_id)};
      SQL
      raise HttpError.new(400, 'from_character_id must be a known campaign character') unless source

      destination = Database.query(<<~SQL).first
        SELECT gold FROM play_members
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
      SQL
      raise HttpError.new(400, 'to_character_id must be a known campaign character') unless destination

      raise HttpError.new(403, "only the character's owner may transfer gold") unless source['owner'] == actor[:username]

      from_gold_before = source['gold'].to_i
      raise HttpError.new(409, 'insufficient gold for this transfer') if amount > from_gold_before

      raise HttpError.new(500, 'simulated failure') if body['simulate_failure'] == true

      from_gold = from_gold_before - amount
      to_gold = destination['gold'].to_i + amount

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COUNT(*) AS n FROM play_transactional_transfers
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        UPDATE play_members SET gold = #{Database.int(from_gold)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(from_character_id)};
        UPDATE play_members SET gold = #{Database.int(to_gold)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND character_id = #{Database.escape(to_character_id)};
        INSERT INTO play_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(from_character_id)},
          #{Database.escape(to_character_id)},
          #{Database.int(amount)},
          #{Database.int(from_gold)},
          #{Database.int(to_gold)}
        );
      SQL

      [201, {
        from_character_id: from_character_id,
        to_character_id: to_character_id,
        amount: amount,
        from_gold: from_gold,
        to_gold: to_gold,
        sequence: sequence
      }]
    end

    def list_transactional_transfers(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      raise HttpError.new(403, 'must be the campaign dm or a member to read transactional transfers') unless owner?(campaign, actor) || member?(campaign_id, actor[:username])

      rows = Database.query(<<~SQL)
        SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_transactional_transfers
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      [200, {
        transfers: rows.map do |row|
          {
            from_character_id: row['from_character_id'],
            to_character_id: row['to_character_id'],
            amount: row['amount'].to_i,
            from_gold: row['from_gold'].to_i,
            to_gold: row['to_gold'].to_i,
            sequence: row['sequence'].to_i
          }
        end
      }]
    end

    def export_view(row)
      { version: row['version'].to_i, story: row['story'], status: row['status'] }
    end

    # Snapshots the campaign's current public story and status into a new
    # immutable, sequential export version. Only the owning dm may create
    # exports; the version is one greater than the campaign's previous
    # export count.
    def create_export(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create an export')

      document = Database.query(<<~SQL).first
        SELECT story FROM play_documents
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      story = document ? document['story'] : ''

      version = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(version), 0) AS n FROM play_exports
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_exports (campaign_id, version, story, status)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(version)},
          #{Database.escape(story)},
          #{Database.escape(campaign['status'])}
        );
      SQL

      [201, { version: version, story: story, status: campaign['status'] }]
    end

    # Only the owning dm may list exports, ordered by ascending version.
    def list_exports(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may list exports')

      rows = Database.query(<<~SQL)
        SELECT version, story, status FROM play_exports
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY version ASC;
      SQL

      [200, { exports: rows.map { |row| export_view(row) } }]
    end

    # Only the owning dm may read a specific export snapshot by version.
    def get_export(actor, campaign_id, version, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may read an export')

      raise HttpError.new(404, 'unknown export version') unless version =~ /\A\d+\z/

      row = Database.query(<<~SQL).first
        SELECT version, story, status FROM play_exports
        WHERE campaign_id = #{Database.escape(campaign_id)} AND version = #{Database.int(version)};
      SQL
      raise HttpError.new(404, 'unknown export version') unless row

      [200, export_view(row)]
    end

    IMPORT_VALID_STATUSES = %w[lobby started].freeze

    def import_view(row)
      { version: row['version'].to_i, story: row['story'], status: row['status'] }
    end

    # Accepts a compatible version-1 snapshot and applies its story and
    # status atomically to the campaign. Only the owning dm may import;
    # invalid bodies leave campaign and imported state untouched.
    def create_import(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create an import')

      version = body['version']
      story = body['story']
      status = body['status']

      raise HttpError.new(400, 'version must be 1') unless version == 1
      raise HttpError.new(400, 'story must be a nonempty string') unless story.is_a?(String) && !story.empty?
      raise HttpError.new(400, 'status must be lobby or started') unless IMPORT_VALID_STATUSES.include?(status)

      Database.exec(<<~SQL)
        BEGIN TRANSACTION;
        INSERT INTO play_documents (campaign_id, story, dm_notes)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(story)}, '')
        ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story;
        UPDATE play_campaigns SET status = #{Database.escape(status)}
        WHERE id = #{Database.escape(campaign_id)};
        INSERT INTO play_imports (campaign_id, version, story, status)
        VALUES (#{Database.escape(campaign_id)}, #{Database.int(version)}, #{Database.escape(story)}, #{Database.escape(status)})
        ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status;
        COMMIT;
      SQL

      [200, { version: version, story: story, status: status }]
    end

    # Only the owning dm may read the current imported state; 404 until a
    # successful import has occurred.
    def get_import_state(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may read imported state')

      row = Database.query(<<~SQL).first
        SELECT version, story, status FROM play_imports
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      raise HttpError.new(404, 'no import has been applied to this campaign') unless row

      [200, import_view(row)]
    end

    MIGRATION_SOURCE_SCHEMA_VERSION = 1
    MIGRATION_TARGET_SCHEMA_VERSION = 2

    def migration_view(row)
      { schema_version: row['schema_version'].to_i, story: row['story'], campaign_name: row['campaign_name'] }
    end

    # Accepts a legacy schema version 1 snapshot and deterministically
    # migrates it to schema version 2. Only the owning dm may migrate;
    # invalid bodies leave migrated state untouched. Repeating the same
    # source snapshot is idempotent and returns 200 without writing again.
    def create_migration(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create a migration')

      schema_version = body['schema_version']
      story = body['story']

      raise HttpError.new(400, 'schema_version must be 1') unless schema_version == MIGRATION_SOURCE_SCHEMA_VERSION
      raise HttpError.new(400, 'story must be a nonempty string') unless story.is_a?(String) && !story.empty?

      existing = Database.query(<<~SQL).first
        SELECT source_schema_version, source_story, schema_version, story, campaign_name
        FROM play_migrations WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      if existing && existing['source_schema_version'].to_i == schema_version && existing['source_story'] == story
        return [200, migration_view(existing)]
      end

      Database.exec(<<~SQL)
        INSERT INTO play_migrations (campaign_id, source_schema_version, source_story, schema_version, story, campaign_name)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(schema_version)},
          #{Database.escape(story)},
          #{Database.int(MIGRATION_TARGET_SCHEMA_VERSION)},
          #{Database.escape(story)},
          #{Database.escape(campaign['name'])}
        )
        ON CONFLICT(campaign_id) DO UPDATE SET
          source_schema_version = excluded.source_schema_version,
          source_story = excluded.source_story,
          schema_version = excluded.schema_version,
          story = excluded.story,
          campaign_name = excluded.campaign_name;
      SQL

      [201, { schema_version: MIGRATION_TARGET_SCHEMA_VERSION, story: story, campaign_name: campaign['name'] }]
    end

    # Only the owning dm may read the current migrated state; 404 until a
    # successful migration has occurred.
    def get_migration_state(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may read migrated state')

      row = Database.query(<<~SQL).first
        SELECT schema_version, story, campaign_name FROM play_migrations
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      raise HttpError.new(404, 'no migration has been applied to this campaign') unless row

      [200, migration_view(row)]
    end

    SEARCH_RECORD_MIN_LIMIT = 1
    SEARCH_RECORD_MAX_LIMIT = 3
    SEARCH_RECORD_DEFAULT_LIMIT = 2

    def search_record_view(row)
      { record_id: row['record_id'], text: row['text'] }
    end

    def find_search_record(campaign_id, record_id)
      Database.query(<<~SQL).first
        SELECT record_id, text FROM play_search_records
        WHERE campaign_id = #{Database.escape(campaign_id)} AND record_id = #{Database.escape(record_id)};
      SQL
    end

    def find_search_record_by_text(campaign_id, text)
      Database.query(<<~SQL).first
        SELECT record_id, text FROM play_search_records
        WHERE campaign_id = #{Database.escape(campaign_id)} AND text = #{Database.escape(text)};
      SQL
    end

    # Creates a campaign-scoped search record. Only the owning dm may
    # create records; record_id must be unique within the campaign.
    def create_search_record(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create search records')

      record_id = body['record_id']
      text = body['text']

      raise HttpError.new(400, 'record_id must be a nonempty string') unless record_id.is_a?(String) && !record_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'record_id already exists') if find_search_record(campaign_id, record_id)
      raise HttpError.new(400, 'text already exists') if find_search_record_by_text(campaign_id, text)

      Database.exec(<<~SQL)
        INSERT INTO play_search_records (campaign_id, record_id, text)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(record_id)}, #{Database.escape(text)});
      SQL

      [201, { record_id: record_id, text: text }]
    end

    # Parses a nonnegative integer query parameter, raising 400 on anything
    # that isn't a plain base-10 integer string within [min, max].
    def parse_search_query_int(raw, min, max, field)
      raise HttpError.new(400, "#{field} must be an integer") unless raw.is_a?(String) && raw.match?(/\A\d+\z/)

      value = raw.to_i
      raise HttpError.new(400, "#{field} out of range") if value < min || (max && value > max)

      value
    end

    # Lists campaign search records: the dm and campaign members may list;
    # other authenticated users receive 403. Supports substring filtering
    # over text, then stable cursor/limit pagination over creation order.
    def list_search_records(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to list search records')

      limit = body.key?('limit') ? parse_search_query_int(body['limit'], SEARCH_RECORD_MIN_LIMIT, SEARCH_RECORD_MAX_LIMIT, 'limit') : SEARCH_RECORD_DEFAULT_LIMIT
      cursor = body.key?('cursor') ? parse_search_query_int(body['cursor'], 0, nil, 'cursor') : 0

      rows = Database.query(<<~SQL)
        SELECT record_id, text FROM play_search_records
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      records = rows.map { |row| search_record_view(row) }

      q = body['q']
      raise HttpError.new(400, 'q must be a string') if q && !q.is_a?(String)

      records = records.select { |record| record[:text].downcase.include?(q.downcase) } if q && !q.empty?

      page = records[cursor, limit] || []
      next_cursor = cursor + page.length < records.length ? cursor + page.length : nil

      [200, { records: page, next_cursor: next_cursor }]
    end

    RATE_EVENT_LIMIT = 2

    def rate_event_view(row)
      { event_id: row['event_id'], actor: row['actor'] }
    end

    def find_rate_event(campaign_id, event_id)
      Database.query(<<~SQL).first
        SELECT event_id, actor FROM play_rate_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
    end

    def rate_events_used(campaign_id, username)
      Database.query(<<~SQL).first['count']
        SELECT COUNT(*) AS count FROM play_rate_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND actor = #{Database.escape(username)};
      SQL
    end

    # Creates a per-actor-limited rate event. The dm and campaign members
    # may create events; other authenticated users receive 403. Each
    # username has a fixed limit of RATE_EVENT_LIMIT accepted events per
    # campaign; rejected requests do not record an event.
    def create_rate_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to create rate events')

      event_id = body['event_id']
      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'event_id already exists') if find_rate_event(campaign_id, event_id)

      username = actor[:username]
      used = rate_events_used(campaign_id, username)
      if used >= RATE_EVENT_LIMIT
        Database.exec(<<~SQL)
          INSERT INTO play_rate_event_rejections (campaign_id)
          VALUES (#{Database.escape(campaign_id)});
        SQL
        return [429, { limit: RATE_EVENT_LIMIT, remaining: 0 }]
      end

      Database.exec(<<~SQL)
        INSERT INTO play_rate_events (campaign_id, event_id, actor)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(event_id)}, #{Database.escape(username)});
      SQL

      [201, { event_id: event_id, actor: username, remaining: RATE_EVENT_LIMIT - used - 1 }]
    end

    # Lists campaign rate events in creation order plus the caller's
    # remaining allowance. The dm and campaign members may list; other
    # authenticated users receive 403.
    def list_rate_events(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to list rate events')

      rows = Database.query(<<~SQL)
        SELECT event_id, actor FROM play_rate_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY id ASC;
      SQL

      events = rows.map { |row| rate_event_view(row) }
      used = rate_events_used(campaign_id, actor[:username])

      [200, { events: events, remaining: RATE_EVENT_LIMIT - used }]
    end

    # Returns campaign-scoped safe aggregate counters. Only the owning dm
    # may read metrics; campaign players and other authenticated users
    # receive 403. Exposes no story, character, event, or actor content.
    def get_metrics(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may read campaign metrics')

      accepted = Database.query(<<~SQL).first['count']
        SELECT COUNT(*) AS count FROM play_rate_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      rejected = Database.query(<<~SQL).first['count']
        SELECT COUNT(*) AS count FROM play_rate_event_rejections
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      projections = Database.query(<<~SQL).first['count']
        SELECT COUNT(*) AS count FROM play_projection_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      [200, {
        accepted_rate_events: accepted,
        rejected_rate_events: rejected,
        projection_events: projections,
        uptime_ticks: 1
      }]
    end

    # Flips the process-global maintenance switch (see ServiceState), which
    # every campaign's public GET /readyz reflects. Only the owning dm of
    # `campaign_id` may change it; the campaign itself is otherwise
    # unaffected — this is reference service state, not campaign data.
    def service_mode(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the owning dm may change service mode')

      maintenance = body['maintenance']
      raise HttpError.new(400, 'maintenance must be a boolean') unless [true, false].include?(maintenance)

      ServiceState.maintenance = maintenance

      [200, { maintenance: ServiceState.maintenance? }]
    end

    def backup_view(row)
      { backup_id: "backup-#{row['sequence']}", story: row['story'], status: row['status'] }
    end

    # Snapshots the campaign's current public story and status into a new
    # immutable, sequential backup. Only the owning dm may create backups;
    # the sequence is one greater than the campaign's previous backup count.
    def create_backup(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may create a backup')

      document = Database.query(<<~SQL).first
        SELECT story FROM play_documents
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      story = document ? document['story'] : ''

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_backups
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_backups (campaign_id, sequence, story, status)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(story)},
          #{Database.escape(campaign['status'])}
        );
      SQL

      [201, backup_view({ 'sequence' => sequence, 'story' => story, 'status' => campaign['status'] })]
    end

    # Only the owning dm may list backups, ordered by creation sequence.
    def list_backups(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may list backups')

      rows = Database.query(<<~SQL)
        SELECT sequence, story, status FROM play_backups
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      [200, { backups: rows.map { |row| backup_view(row) } }]
    end

    # Applies an existing backup's story and status to the campaign without
    # mutating the snapshot itself or creating a new backup. Only the owning
    # dm may restore.
    def restore_backup(actor, campaign_id, backup_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may restore a backup')

      raise HttpError.new(404, 'unknown backup id') unless backup_id =~ /\Abackup-(\d+)\z/

      sequence = backup_id.split('-').last

      row = Database.query(<<~SQL).first
        SELECT sequence, story, status FROM play_backups
        WHERE campaign_id = #{Database.escape(campaign_id)} AND sequence = #{Database.int(sequence)};
      SQL
      raise HttpError.new(404, 'unknown backup id') unless row

      Database.exec(<<~SQL)
        BEGIN TRANSACTION;
        INSERT INTO play_documents (campaign_id, story, dm_notes)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(row['story'])}, '')
        ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story;
        UPDATE play_campaigns SET status = #{Database.escape(row['status'])}
        WHERE id = #{Database.escape(campaign_id)};
        COMMIT;
      SQL

      [200, backup_view(row)]
    end

    # Appends a deterministic replay event to the campaign's replay stream.
    # Only `kind: "append"` is supported; event_id must be unique within the
    # campaign. The sequence is one greater than the campaign's previous
    # replay event count, and reflects successful append order only.
    def create_replay_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to append replay events')

      event_id = body['event_id']
      kind = body['kind']
      text = body['text']

      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, 'kind must be append') unless kind == 'append'

      existing = Database.query(<<~SQL).first
        SELECT event_id FROM play_replay_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
      raise HttpError.new(409, 'event_id already exists') if existing

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_replay_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_replay_events (campaign_id, sequence, event_id, kind, text)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(event_id)},
          #{Database.escape(kind)},
          #{Database.escape(text)}
        );
      SQL

      [201, { event_id: event_id, kind: kind, text: text, sequence: sequence }]
    end

    # Rebuilds the public replay state deterministically from successful
    # append order: `story` is the concatenation of event texts, `event_ids`
    # is the ordered list of event IDs, and `digest` is a simple
    # deterministic hash substitute derived from both.
    def replay_state(campaign_id)
      rows = Database.query(<<~SQL)
        SELECT event_id, text FROM play_replay_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      story = rows.map { |row| row['text'] }.join
      event_ids = rows.map { |row| row['event_id'] }
      digest = "#{event_ids.join(',')}|#{story}"

      { story: story, event_ids: event_ids, digest: digest }
    end

    def get_replay(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to read replay state')

      [200, replay_state(campaign_id)]
    end

    # Explicit replay verification path; identical to GET /replay and does
    # not mutate state.
    def check_replay(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to read replay state')

      [200, replay_state(campaign_id)]
    end

    # Computes the stable RNG roll result deterministically from the
    # campaign seed, append-order sequence, roll_id, and sides, per the
    # 32-bit accumulator algorithm in the stage spec. No math/rand, wall
    # clock, or other nondeterministic input is used.
    def rng_roll_result(seed, sequence, roll_id, sides)
      bytes = "#{seed}|#{sequence}|#{roll_id}|#{sides}".bytes
      acc = 0
      bytes.each { |b| acc = (acc * 31 + b) % 4_294_967_296 }
      (acc % sides) + 1
    end

    def find_rng_seed(campaign_id)
      Database.query(<<~SQL).first
        SELECT seed FROM play_rng_seeds WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def rng_roll_view(row)
      { roll_id: row['roll_id'], sides: row['sides'].to_i, result: row['result'].to_i, sequence: row['sequence'].to_i }
    end

    def rng_ledger_state(campaign_id)
      seed_row = find_rng_seed(campaign_id)
      rolls = Database.query(<<~SQL)
        SELECT roll_id, sides, result, sequence FROM play_rng_rolls
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      { seed: seed_row ? seed_row['seed'] : nil, rolls: rolls.map { |row| rng_roll_view(row) } }
    end

    # Configures the campaign's deterministic RNG seed. Only the owning dm
    # may set it, and only once; replacing an existing seed is rejected
    # without mutating the ledger.
    def set_rng_seed(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may configure the rng seed')

      seed = body['seed']
      raise HttpError.new(400, 'seed must be a nonempty string') unless seed.is_a?(String) && !seed.empty?
      raise HttpError.new(409, 'rng seed already configured') if find_rng_seed(campaign_id)

      Database.exec(<<~SQL)
        INSERT INTO play_rng_seeds (campaign_id, seed)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(seed)});
      SQL

      [200, { seed: seed, rolls: [] }]
    end

    # Appends a deterministic roll to the campaign's immutable RNG ledger.
    # Any authenticated campaign member, including the dm, may append.
    def create_rng_roll(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to append rng rolls')

      seed_row = find_rng_seed(campaign_id)
      raise HttpError.new(409, 'rng seed not configured') unless seed_row

      roll_id = body['roll_id']
      sides = body['sides']

      raise HttpError.new(400, 'roll_id must be a nonempty string') unless roll_id.is_a?(String) && !roll_id.empty?
      raise HttpError.new(400, 'sides must be an integer from 2 through 100') unless sides.is_a?(Integer) && sides >= 2 && sides <= 100

      existing = Database.query(<<~SQL).first
        SELECT roll_id FROM play_rng_rolls
        WHERE campaign_id = #{Database.escape(campaign_id)} AND roll_id = #{Database.escape(roll_id)};
      SQL
      raise HttpError.new(409, 'roll_id already exists') if existing

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_rng_rolls
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      result = rng_roll_result(seed_row['seed'], sequence, roll_id, sides)

      Database.exec(<<~SQL)
        INSERT INTO play_rng_rolls (campaign_id, sequence, roll_id, sides, result)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(roll_id)},
          #{Database.int(sides)},
          #{Database.int(result)}
        );
      SQL

      [201, { roll_id: roll_id, sides: sides, result: result, sequence: sequence }]
    end

    def get_rng_ledger(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to read the rng ledger')

      [200, rng_ledger_state(campaign_id)]
    end

    def find_moderation_report(campaign_id, report_id)
      Database.query(<<~SQL).first
        SELECT sequence, report_id, target_id, reason, status, reporter, action, note, resolver
        FROM play_moderation_reports
        WHERE campaign_id = #{Database.escape(campaign_id)} AND report_id = #{Database.escape(report_id)};
      SQL
    end

    def moderation_report_view(row)
      view = {
        report_id: row['report_id'],
        target_id: row['target_id'],
        reason: row['reason'],
        status: row['status'],
        reporter: row['reporter'],
        sequence: row['sequence'].to_i
      }

      if row['status'] == 'resolved'
        view[:action] = row['action']
        view[:note] = row['note']
        view[:resolver] = row['resolver']
      end

      view
    end

    # Any authenticated campaign member, including the dm, may submit a
    # moderation report. report_id is unique per campaign; append order is
    # tracked via sequence, mirroring the rng ledger's append semantics.
    def create_moderation_report(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to submit a moderation report')

      report_id = body['report_id']
      target_id = body['target_id']
      reason = body['reason']

      raise HttpError.new(400, 'report_id must be a nonempty string') unless report_id.is_a?(String) && !report_id.empty?
      raise HttpError.new(400, 'target_id must be a nonempty string') unless target_id.is_a?(String) && !target_id.empty?
      raise HttpError.new(400, 'reason must be a nonempty string') unless reason.is_a?(String) && !reason.empty?

      raise HttpError.new(409, 'report_id already exists') if find_moderation_report(campaign_id, report_id)

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_moderation_reports
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_moderation_reports (campaign_id, sequence, report_id, target_id, reason, status, reporter)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(report_id)},
          #{Database.escape(target_id)},
          #{Database.escape(reason)},
          'open',
          #{Database.escape(actor[:username])}
        );
      SQL

      [201, { report_id: report_id, target_id: target_id, reason: reason, status: 'open', reporter: actor[:username], sequence: sequence }]
    end

    def list_moderation_reports(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the owning dm or a campaign member to read moderation reports')

      rows = Database.query(<<~SQL)
        SELECT sequence, report_id, target_id, reason, status, reporter, action, note, resolver
        FROM play_moderation_reports
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      [200, { reports: rows.map { |row| moderation_report_view(row) } }]
    end

    VALID_MODERATION_ACTIONS = %w[allow remove].freeze

    # Only the owning dm may resolve a report, and only once: the open ->
    # resolved transition is a one-way door that leaves sequence and the
    # original fields untouched.
    def resolve_moderation_report(actor, campaign_id, report_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may resolve moderation reports')

      report = find_moderation_report(campaign_id, report_id)
      raise HttpError.new(404, 'unknown report id') unless report

      action = body['action']
      note = body['note']

      raise HttpError.new(400, "action must be 'allow' or 'remove'") unless VALID_MODERATION_ACTIONS.include?(action)
      raise HttpError.new(400, 'note must be a nonempty string') unless note.is_a?(String) && !note.empty?

      raise HttpError.new(409, 'report already resolved') if report['status'] == 'resolved'

      Database.exec(<<~SQL)
        UPDATE play_moderation_reports
        SET status = 'resolved', action = #{Database.escape(action)}, note = #{Database.escape(note)}, resolver = 'dm'
        WHERE campaign_id = #{Database.escape(campaign_id)} AND report_id = #{Database.escape(report_id)};
      SQL

      resolved = find_moderation_report(campaign_id, report_id)
      [200, moderation_report_view(resolved)]
    end

    def find_safety_boundaries(campaign_id)
      Database.query(<<~SQL).first
        SELECT blocked_tags_json FROM play_safety_boundaries
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def blocked_tags_for(campaign_id)
      row = find_safety_boundaries(campaign_id)
      row ? JSON.parse(row['blocked_tags_json']) : []
    end

    # Only the owning dm may replace boundaries. Validation happens before
    # any write so an invalid request never mutates the previous state.
    def replace_safety_boundaries(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may replace safety boundaries')

      tags = body['blocked_tags']
      raise HttpError.new(400, 'blocked_tags must be a nonempty array of unique nonempty strings') unless valid_tags?(tags) && !tags.empty?

      sorted = tags.sort

      Database.exec(<<~SQL)
        INSERT INTO play_safety_boundaries (campaign_id, blocked_tags_json)
        VALUES (#{Database.escape(campaign_id)}, #{Database.escape(JSON.generate(sorted))})
        ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags_json = excluded.blocked_tags_json;
      SQL

      [200, { blocked_tags: sorted }]
    end

    def get_safety_boundaries(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read safety boundaries')

      [200, { blocked_tags: blocked_tags_for(campaign_id).sort }]
    end

    VALID_SAFETY_CHECK_KINDS = %w[narration chat].freeze

    def find_safety_event(campaign_id, event_id)
      Database.query(<<~SQL).first
        SELECT sequence, event_id, kind, text, tags_json FROM play_safety_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
    end

    def safety_event_view(row)
      {
        event_id: row['event_id'],
        kind: row['kind'],
        text: row['text'],
        tags: JSON.parse(row['tags_json']),
        sequence: row['sequence'].to_i
      }
    end

    # Any authenticated campaign member, including the dm, may submit a
    # safety check. Duplicate event_id or any submitted tag intersecting the
    # current blocked_tags is rejected without appending or mutating events.
    def submit_safety_check(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to submit a safety check')

      event_id = body['event_id']
      kind = body['kind']
      text = body['text']
      tags = body['tags']

      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(400, "kind must be 'narration' or 'chat'") unless VALID_SAFETY_CHECK_KINDS.include?(kind)
      raise HttpError.new(400, 'tags must be a nonempty array of unique nonempty strings') unless valid_tags?(tags) && !tags.empty?

      raise HttpError.new(409, 'event_id already accepted') if find_safety_event(campaign_id, event_id)

      blocked = blocked_tags_for(campaign_id)
      raise HttpError.new(409, 'submitted tags intersect blocked_tags') if tags.any? { |tag| blocked.include?(tag) }

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_safety_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_safety_events (campaign_id, sequence, event_id, kind, text, tags_json)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(event_id)},
          #{Database.escape(kind)},
          #{Database.escape(text)},
          #{Database.escape(JSON.generate(tags))}
        );
      SQL

      [201, { event_id: event_id, kind: kind, text: text, tags: tags, sequence: sequence }]
    end

    def list_safety_events(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read safety events')

      rows = Database.query(<<~SQL)
        SELECT sequence, event_id, kind, text, tags_json FROM play_safety_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      [200, { events: rows.map { |row| safety_event_view(row) } }]
    end

    VALID_FIXTURE_IDS = %w[canonical-v1].freeze

    def canonical_fixture_state
      {
        fixture_id: 'canonical-v1',
        status: 'seeded',
        characters: [
          { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
          { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' }
        ],
        story: 'The lantern is lit.',
        event_ids: %w[fixture-event-1 fixture-event-2]
      }
    end

    def find_fixture_seed(campaign_id)
      Database.query(<<~SQL).first
        SELECT fixture_id, state_json FROM play_fixture_seeds
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    # Only the owning dm may seed fixture state. Validation happens before
    # any write, and idempotent replays of an already-seeded campaign return
    # the stored state rather than re-deriving it, so state can never drift.
    def create_fixture_seed(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner!(campaign, actor, 'only the campaign dm may seed fixture state')

      fixture_id = body['fixture_id']
      raise HttpError.new(400, "fixture_id must be 'canonical-v1'") unless VALID_FIXTURE_IDS.include?(fixture_id)

      existing = find_fixture_seed(campaign_id)
      return [200, JSON.parse(existing['state_json'], symbolize_names: true)] if existing

      state = canonical_fixture_state

      Database.exec(<<~SQL)
        INSERT INTO play_fixture_seeds (campaign_id, fixture_id, state_json)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(fixture_id)},
          #{Database.escape(JSON.generate(state))}
        );
      SQL

      [201, state]
    end

    def get_fixture_state(actor, campaign_id, _body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read fixture state')

      row = find_fixture_seed(campaign_id)
      raise HttpError.new(404, 'no fixture seeded for this campaign') unless row

      [200, JSON.parse(row['state_json'], symbolize_names: true)]
    end

    def feed_event_view(row)
      { event_id: row['event_id'], text: row['text'], sequence: row['sequence'] }
    end

    def find_feed_event(campaign_id, event_id)
      Database.query(<<~SQL).first
        SELECT event_id, text, sequence FROM play_feed_events
        WHERE campaign_id = #{Database.escape(campaign_id)} AND event_id = #{Database.escape(event_id)};
      SQL
    end

    # Appends an event to the campaign's load-safe feed. Any authenticated
    # campaign member (dm owner or joined player) may append; event_id must
    # be unique within the campaign so retries/duplicates are rejected
    # rather than silently accepted twice.
    def append_feed_event(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to append feed events')

      event_id = body['event_id']
      text = body['text']

      raise HttpError.new(400, 'event_id must be a nonempty string') unless event_id.is_a?(String) && !event_id.empty?
      raise HttpError.new(400, 'text must be a nonempty string') unless text.is_a?(String) && !text.empty?
      raise HttpError.new(409, 'event_id already exists') if find_feed_event(campaign_id, event_id)

      sequence = Database.query(<<~SQL).first['n'].to_i + 1
        SELECT COALESCE(MAX(sequence), 0) AS n FROM play_feed_events
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO play_feed_events (campaign_id, sequence, event_id, text)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.int(sequence)},
          #{Database.escape(event_id)},
          #{Database.escape(text)}
        );
      SQL

      [201, { event_id: event_id, text: text, sequence: sequence }]
    end

    FEED_MIN_LIMIT = 1
    FEED_MAX_LIMIT = 3
    FEED_DEFAULT_LIMIT = 2

    # Cursor/limit read over the append-only feed. `cursor` counts events
    # already consumed (not a sequence number), so a page is always the
    # next `limit` events after the first `cursor` accepted so far -
    # stable even when new events are appended between reads.
    def get_event_feed(actor, campaign_id, body)
      campaign = find_play_campaign(campaign_id)
      require_owner_or_member!(campaign, actor, campaign_id, 'must be the campaign dm or a member to read the event feed')

      cursor = body.key?('cursor') ? parse_search_query_int(body['cursor'], 0, nil, 'cursor') : 0
      limit = body.key?('limit') ? parse_search_query_int(body['limit'], FEED_MIN_LIMIT, FEED_MAX_LIMIT, 'limit') : FEED_DEFAULT_LIMIT

      rows = Database.query(<<~SQL)
        SELECT event_id, text, sequence FROM play_feed_events
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY sequence ASC;
      SQL

      page = rows[cursor, limit] || []
      events = page.map { |row| feed_event_view(row) }

      [200, { events: events, next_cursor: cursor + events.length }]
    end
  end
end
