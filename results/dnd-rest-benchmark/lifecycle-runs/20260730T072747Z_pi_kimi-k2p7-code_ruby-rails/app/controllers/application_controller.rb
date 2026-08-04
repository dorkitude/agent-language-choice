class ApplicationController < ActionController::API
  include DndRules
  before_action :parse_json_body

  private

  # Parse the JSON body into @body before every action. Rewind the Rack input so
  # that later middleware can read it again if necessary. On invalid JSON, stop
  # the request immediately with a 400 response.
  def parse_json_body
    @body = {}
    if request.media_type == 'application/json' && request.body
      raw = request.body.read
      request.body.rewind if request.body.respond_to?(:rewind)
      @body = JSON.parse(raw) unless raw.empty?
    end
  rescue JSON::ParserError
    render json: { error: 'invalid json' }, status: :bad_request
  end

  def bad_request(message = 'bad request')
    render json: { error: message }, status: :bad_request
  end

  def require_authentication
    return if performed?

    auth_header = request.authorization
    unless auth_header.to_s.start_with?('Bearer ')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    token = auth_header.to_s.sub('Bearer ', '').strip
    unless token.start_with?('session-')
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    username = token.sub('session-', '').force_encoding(Encoding::UTF_8)
    if username.empty?
      render json: { error: 'unauthorized' }, status: :unauthorized
      return
    end

    # The play surface uses the bearer token itself as the session proof.
    # Only the reserved username 'dm' is treated as a DM; every other valid
    # session bearer is a player.
    @current_user = { username: username, role: username == 'dm' ? 'dm' : 'player' }
  end

  def require_dm
    return if performed?

    unless @current_user && @current_user[:role] == 'dm'
      render json: { error: 'forbidden' }, status: :forbidden
    end
  end
end
