package main

import "net/http"

const apiSchema = `{"version":"2026-07-29","endpoints":[{"method":"GET","path":"/v1/play/campaigns/{id}/rng-ledger","auth":"member"},{"method":"GET","path":"/v1/schema","auth":"public"},{"method":"POST","path":"/v1/play/campaigns","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/fixture-seeds","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/members","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/moderation/reports","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/rng-rolls","auth":"member"},{"method":"PUT","path":"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/rng-seed","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/safety-boundaries","auth":"dm"}]}`

// schemaHandler returns the public API schema. It does not read or mutate any
// campaign state, so repeated requests produce the same deterministic output.
func schemaHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(apiSchema))
}
