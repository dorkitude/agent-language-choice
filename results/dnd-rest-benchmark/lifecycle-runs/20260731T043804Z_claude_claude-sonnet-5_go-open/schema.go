package main

import "net/http"

// schemaEndpoint describes one route in the public API schema.
type schemaEndpoint struct {
	Method string `json:"method"`
	Path   string `json:"path"`
	Auth   string `json:"auth"`
}

// schemaResponse is the exact shape returned by GET /v1/schema.
type schemaResponse struct {
	Version   string           `json:"version"`
	Endpoints []schemaEndpoint `json:"endpoints"`
}

// apiSchema is a static description of the public play API surface, sorted
// lexicographically by method then path. It carries no dynamic state.
var apiSchema = schemaResponse{
	Version: "2026-07-29",
	Endpoints: []schemaEndpoint{
		{Method: "GET", Path: "/v1/play/campaigns/{id}/rng-ledger", Auth: "member"},
		{Method: "GET", Path: "/v1/schema", Auth: "public"},
		{Method: "POST", Path: "/v1/play/campaigns", Auth: "dm"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/fixture-seeds", Auth: "dm"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/members", Auth: "member"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/moderation/reports", Auth: "member"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/rng-rolls", Auth: "member"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", Auth: "dm"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/rng-seed", Auth: "dm"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/safety-boundaries", Auth: "dm"},
	},
}

// schemaHandler serves the public, static API schema. It performs no auth
// check and mutates no state.
func schemaHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, apiSchema)
}
