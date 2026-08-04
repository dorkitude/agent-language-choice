class AuthController < ApplicationController
  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/.freeze

  def register
    username = @body['username']
    password = @body['password']
    role = @body['role']

    unless username.is_a?(String) && USERNAME_RE.match?(username)
      bad_request('invalid username')
      return
    end

    unless password.is_a?(String) && password.length >= 8
      bad_request('invalid password')
      return
    end

    unless role == 'dm' || role == 'player'
      bad_request('invalid role')
      return
    end

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO users (username, password_digest, role) VALUES (?, ?, ?)',
          [username, BCrypt::Password.create(password), role]
        )
        render json: { username: username, role: role }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'username taken' }, status: :conflict
      end
    end
  end

  def login
    username = @body['username']
    password = @body['password']

    unless username.is_a?(String) && password.is_a?(String)
      bad_request('invalid request')
      return
    end

    row = GameStorage.db.get_first_row(
      'SELECT username, password_digest, role FROM users WHERE username = ?',
      username
    )

    if row && BCrypt::Password.new(row[1]) == password
      render json: { username: username, token: "session-#{username}" }
    else
      render json: { error: 'invalid credentials' }, status: :unauthorized
    end
  end
end
