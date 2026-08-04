# frozen_string_literal: true

require_relative '../database'

module Handlers
  # Introspection and reset for the persistence layer. `reset` drops and
  # recreates every table, wiping all data (used by the test suite to get a
  # clean slate between scenarios).
  module Storage
    module_function

    def status(_body)
      [200, { driver: 'sqlite', schema_version: Database::SCHEMA_VERSION, initialized: File.exist?(Database.path) }]
    end

    def reset(_body)
      Database.reset_schema
      [200, { ok: true, schema_version: Database::SCHEMA_VERSION }]
    end
  end
end
