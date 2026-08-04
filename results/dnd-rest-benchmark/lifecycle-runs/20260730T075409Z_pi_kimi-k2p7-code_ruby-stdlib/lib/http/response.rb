# frozen_string_literal: true

# HTTP response building.
class Response
  STATUS_TEXT = {
    200 => 'OK',
    201 => 'Created',
    400 => 'Bad Request',
    401 => 'Unauthorized',
    403 => 'Forbidden',
    404 => 'Not Found',
    409 => 'Conflict',
    500 => 'Internal Server Error'
  }.freeze

  attr_reader :status, :body, :content_type

  def initialize(status, body, content_type: 'application/json')
    @status = status
    @body = body
    @content_type = content_type
  end

  def to_s
    [
      "HTTP/1.1 #{status} #{STATUS_TEXT.fetch(status, 'Unknown')}",
      "Content-Type: #{content_type}",
      "Content-Length: #{body.bytesize}",
      '',
      body
    ].join("\r\n")
  end
end
