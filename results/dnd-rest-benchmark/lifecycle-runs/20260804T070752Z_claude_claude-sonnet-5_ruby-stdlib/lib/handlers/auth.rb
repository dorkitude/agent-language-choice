# frozen_string_literal: true

require 'openssl'
require 'securerandom'
require_relative '../errors'
require_relative '../database'

module Handlers
  # User registration and login. Passwords are hashed with PBKDF2-HMAC-SHA256
  # and a per-user random salt; the login "token" is a deterministic
  # placeholder (not a real session token) sufficient for this API's tests.
  module Auth
    PBKDF2_ITERATIONS = 100_000
    PBKDF2_LENGTH = 32
    PBKDF2_DIGEST = OpenSSL::Digest.new('SHA256')
    USERNAME_PATTERN = /\A[a-z0-9_-]{2,32}\z/

    module_function

    def register(body)
      username = body['username']
      password = body['password']
      role = body['role']

      raise HttpError.new(400, 'username must be 2-32 chars of lowercase letters, digits, _ or -') unless username.is_a?(String) && USERNAME_PATTERN.match?(username)
      raise HttpError.new(400, 'password must be at least 8 characters') unless password.is_a?(String) && password.length >= 8
      raise HttpError.new(400, "role must be 'dm' or 'player'") unless %w[dm player].include?(role)
      raise HttpError.new(409, 'username already exists') unless Database.query("SELECT username FROM users WHERE username = #{Database.escape(username)};").empty?

      salt = SecureRandom.hex(16)
      digest = hash_password(password, salt)
      Database.exec("INSERT INTO users (username, role, salt, digest) VALUES (#{Database.escape(username)}, #{Database.escape(role)}, #{Database.escape(salt)}, #{Database.escape(digest)});")

      [201, { username: username, role: role }]
    end

    def login(body)
      username = body['username']
      password = body['password']

      raise HttpError.new(400, 'username must be a string') unless username.is_a?(String)
      raise HttpError.new(400, 'password must be a string') unless password.is_a?(String)

      user = Database.query("SELECT username, salt, digest FROM users WHERE username = #{Database.escape(username)};").first
      raise HttpError.new(401, 'invalid credentials') unless user && password_matches?(password, user['salt'], user['digest'])

      [200, { username: username, token: "session-#{username}" }]
    end

    # Resolves the "Authorization: Bearer session-<username>" header used by
    # protected routes into the authenticated actor's {username:, role:}.
    # Also recognizes "Bearer spectator-<id>" tickets, returning
    # {username: nil, role: 'spectator', spectator_id:} so spectator-only
    # routes can check for that shape without a separate auth path. Raises
    # 401 for a missing header or malformed token. A well-formed session
    # token for an unregistered username still authenticates (role: nil) so
    # route-level permission checks can return 403 rather than 401 for it.
    def authenticate(headers)
      header = headers && headers['authorization']
      raise HttpError.new(401, 'missing bearer token') unless header

      session_match = /\ABearer session-([a-z0-9_-]{2,32})\z/.match(header)
      if session_match
        username = session_match[1]
        user = Database.query("SELECT username, role FROM users WHERE username = #{Database.escape(username)};").first
        return { username: username, role: user && user['role'] }
      end

      spectator_match = /\ABearer spectator-(.+)\z/.match(header)
      raise HttpError.new(401, 'invalid bearer token') unless spectator_match

      { username: nil, role: 'spectator', spectator_id: spectator_match[1] }
    end

    def hash_password(password, salt)
      OpenSSL::PKCS5.pbkdf2_hmac(password, salt, PBKDF2_ITERATIONS, PBKDF2_LENGTH, PBKDF2_DIGEST).unpack1('H*')
    end

    def password_matches?(password, salt, digest_hex)
      candidate = hash_password(password, salt)
      OpenSSL.fixed_length_secure_compare(candidate, digest_hex)
    rescue ArgumentError
      false
    end
  end
end
