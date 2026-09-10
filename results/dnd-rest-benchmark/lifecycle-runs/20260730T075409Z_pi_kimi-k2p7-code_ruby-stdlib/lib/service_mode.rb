# frozen_string_literal: true

# Process-global maintenance switch used by readiness and service-mode
# endpoints. It is independent of any individual campaign.
module ServiceMode
  @mutex = Mutex.new
  @maintenance = false

  def self.maintenance?
    @mutex.synchronize { @maintenance }
  end

  def self.maintenance=(value)
    @mutex.synchronize { @maintenance = !!value }
  end
end
