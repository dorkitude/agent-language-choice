class HealthController < ApplicationController
  def index
    render json: { ok: true }
  end

  # Public liveness probe. Maintenance mode must not affect liveness.
  def liveness
    render json: { status: 'ok' }
  end

  # Public readiness probe. Reports maintenance when the global switch is set.
  def readiness
    if GameStorage.maintenance?
      render json: { status: 'maintenance', schema_version: 2 }, status: :service_unavailable
    else
      render json: { status: 'ready', schema_version: 2 }
    end
  end
end
