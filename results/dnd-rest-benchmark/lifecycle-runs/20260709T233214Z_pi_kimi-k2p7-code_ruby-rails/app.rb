ENV['BUNDLE_GEMFILE'] ||= File.expand_path('Gemfile', __dir__)

require 'bundler/setup'
require 'rails'
require 'action_controller/railtie'

$combat_sessions = {}

class App < Rails::Application
  config.load_defaults 8.1
  config.eager_load = false
  config.api_only = true

  config.secret_key_base = ENV.fetch('SECRET_KEY_BASE', 'x' * 32)
  config.hosts.clear
  config.consider_all_requests_local = false
  config.log_level = :fatal
  config.action_dispatch.show_exceptions = :all
  config.logger = ActiveSupport::Logger.new(nil)
end

require_relative 'config/routes'
Rails.application.initialize!
