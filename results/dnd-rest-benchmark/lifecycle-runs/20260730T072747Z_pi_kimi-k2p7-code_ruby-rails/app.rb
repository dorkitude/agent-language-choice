require 'rails'
require 'action_controller/railtie'
require 'json'
require 'logger'
require 'bcrypt'
require 'sqlite3'
require 'set'

require_relative 'app/models/game_storage'

module Dnd
  class Application < Rails::Application
    config.load_defaults 8.1
    config.api_only = true
    config.eager_load = false
    config.hosts.clear
    config.secret_key_base = 'd3d-rest-benchmark-secret-key-base-32bytes-long-enough-1234567890'
    config.logger = Logger.new($stdout)
    config.log_level = :fatal

    config.action_controller.allow_forgery_protection = false
  end
end

Dnd::Application.initialize!
GameStorage.init

# Reset the database on every boot so the server starts from a deterministic,
# empty state. This matches the benchmark contract where tests reset storage
# explicitly, but it also guarantees no stale data from a previous run leaks
# into the current process.
GameStorage.reset
