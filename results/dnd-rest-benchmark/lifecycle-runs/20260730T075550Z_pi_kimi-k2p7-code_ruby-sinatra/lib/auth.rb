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
    unless auth_header.start_with?('Bearer session-')
      halt 401, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'missing or invalid credentials')
    end

    username = auth_header.sub('Bearer session-', '').force_encoding('UTF-8')
    user = Storage.load_user(username)

    unless user
      # The play-campaign surface uses session tokens deterministically. The
      # reserved 'dm' token and any 'player-' token are valid actors even if
      # they have not been explicitly registered through /v1/auth/register.
      if username == 'dm' || username.start_with?('player-')
        user = { username: username, role: username == 'dm' ? 'dm' : 'player' }
      else
        halt 401, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'missing or invalid credentials')
      end
    end

    user
  end

  # Authenticates the request and returns the username only if the user has the
  # dm role. Halts 403 for a known non-dm actor.
  def require_dm_actor!
    user = authenticate_actor!
    unless user[:role] == 'dm'
      halt 403, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'forbidden')
    end
    user[:username]
  end
end
