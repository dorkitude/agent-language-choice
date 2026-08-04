package main

import (
	"encoding/json"
	"net/http"
)

// Shared HTTP plumbing. Every handler in this service speaks JSON in and JSON
// out, so response writing, body decoding, and method guards live here rather
// than being repeated per endpoint.

// writeJSON writes body as a JSON document with the given status. HTML escaping
// is disabled so string fields round-trip verbatim.
func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(body)
}

// writeError writes the canonical error envelope: {"error": "..."}.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// decodeBody decodes a single JSON value from the request body into dst.
// Trailing content after the first value is ignored, matching the behavior the
// cumulative suite was built against.
func decodeBody(r *http.Request, dst any) error {
	return json.NewDecoder(r.Body).Decode(dst)
}

// requirePost reports whether the request is a POST, answering 405 when not.
// It is only needed for routes registered without a method pattern; routes
// registered as "POST /path" are filtered by the mux itself.
func requirePost(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return false
	}
	return true
}

// requireGet reports whether the request is a GET or HEAD, answering 405 when
// not. HEAD is accepted because net/http serves it from the GET handler.
func requireGet(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET")
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return false
	}
	return true
}
