# Bearer-token authentication for the /v1/play surface. Tokens are the
# placeholder `session-<username>` values issued by /v1/auth/login; there is
# no expiry, so a valid token just needs to name a real user.
#
# A malformed/missing token is 401 (not authenticated at all). A
# well-formed token naming an unknown user is 403: the caller presented
# *some* identity, it just isn't authorized here.

def authenticate_play_request!
  auth_header = request.env['HTTP_AUTHORIZATION']
  halt 401, { error: 'missing credentials' }.to_json unless auth_header

  match = auth_header.match(/\ABearer session-(.+)\z/)
  halt 401, { error: 'invalid credentials' }.to_json unless match

  # Rack header values arrive ASCII-8BIT; the sqlite3 gem binds ASCII-8BIT
  # strings as BLOB, which never matches the TEXT username column.
  username = match[1].dup.force_encoding(Encoding::UTF_8)
  user = db.execute('SELECT * FROM users WHERE username = ?', [username]).first
  halt 403, { error: 'not a campaign member' }.to_json unless user

  user
end
