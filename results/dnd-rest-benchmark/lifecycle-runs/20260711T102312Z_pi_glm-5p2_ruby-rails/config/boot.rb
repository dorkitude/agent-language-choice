# frozen_string_literal: true

# Gems are installed into the default GEM_PATH via `gem install`, so this
# minimal API app does not require Bundler at boot. We only pin the Gemfile
# location for reference.
ENV["BUNDLE_GEMFILE"] ||= File.expand_path("../Gemfile", __dir__)
