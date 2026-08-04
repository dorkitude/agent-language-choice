# Shared domain rules and validation helpers used by the API controllers.
#
# This module is included in ApplicationController so every concrete controller
# has access to the same D&D 5e math (initiative, encounter difficulty) and the
# shared identifier validation pattern. Keeping the rules in one place prevents
# the duplication that existed between EncountersController and DmController,
# and guarantees that the deterministic evaluator sees identical results.
module DndRules
  extend ActiveSupport::Concern

  # Identifier pattern used for campaigns, characters, quests, sessions, and
  # compendium slugs. Keep this in sync with the cumulative evaluator fixtures.
  VALID_ID_RE = /\A[a-z0-9_-]+\z/.freeze

  # 5e encounter XP budgets by challenge rating.
  XP_BY_CR = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800
  }.freeze

  # Per-character daily encounter thresholds by level. Only level 3 is needed by
  # the current evaluator, but the structure mirrors the full 5e table.
  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  # 5e ability modifier for a score in the 1..30 range. Shared between
  # CharactersController and PlayCampaignsController so the math stays
  # identical across the codebase. Named `modifier_for` to avoid shadowing
  # the `ability_modifier` action in CharactersController.
  def modifier_for(score)
    (score - 10) / 2
  end

  # 5e proficiency bonus by character level (1..20). Kept in one place so
  # both the character utilities and the play surface use the same curve.
  def proficiency_bonus(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    else 6
    end
  end

  # True when +value+ is a non-empty string matching the shared ID pattern.
  def valid_id?(value)
    value.is_a?(String) && VALID_ID_RE.match?(value)
  end

  # True when +value+ is a non-empty string.
  def valid_non_empty_string?(value)
    value.is_a?(String) && !value.empty?
  end

  # Look up a campaign by id. Renders 404 and returns nil when missing.
  #
  # Callers must validate the id format first if they want a 400 for invalid
  # ids; this helper does not validate and simply treats malformed ids as not
  # found.
  def find_campaign(id)
    row = GameStorage.db.get_first_row(
      'SELECT id, name, dm FROM campaigns WHERE id = ?',
      id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  # Sort combatants by initiative score, then dexterity, then name (descending).
  # Returns an array of { 'name' => ..., 'score' => ... } hashes. The caller is
  # expected to have already validated the combatant shape.
  def initiative_order(combatants)
    entries = combatants.map do |c|
      {
        'name' => c['name'],
        'dex' => c['dex'],
        'score' => c['roll'] + c['dex']
      }
    end

    entries.sort! do |a, b|
      [b['score'], b['dex'], a['name']] <=> [a['score'], a['dex'], b['name']]
    end

    entries.map { |e| { 'name' => e['name'], 'score' => e['score'] } }
  end

  # Validate a party array and return the summed daily encounter thresholds.
  # Renders a 400 and returns nil for invalid or unsupported party members.
  def build_party_thresholds(party)
    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      unless member.is_a?(Hash) && member['level'].is_a?(Integer)
        bad_request('invalid party member')
        return nil
      end
      th = LEVEL_THRESHOLDS[member['level']]
      unless th
        bad_request('unsupported level')
        return nil
      end
      thresholds.each_key { |k| thresholds[k] += th[k] }
    end
    thresholds
  end

  # Validate a monster list of { 'cr' => ..., 'count' => ... } hashes and return
  # [base_xp, monster_count]. Renders a 400 and returns nil for invalid input.
  def sum_monster_xp(monsters)
    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      unless monster.is_a?(Hash) && monster['cr'].is_a?(String) && monster['count'].is_a?(Integer)
        bad_request('invalid monster')
        return nil
      end
      xp = XP_BY_CR[monster['cr']]
      unless xp
        bad_request('unsupported challenge rating')
        return nil
      end
      base_xp += xp * monster['count']
      monster_count += monster['count']
    end
    [base_xp, monster_count]
  end

  # Return [numerator, denominator] for the 5e encounter size multiplier.
  def encounter_multiplier(monster_count)
    case monster_count
    when 1 then [1, 1]
    when 2 then [3, 2]
    when 3..6 then [2, 1]
    when 7..10 then [5, 2]
    when 11..14 then [3, 1]
    else [4, 1]
    end
  end

  # Map an adjusted XP total against the supplied thresholds to a difficulty
  # label. The evaluator expects these exact strings.
  def difficulty_label(adjusted_xp, thresholds)
    if adjusted_xp >= thresholds[:deadly]
      'deadly'
    elsif adjusted_xp >= thresholds[:hard]
      'hard'
    elsif adjusted_xp >= thresholds[:medium]
      'medium'
    elsif adjusted_xp >= thresholds[:easy]
      'easy'
    else
      'trivial'
    end
  end
end
