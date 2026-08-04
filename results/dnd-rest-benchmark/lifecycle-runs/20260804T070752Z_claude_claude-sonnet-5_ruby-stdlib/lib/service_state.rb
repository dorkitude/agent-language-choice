# frozen_string_literal: true

# Process-global service mode, shared by every campaign for the lifetime of
# this server process. Set via POST /v1/play/campaigns/{id}/service-mode by
# any owning dm; read by the public GET /readyz liveness/readiness split.
module ServiceState
  @maintenance = false

  class << self
    attr_writer :maintenance
  end

  def self.maintenance?
    @maintenance
  end
end
