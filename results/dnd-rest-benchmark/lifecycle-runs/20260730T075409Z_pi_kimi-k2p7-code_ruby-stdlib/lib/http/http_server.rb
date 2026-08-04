# frozen_string_literal: true

require 'socket'
require 'json'
require_relative '../config'
require_relative '../persistence'
require_relative 'request'
require_relative 'response'
require_relative 'router'

# TCP server loop.
module HttpServer
  def self.run
    Persistence.reset!
    server = TCPServer.new(Config::HOST, Config::PORT)
    puts "Server listening on #{Config::HOST}:#{Config::PORT}"

    loop do
      begin
        client = server.accept
        Thread.new(client) { |c| handle(c) }
      rescue StandardError => e
        warn "Error accepting connection: #{e.message}"
      end
    end
  end

  # Each connection is handled in its own thread. The server reads requests on
  # the same connection until the client closes it (or sends Connection: close),
  # supporting HTTP/1.1 keep-alive without blocking the accept loop. Database
  # access is already serialized by Persistence.
  def self.handle(client)
    loop do
      request = Request.parse(client)
      break if request.nil?

      response = Router.route(request)
      client.write(response.to_s)

      connection = request.headers['connection']
      break if connection && connection.downcase == 'close'
    end
  rescue StandardError => e
    warn "Request handler error: #{e.message}"
    client.write(Response.new(500, JSON.generate({ error: 'internal server error' })).to_s)
  ensure
    client.close
  end
end
