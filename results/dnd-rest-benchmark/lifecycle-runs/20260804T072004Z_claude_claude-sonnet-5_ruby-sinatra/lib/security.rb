# Password hashing for /v1/auth. Uses PBKDF2-HMAC-SHA256 with a random salt
# per user and a constant-time comparison to avoid timing side channels.

require 'openssl'
require 'securerandom'

PBKDF2_ITERATIONS = 100_000

def hash_password(password, salt = SecureRandom.hex(16))
  digest = OpenSSL::PKCS5.pbkdf2_hmac(password, salt, PBKDF2_ITERATIONS, 32, OpenSSL::Digest.new('SHA256'))
  { salt: salt, hash: digest.unpack1('H*') }
end

def verify_password(password, salt, expected_hash)
  computed = hash_password(password, salt)[:hash]
  computed_bytes = [computed].pack('H*')
  expected_bytes = [expected_hash].pack('H*')
  return false unless computed_bytes.bytesize == expected_bytes.bytesize

  OpenSSL.fixed_length_secure_compare(computed_bytes, expected_bytes)
end
