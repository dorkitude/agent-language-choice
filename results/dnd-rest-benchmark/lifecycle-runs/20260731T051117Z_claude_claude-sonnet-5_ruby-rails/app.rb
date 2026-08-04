# Entry point for the D&D REST benchmark API. This is a minimal, non-
# generated Rails API app: rather than relying on `rails new`'s directory
# conventions and Zeitwerk autoloading, every file is required explicitly
# in dependency order below. See CODEBASE.md for the full architecture.
require 'rails'
require 'action_controller/railtie'

class DndApp < Rails::Application
  config.eager_load = false
  config.logger = Logger.new(IO::NULL)
  config.log_level = :fatal
  config.hosts.clear
  config.api_only = true
  config.secret_key_base = 'benchmark_secret_key_base'
end

require_relative 'lib/game_data'
require_relative 'lib/game_storage'
require_relative 'lib/persistent_collections'
require_relative 'lib/password_hasher'

GameStorage.connect

COMBAT_SESSIONS = PersistentCombatSessions.new
USERS = PersistentUsers.new
MONSTERS = PersistentCompendium.new('monsters')
ITEMS = PersistentCompendium.new('items')
CAMPAIGNS = PersistentCampaigns.new
PLAY_CAMPAIGNS = PersistentPlayCampaigns.new

require_relative 'app/controllers/application_controller'
require_relative 'app/controllers/core_controller'
require_relative 'app/controllers/characters_controller'
require_relative 'app/controllers/combat_controller'
require_relative 'app/controllers/auth_controller'
require_relative 'app/controllers/storage_controller'
require_relative 'app/controllers/compendium_controller'
require_relative 'app/controllers/campaigns_controller'
require_relative 'app/controllers/quests_controller'
require_relative 'app/controllers/phb_controller'
require_relative 'app/controllers/dm_controller'
require_relative 'app/controllers/npcs_controller'
require_relative 'app/controllers/inventory_controller'
require_relative 'app/controllers/downtime_controller'
require_relative 'app/controllers/sessions_controller'
require_relative 'app/controllers/audit_controller'
require_relative 'app/controllers/analytics_controller'
require_relative 'app/controllers/play_controller'

DndApp.initialize!

require_relative 'config/routes'
