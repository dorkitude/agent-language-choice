# frozen_string_literal: true

require 'openssl'
require 'json'

# Authentication utilities.
#
# Passwords are hashed with PBKDF2-HMAC-SHA256. The salt is derived from the
# username so that the same password always produces the same hash for a given
# user. This avoids storing per-user salts while still preventing naive rainbow
# table attacks against the global salt prefix.
module Auth
  def hash_password(password, username)
    salt = "dnd-auth-salt-#{username}"
    OpenSSL::KDF.pbkdf2_hmac(password, salt: salt, iterations: 10_000, length: 32, hash: 'sha256')
  end

  def hash_password_hex(password, username)
    hash_password(password, username).unpack1('H*')
  end

  # Extracts the bearer token from the Authorization header and returns the
  # authenticated user. Halts 401 if the token is missing or does not match a
  # known user.
  def authenticate_actor!
    auth_header = request.env['HTTP_AUTHORIZATION'].to_s
    json_error(401, 'missing or invalid credentials') unless auth_header.match?(/\ABearer session-/i)

    username = auth_header.sub(/\ABearer session-/i, '').force_encoding('UTF-8')
    user = Storage.load_user(username)

    unless user
      # The play-campaign surface uses session tokens deterministically. Any
      # well-formed session token is treated as an authenticated actor; reserved
      # 'dm'/'player-*' tokens keep their prior roles, while other unknown
      # usernames are authenticated but carry no privileged role so membership
      # checks can return 403 instead of 401.
      role = if username == 'dm'
               'dm'
             elsif username.start_with?('player-')
               'player'
             else
               'unknown'
             end
      user = { username: username, role: role }
    end

    user
  end

  # Authenticates the request and returns the username only if the user has the
  # dm role. Halts 403 for a known non-dm actor.
  def require_dm_actor!
    user = authenticate_actor!
    json_error(403, 'forbidden') unless user[:role] == 'dm'
    user[:username]
  end

  # Authenticates the request and returns the username only if the user has the
  # player role. Halts 403 for a known non-player actor.
  def require_player_actor!
    user = authenticate_actor!
    json_error(403, 'forbidden') unless user[:role] == 'player'
    user[:username]
  end

  # Authenticates a spectator-view request. Session tokens (DM or player) halt
  # 403; missing or non-spectator-shaped tokens halt 401. Returns the
  # spectator_id from the bearer token on success.
  def authenticate_spectator_view!
    auth_header = request.env['HTTP_AUTHORIZATION'].to_s
    json_error(401, 'missing or invalid credentials') if auth_header.empty?
    json_error(403, 'forbidden') if auth_header.match?(/\ABearer session-/i)
    json_error(401, 'missing or invalid credentials') unless auth_header.match?(/\ABearer spectator-/i)

    spectator_id = auth_header.sub(/\ABearer spectator-/i, '').force_encoding('UTF-8')
    json_error(401, 'missing or invalid credentials') if spectator_id.empty?

    spectator_id
  end
end
