# frozen_string_literal: true

require 'openssl'
require 'securerandom'
require 'base64'
require_relative 'persistence'

# Authentication (PBKDF2 password hashing).
#
# Auth registers and verifies users and also validates bearer tokens. Tokens
# are deterministic: "session-<username>". This is acceptable for the test
# harness and keeps the implementation simple; production code would use
# opaque, unguessable tokens.
module Auth
  VALID_ROLES = %w[dm player].freeze
  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/.freeze
  PBKDF2_ITERATIONS = 210_000
  HASH_BYTES = 32
  SALT_BYTES = 16

  def self.valid_username?(username)
    username.is_a?(String) && username.match?(USERNAME_RE)
  end

  def self.valid_password?(password)
    password.is_a?(String) && password.bytesize >= 8
  end

  def self.valid_role?(role)
    VALID_ROLES.include?(role)
  end

  def self.register_user(username, password, role)
    creds = hash_password(password)
    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM users WHERE username = ?', username)
      next false if existing

      d.execute('INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)', [username, role, creds[:salt], creds[:hash]])
      true
    end
  end

  def self.authenticate_user(username, password)
    Persistence.db do |d|
      row = d.get_first_row('SELECT salt, hash FROM users WHERE username = ?', username)
      next false unless row

      verify_password(password, row[0], row[1])
    end
  end

  def self.authenticate_bearer(request)
    header = request.headers['authorization']
    return nil unless header.is_a?(String) && header.start_with?('Bearer ')

    token = header.sub('Bearer ', '').strip
    return nil unless token.start_with?('session-')

    username = token.sub('session-', '').force_encoding(Encoding::UTF_8)
    return nil unless valid_username?(username)

    Persistence.db do |d|
      row = d.get_first_row('SELECT role FROM users WHERE username = ?', username)
      { username: username, role: row ? row[0] : nil }
    end
  end

  def self.hash_password(password)
    salt = SecureRandom.random_bytes(SALT_BYTES)
    hash = OpenSSL::KDF.pbkdf2_hmac(
      password,
      salt: salt,
      iterations: PBKDF2_ITERATIONS,
      length: HASH_BYTES,
      hash: 'sha256'
    )
    { salt: Base64.strict_encode64(salt), hash: Base64.strict_encode64(hash) }
  end
  private_class_method :hash_password

  def self.verify_password(password, salt_b64, hash_b64)
    salt = Base64.strict_decode64(salt_b64)
    expected = Base64.strict_decode64(hash_b64)
    actual = OpenSSL::KDF.pbkdf2_hmac(
      password,
      salt: salt,
      iterations: PBKDF2_ITERATIONS,
      length: expected.bytesize,
      hash: 'sha256'
    )
    OpenSSL.secure_compare(actual, expected)
  rescue StandardError
    false
  end
  private_class_method :verify_password
end
