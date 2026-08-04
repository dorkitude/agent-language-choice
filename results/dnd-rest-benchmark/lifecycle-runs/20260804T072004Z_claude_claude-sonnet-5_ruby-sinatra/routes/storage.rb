# Storage introspection and a full reset (used by test setup/teardown).

get '/v1/storage/status' do
  { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: File.exist?(DB_PATH) }.to_json
end

post '/v1/storage/reset' do
  reset_schema!
  { ok: true, schema_version: SCHEMA_VERSION }.to_json
end
