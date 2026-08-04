class ServiceModeController < ApplicationController
  before_action :require_authentication
  before_action :require_dm

  # POST /v1/play/campaigns/:id/service-mode
  # Only an authenticated DM may toggle the global maintenance switch.
  def update
    maintenance = @body['maintenance']
    unless maintenance == true || maintenance == false
      bad_request('invalid maintenance value')
      return
    end

    GameStorage.with_lock do
      campaign = GameStorage.db.get_first_row(
        'SELECT id FROM play_campaigns WHERE id = ?',
        params[:id]
      )
      unless campaign
        render json: { error: 'campaign not found' }, status: :not_found
        return
      end

      GameStorage.maintenance = maintenance
      render json: { maintenance: GameStorage.maintenance? }, status: :ok
    end
  end
end
