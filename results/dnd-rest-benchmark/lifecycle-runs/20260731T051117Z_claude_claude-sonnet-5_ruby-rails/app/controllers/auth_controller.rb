# User registration and login against the USERS persistent collection.
# Passwords are hashed with bcrypt (see lib/password_hasher.rb); the login
# "token" is a deterministic placeholder, not a real session credential.
class AuthController < ApplicationController
  def register
    username = params[:username]
    password = params[:password]
    role = params[:role]

    unless username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
      render json: { error: 'invalid username' }, status: :bad_request
      return
    end

    unless password.is_a?(String) && password.length >= 8
      render json: { error: 'invalid password' }, status: :bad_request
      return
    end

    unless %w[dm player].include?(role)
      render json: { error: 'invalid role' }, status: :bad_request
      return
    end

    if USERS.key?(username)
      render json: { error: 'duplicate username' }, status: :conflict
      return
    end

    USERS[username] = { role: role, password_digest: PasswordHasher.hash(password) }

    render json: { username: username, role: role }, status: :created
  end

  def login
    username = params[:username]
    password = params[:password]

    unless username.is_a?(String) && password.is_a?(String)
      render json: { error: 'invalid credentials' }, status: :bad_request
      return
    end

    user = USERS[username]
    if user.nil? || !PasswordHasher.verify(password, user[:password_digest])
      render json: { error: 'invalid credentials' }, status: :unauthorized
      return
    end

    render json: { username: username, token: "session-#{username}" }
  end
end
