package main

import "net/http"

type schemaEndpoint struct {
	Method string `json:"method"`
	Path   string `json:"path"`
	Auth   string `json:"auth"`
}

type apiSchema struct {
	Version   string           `json:"version"`
	Endpoints []schemaEndpoint `json:"endpoints"`
}

var apiSchemaResponse = apiSchema{
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

func handleAPISchema(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, apiSchemaResponse)
}
