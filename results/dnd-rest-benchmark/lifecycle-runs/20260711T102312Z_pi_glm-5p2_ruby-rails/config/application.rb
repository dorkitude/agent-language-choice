# frozen_string_literal: true

require_relative "boot"

require "logger"
require "rails"
require "action_controller/railtie"

module Dnd
  class Application < Rails::Application
    config.api_only = true
    config.eager_load = false
    config.cache_classes = false
    config.consider_all_requests_local = false
    config.log_level = :warn
    config.logger = Logger.new($stdout)
    # No host authorization checks for the benchmark.
    config.hosts.clear
    # A stable secret key base is required by some Rails internals even for
    # API-only apps; this dummy value is never used for real cookies/sessions.
    config.secret_key_base = "dnd_rest_benchmark_api_only_secret_key_base_0123456789abcdef"
  end
end
