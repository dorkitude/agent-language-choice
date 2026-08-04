# frozen_string_literal: true

# HTTP request parsing.
class Request
  attr_reader :method, :path, :headers, :body

  def initialize(method, path, headers, body)
    @method = method
    @path = path
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
    path = full_path.split('?', 2).first.force_encoding(Encoding::UTF_8)

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

    new(method, path, headers, body)
  end
end
