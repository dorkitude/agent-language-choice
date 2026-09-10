# frozen_string_literal: true

require 'cgi'

# HTTP request parsing.
class Request
  attr_reader :method, :path, :headers, :body, :query

  def initialize(method, path, query, headers, body)
    @method = method
    @path = path
    @query = query
    @headers = headers
    @body = body
  end

  def self.parse(io)
    line = io.gets
    return nil unless line

    parts = line.split(' ')
    return nil if parts.length < 2

    method = parts[0]
    full_path = parts[1]
    path_parts = full_path.split('?', 2)
    path = path_parts[0].force_encoding(Encoding::UTF_8)
    query = path_parts[1] || ''

    headers = {}
    loop do
      header_line = io.gets
      return nil unless header_line
      break if header_line == "\r\n" || header_line == "\n"

      key, value = header_line.split(':', 2)
      headers[key.strip.downcase] = value.strip if key && value
    end

    body = nil
    content_length = headers['content-length']
    if content_length
      length = content_length.to_i
      body = io.read(length) if length > 0
    end

    new(method, path, query, headers, body)
  end

  def query_params
    query.to_s.split('&').each_with_object({}) do |pair, h|
      key, value = pair.split('=', 2)
      h[CGI.unescape(key.to_s)] = CGI.unescape(value.to_s)
    end
  end
end
