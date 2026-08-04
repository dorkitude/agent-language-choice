# frozen_string_literal: true

require 'json'
require_relative 'persistence'

# Protected campaign-play surface: ownership, membership, turn queue,
# narration, actions, resolutions, and campaign documents.
module PlayCampaigns
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
        'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, actor[:username], data[:character_id], data[:name], data[:class]]
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

  def self.narrate(campaign_id, actor, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    text = payload['text']
    return [:invalid] unless text.is_a?(String) && !text.empty?

    Persistence.db do |d|
      campaign = d.get_first_row('SELECT owner FROM play_campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign

      owner = campaign[0]
      next [:forbidden] unless owner == actor[:username]

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'narration', 'dm', text]
      )

      [:ok, {
        'sequence' => next_sequence,
        'kind' => 'narration',
        'actor' => 'dm',
        'text' => text
      }]
    end
  end

  def self.turn(campaign_id, actor)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign = d.get_first_row(
        'SELECT owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?',
        campaign_id
      )
      next [:not_found] unless campaign

      owner, status, current_actor, turn_number = campaign
      is_member = d.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, actor[:username]]
      )
      next [:forbidden] unless owner == actor[:username] || is_member

      phase = current_actor == owner ? 'dm' : 'player'

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

      recent_events = d.execute(
        'SELECT sequence, kind, actor, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence DESC',
        campaign_id
      ).map do |sequence, kind, event_actor, text|
        { 'sequence' => sequence, 'kind' => kind, 'actor' => event_actor, 'text' => text }
      end

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

      recent_events = d.execute(
        'SELECT sequence, kind, actor, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence DESC',
        campaign_id
      ).map do |sequence, kind, event_actor, text|
        { 'sequence' => sequence, 'kind' => kind, 'actor' => event_actor, 'text' => text }
      end

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

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'action', actor[:username], text]
      )

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

      # Advance to the player after whoever submitted the last action,
      # wrapping around at the end of the sorted party list.
      last_action_row = d.get_first_row(
        "SELECT actor FROM play_narrations WHERE campaign_id = ? AND kind = 'action' ORDER BY sequence DESC LIMIT 1",
        campaign_id
      )
      last_actor = last_action_row ? last_action_row[0] : nil

      next_actor = if last_actor && members.include?(last_actor)
                     members[(members.index(last_actor) + 1) % members.length]
                   else
                     members[0]
                   end

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'resolution', 'dm', text]
      )

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

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )
      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'nudge', owner, message]
      )

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

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )
      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'document', owner, story]
      )

      [:ok, { 'story' => story, 'dm_notes' => dm_notes }]
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

      next_sequence = d.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?',
        campaign_id
      )

      d.execute(
        'INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, 'travel', actor[:username], "traveled to #{destination_id}"]
      )

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

    return nil unless character_id.is_a?(String) && !character_id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      klass.is_a?(String) && !klass.empty?

    { character_id: character_id, name: name, class: klass }
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
end
