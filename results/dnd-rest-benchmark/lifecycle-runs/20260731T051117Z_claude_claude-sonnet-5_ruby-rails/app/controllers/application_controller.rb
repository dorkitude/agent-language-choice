# Shared base for every domain controller. Holds only cross-cutting
# request-validation helpers and the D&D 5e math (ability modifier,
# proficiency bonus) used by more than one controller. No routes are
# mapped directly to this controller.
class ApplicationController < ActionController::Base
  private

  def valid_integer?(value)
    case value
    when Integer
      true
    when String
      value.match?(/\A-?\d+\z/)
    else
      false
    end
  end

  def ability_mod(score)
    (score - 10) / 2
  end

  def proficiency_bonus(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end

  # Shared by CoreController#adjusted_xp and DmController#dm_encounter_builder:
  # sums the per-member DMG XP thresholds for a party across the four
  # difficulty tiers.
  def encounter_thresholds(party)
    totals = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |p|
      level = p[:level].to_i
      thresholds = LEVEL_THRESHOLDS[level]
      next unless thresholds

      totals[:easy] += thresholds[:easy]
      totals[:medium] += thresholds[:medium]
      totals[:hard] += thresholds[:hard]
      totals[:deadly] += thresholds[:deadly]
    end
    totals
  end

  def difficulty_for(adjusted_xp, totals)
    difficulty = 'trivial'
    difficulty = 'easy' if adjusted_xp >= totals[:easy]
    difficulty = 'medium' if adjusted_xp >= totals[:medium]
    difficulty = 'hard' if adjusted_xp >= totals[:hard]
    difficulty = 'deadly' if adjusted_xp >= totals[:deadly]
    difficulty
  end

  # Shared sort used by initiative_order and combat session creation:
  # highest score first, ties broken by dex then name.
  def compare_by_score_dex_name(a, b)
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp == 0
    cmp = a[:name] <=> b[:name] if cmp == 0
    cmp
  end

  # Extracts the username from a `Authorization: Bearer session-<username>`
  # header, or nil if the header is missing/malformed. Shared by
  # authenticate_user! and authenticate_play_actor!, which differ only in
  # whether the username must also be a registered USERS entry.
  def bearer_session_username
    header = request.headers['Authorization']
    return nil unless header.is_a?(String) && header.start_with?('Bearer session-')

    username = header.sub('Bearer session-', '')
    username.length.positive? ? username : nil
  end

  # Authenticates a request bearing `Authorization: Bearer session-<username>`
  # against the USERS collection. Renders 401 and returns nil on missing/
  # invalid credentials; otherwise returns the authenticated username.
  # Callers that need a specific role should check the returned username's
  # role themselves and render 403 for a valid-but-unauthorized actor.
  def authenticate_user!
    username = bearer_session_username
    unless username && USERS.key?(username)
      render json: { error: 'unauthorized' }, status: :unauthorized
      return nil
    end

    username
  end

  # Authenticates a /v1/play actor bearing `Authorization: Bearer
  # session-<username>`. Unlike authenticate_user!, this does not consult the
  # USERS registry: play-surface actors (dm, player-a, player-b, ...) are
  # identified by the session token alone, independent of /v1/auth
  # registration. Renders 401 and returns nil on missing/malformed
  # credentials; otherwise returns the actor's username.
  def authenticate_play_actor!
    username = bearer_session_username
    unless username
      render json: { error: 'unauthorized' }, status: :unauthorized
      return nil
    end

    username
  end
end
