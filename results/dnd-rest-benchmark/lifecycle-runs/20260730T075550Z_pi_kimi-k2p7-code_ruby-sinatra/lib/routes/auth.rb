# frozen_string_literal: true

# Route definitions for auth endpoints.

# --- Auth users ---

post '/v1/auth/register' do
  content_type :json
  body = parse_json_body

  username = body['username']
  password = body['password']
  role = body['role']

  validate_username!(username)
  validate_password!(password)
  validate_role!(role)

  json_error(409, 'username already exists') if Storage.user_exists?(username)

  Storage.register_user(username, hash_password_hex(password, username), role)

  status 201
  JSON.dump(username: username, role: role)
end

post '/v1/auth/login' do
  content_type :json
  body = parse_json_body

  username = body['username']
  password = body['password']

  user = Storage.load_user(username)
  unless user && user[:password_hash] == hash_password_hex(password, username)
    json_error(401, 'invalid credentials')
  end

  JSON.dump(username: username, token: "session-#{username}")
end

