class StorageController < ApplicationController
  def status
    render json: GameStorage.status
  end

  def reset
    GameStorage.reset
    render json: { ok: true, schema_version: GameStorage::SCHEMA_VERSION }
  end
end
