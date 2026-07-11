require_relative 'app'
require 'puma'
require 'puma/server'

port = Integer(ENV.fetch('PORT'))

server = Puma::Server.new(
  Sinatra::Application,
  nil,
  min_threads: 0,
  max_threads: 5,
  environment: ENV.fetch('RACK_ENV', 'production')
)

server.add_tcp_listener('127.0.0.1', port)
thread = server.run

shutdown = proc { server.stop(true) }
Signal.trap('INT', &shutdown)
Signal.trap('TERM', &shutdown)

thread.join
