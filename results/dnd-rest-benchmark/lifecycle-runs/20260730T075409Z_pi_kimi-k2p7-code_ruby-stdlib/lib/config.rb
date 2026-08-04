# frozen_string_literal: true

# Runtime configuration read from the environment.
module Config
  PORT = Integer(ENV.fetch('PORT', '3000'))
  HOST = '127.0.0.1'
  DB_PATH = 'game.db'
  SCHEMA_VERSION = 1
end
