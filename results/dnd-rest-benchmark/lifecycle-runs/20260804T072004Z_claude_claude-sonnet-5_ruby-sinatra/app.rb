# D&D REST API — entry point.
#
# Classic-style Sinatra app: this file and everything it requires share one
# top-level request-handling context, so route files under routes/ can call
# the helpers defined in lib/ directly (no explicit includes needed).
#
# Module layout:
#   lib/database.rb         - SQLite connection (per-thread) and schema DDL
#   lib/request_helpers.rb  - JSON body parsing and generic value validators
#   lib/security.rb         - password hashing/verification for auth
#   lib/dnd_rules.rb         - CR/XP tables, encounter difficulty math
#   lib/combat_session.rb   - initiative ordering + combat session persistence
#   lib/campaigns.rb        - shared campaign lookup
#   lib/analytics.rb        - deterministic campaign readiness/risk scoring
#   lib/play_auth.rb        - bearer-token auth for the /v1/play surface
#   lib/play_campaigns.rb   - shared lookups/helpers for /v1/play routes
#   routes/*.rb             - one file per API domain (see CODEBASE.md)
#   routes/play/*.rb        - the /v1/play surface, split by sub-domain
#                              (campaigns, turns, document, scenes,
#                              locations, encounters, characters) since it
#                              is large enough to outgrow a single file
require 'sinatra'
require 'json'

set :show_exceptions, false
set :raise_errors, false

# Puma's default min_threads is 0, so under load it may need to spin up a
# fresh thread to accept a connection instead of reusing a warm one; keep a
# few threads always warm so request handling doesn't stall on that.
set :server_settings, Threads: '4:8'

require_relative 'lib/database'
require_relative 'lib/request_helpers'
require_relative 'lib/security'
require_relative 'lib/dnd_rules'
require_relative 'lib/combat_session'
require_relative 'lib/campaigns'
require_relative 'lib/analytics'
require_relative 'lib/play_auth'
require_relative 'lib/play_campaigns'

init_schema!

before do
  content_type :json
end

require_relative 'routes/core'
require_relative 'routes/characters'
require_relative 'routes/combat'
require_relative 'routes/auth'
require_relative 'routes/compendium'
require_relative 'routes/campaigns'
require_relative 'routes/phb'
require_relative 'routes/dm'
require_relative 'routes/storage'
require_relative 'routes/quests'
require_relative 'routes/npcs'
require_relative 'routes/inventory'
require_relative 'routes/downtime'
require_relative 'routes/sessions'
require_relative 'routes/audit'
require_relative 'routes/analytics'
require_relative 'routes/play/campaigns'
require_relative 'routes/play/turns'
require_relative 'routes/play/document'
require_relative 'routes/play/scenes'
require_relative 'routes/play/locations'
require_relative 'routes/play/encounters'
require_relative 'routes/play/characters'
require_relative 'routes/play/spells'
require_relative 'routes/play/concentration'
require_relative 'routes/play/inventory'
require_relative 'routes/play/equipment'
require_relative 'routes/play/currency'
require_relative 'routes/play/loot'
require_relative 'routes/play/npcs'
require_relative 'routes/play/factions'
require_relative 'routes/play/relationships'
require_relative 'routes/play/clues'
require_relative 'routes/play/quests'
require_relative 'routes/play/world_events'
require_relative 'routes/play/calendar'
require_relative 'routes/play/settlements'
require_relative 'routes/play/shops'
require_relative 'routes/play/recipes'
require_relative 'routes/play/downtime'
require_relative 'routes/play/session_zero'
require_relative 'routes/play/content'
require_relative 'routes/play/notes'
require_relative 'routes/play/whispers'
require_relative 'routes/play/invitations'
require_relative 'routes/play/delegations'
