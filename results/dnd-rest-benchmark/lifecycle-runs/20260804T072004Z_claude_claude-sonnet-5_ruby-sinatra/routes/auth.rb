# User registration and login. Passwords are PBKDF2-hashed (lib/security.rb);
# login returns a placeholder bearer token — there is no session store or
# expiry, since no route currently checks it.

post '/v1/auth/register' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  username = body['username']
  password = body['password']
  role = body['role']

  halt 400, { error: 'invalid username' }.to_json unless valid_username?(username)
  halt 400, { error: 'invalid password' }.to_json unless password.is_a?(String) && password.length >= 8
  halt 400, { error: 'invalid role' }.to_json unless %w[dm player].include?(role)
  halt 409, { error: 'username already exists' }.to_json if db.execute('SELECT 1 FROM users WHERE username = ?', [username]).first

  hashed = hash_password(password)
  db.execute('INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)', [username, role, hashed[:salt], hashed[:hash]])

  status 201
  { username: username, role: role }.to_json
end

post '/v1/auth/login' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  username = body['username']
  password = body['password']

  halt 400, { error: 'invalid username' }.to_json unless username.is_a?(String)
  halt 400, { error: 'invalid password' }.to_json unless password.is_a?(String)

  user = db.execute('SELECT * FROM users WHERE username = ?', [username]).first
  halt 401, { error: 'invalid credentials' }.to_json unless user
  halt 401, { error: 'invalid credentials' }.to_json unless verify_password(password, user['salt'], user['hash'])

  { username: username, token: "session-#{username}" }.to_json
end
