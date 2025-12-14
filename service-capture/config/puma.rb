# frozen_string_literal: true

port ENV.fetch("PORT", "5000").to_i
environment ENV.fetch("RACK_ENV", "production")

# We must serialize capture per container, so threads > 1 doesn't increase throughput.
# Keeping threads low reduces concurrent request handling complexity.
threads 1, 2
workers 0

preload_app! false

# Log to stdout
stdout_redirect nil, nil, true
