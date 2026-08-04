#!/usr/bin/env ruby
# frozen_string_literal: true

# Entry point: wires up the SQLite schema and starts a single-threaded,
# blocking-accept TCP server. See CODEBASE.md for the module map and
# request-routing design.

require 'socket'
require_relative 'lib/database'
require_relative 'lib/http_server'

PORT = (ENV['PORT'] || 8080).to_i
HOST = '127.0.0.1'

# Each server process starts from a clean database: without this, a database
# file left behind by a prior process (e.g. a crashed run) causes spurious
# "username already exists" conflicts for fixed test usernames like "dm".
File.delete(Database.path) if File.exist?(Database.path)
Database.init_schema

server = TCPServer.new(HOST, PORT)
puts "Listening on #{HOST}:#{PORT}"

loop do
  client = server.accept
  HttpServer.handle_connection(client)
end
