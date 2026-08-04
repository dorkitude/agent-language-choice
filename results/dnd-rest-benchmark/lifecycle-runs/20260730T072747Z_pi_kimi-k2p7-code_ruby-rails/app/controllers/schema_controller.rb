# Public API schema endpoint.
# Returns the static, versioned list of supported endpoints without any
# authentication requirement and without touching campaign or fixture state.
class SchemaController < ActionController::API
  SCHEMA = {
    version: '2026-07-29',
    endpoints: [
      { method: 'GET',  path: '/v1/play/campaigns/{id}/rng-ledger',                         auth: 'member' },
      { method: 'GET',  path: '/v1/schema',                                                  auth: 'public' },
      { method: 'POST', path: '/v1/play/campaigns',                                          auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/fixture-seeds',                      auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/members',                            auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/moderation/reports',                 auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/rng-rolls',                         auth: 'member' },
      { method: 'PUT',  path: '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', auth: 'dm' },
      { method: 'PUT',  path: '/v1/play/campaigns/{id}/rng-seed',                          auth: 'dm' },
      { method: 'PUT',  path: '/v1/play/campaigns/{id}/safety-boundaries',                 auth: 'dm' }
    ].freeze
  }.freeze

  def show
    render json: SCHEMA
  end
end
