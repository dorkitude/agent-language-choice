# Introspection and reset for the SQLite-backed game state.
class StorageController < ApplicationController
  def storage_status
    render json: {
      driver: 'sqlite',
      schema_version: SCHEMA_VERSION,
      initialized: GameStorage.initialized ? true : false
    }
  end

  def storage_reset
    GameStorage.reset
    render json: { ok: true, schema_version: SCHEMA_VERSION }
  end
end
