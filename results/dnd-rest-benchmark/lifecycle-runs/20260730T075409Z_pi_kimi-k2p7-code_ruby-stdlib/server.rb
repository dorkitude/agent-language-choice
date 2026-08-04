#!/usr/bin/env ruby
# frozen_string_literal: true

# D&D DM Tools API
#
# A minimal TCP HTTP server built on Ruby's standard library plus SQLite.
# Domain logic lives in lib/; each module is either side-effect free or owns
# its own persistence boundary. HTTP parsing, routing, and JSON serialization
# live in lib/http/ so domain code stays independent of transport details.

require 'socket'
require 'json'
require 'openssl'
require 'securerandom'
require 'base64'
require 'sqlite3'

require_relative 'lib/config'
require_relative 'lib/persistence'
require_relative 'lib/pure_rules'
require_relative 'lib/auth'
require_relative 'lib/combat'
require_relative 'lib/compendium'
require_relative 'lib/campaigns'
require_relative 'lib/quests'
require_relative 'lib/factions'
require_relative 'lib/inventory'
require_relative 'lib/crafting'
require_relative 'lib/sessions'
require_relative 'lib/analytics'
require_relative 'lib/play_campaigns'
require_relative 'lib/player_handbook'
require_relative 'lib/dm_tools'
require_relative 'lib/http/request'
require_relative 'lib/http/response'
require_relative 'lib/http/router'
require_relative 'lib/http/http_server'

HttpServer.run if __FILE__ == $0
