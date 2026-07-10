require "rails"
require "action_controller/railtie"
require "logger"

module DndApi
  class Application < Rails::Application
    config.root = File.expand_path("..", __dir__)
    config.api_only = true
    config.secret_key_base = "dnd_rest_benchmark_minimal_secret_key_base_0123456789abcdef"

    config.eager_load = false
    config.cache_classes = true

    # Allow any Host header (benchmark hits 127.0.0.1:PORT).
    config.hosts.clear if config.respond_to?(:hosts)

    # Keep stdout clean for the harness.
    config.logger = Logger.new(IO::NULL)
    config.log_level = :fatal
  end
end
