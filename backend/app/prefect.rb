require 'httparty'
require 'json'

module Prefect
  BASE_URL = ENV['PREFECT_API_URL'] || 'http://prefect-server:4200/api'

  def self.create_flow_run(deployment_id, parameters)
    response = HTTParty.post(
      "#{BASE_URL}/deployments/#{deployment_id}/create_flow_run",
      headers: { 'Content-Type' => 'application/json' },
      body: { parameters: parameters }.to_json
    )

    unless response.success?
      raise "Prefect API error: #{response.code} - #{response.body}"
    end

    JSON.parse(response.body)
  end

  def self.get_flow_run(flow_run_id)
    response = HTTParty.get(
      "#{BASE_URL}/flow_runs/#{flow_run_id}",
      headers: { 'Content-Type' => 'application/json' }
    )

    unless response.success?
      raise "Prefect API error: #{response.code} - #{response.body}"
    end

    JSON.parse(response.body)
  end

  def self.get_flow_run_state(flow_run_id)
    flow_run = get_flow_run(flow_run_id)
    flow_run.dig('state', 'name') || 'Unknown'
  end
end
