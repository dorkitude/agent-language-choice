# frozen_string_literal: true

# Raised by handlers to short-circuit a request with a specific HTTP status.
# Rescued centrally in HttpServer#handle_connection and turned into a JSON
# error response.
class HttpError < StandardError
  attr_reader :status

  def initialize(status, message)
    super(message)
    @status = status
  end
end
