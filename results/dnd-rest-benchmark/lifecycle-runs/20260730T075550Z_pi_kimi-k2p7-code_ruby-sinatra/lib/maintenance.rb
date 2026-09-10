# frozen_string_literal: true

# Process-global maintenance switch for the readiness probe.
module Maintenance
  @mutex = Mutex.new
  @enabled = false

  def self.enabled?
    @mutex.synchronize { @enabled }
  end

  def self.enabled=(value)
    @mutex.synchronize { @enabled = value }
  end
end
