# Shared request-parsing and value-shape helpers used across all route files.

require 'json'

def json_body
  request.body.rewind
  raw = request.body.read
  JSON.parse(raw.empty? ? '{}' : raw)
rescue JSON::ParserError
  nil
end

def numericish(v)
  v.is_a?(Numeric)
end

# True for values JSON could only have produced as a whole number, including
# floats like 3.0 that arrive that way because the client's JSON encoder
# always emits decimals.
def integerish(v)
  v.is_a?(Integer) || (v.is_a?(Float) && v.finite? && v == v.to_i)
end

def valid_username?(username)
  username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
end

def valid_slug?(slug)
  slug.is_a?(String) && slug.match?(/\A[a-z0-9-]{1,64}\z/)
end
