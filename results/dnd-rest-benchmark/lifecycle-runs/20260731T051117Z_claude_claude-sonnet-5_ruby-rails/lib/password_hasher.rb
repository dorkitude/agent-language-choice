require 'bcrypt'

module PasswordHasher
  def self.hash(password)
    BCrypt::Password.create(password)
  end

  def self.verify(password, digest)
    BCrypt::Password.new(digest) == password
  rescue BCrypt::Errors::InvalidHash
    false
  end
end
