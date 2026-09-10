# frozen_string_literal: true

# Route definitions for storage endpoints.

# --- Storage ---

get '/v1/storage/status' do
  content_type :json
  JSON.dump(
    driver: 'sqlite',
    schema_version: Storage::SCHEMA_VERSION,
    initialized: Storage.initialized?
  )
end

post '/v1/storage/reset' do
  content_type :json
  begin
    Storage.reset!
    JSON.dump(ok: true, schema_version: Storage::SCHEMA_VERSION)
  rescue SQLite3::Exception
    json_error(500, 'storage reset failed')
  end
end

