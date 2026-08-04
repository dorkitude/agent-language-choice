package main

import (
	"encoding/json"
	"net/http"
)

// writeJSON encodes v as the JSON response body and sets the status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// writeError writes a standard {"error": msg} JSON body.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// requireMethod writes a 405 and returns false if r.Method doesn't match
// method. Handlers that only support one HTTP method call this first and
// return immediately when it reports false.
func requireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method != method {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return false
	}
	return true
}

// decodeJSONBody decodes r.Body into dst, writing a 400 with a standard
// message and returning false on failure. dst must be a pointer.
func decodeJSONBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

// extractSessionID pulls the path segment between a fixed prefix and suffix,
// e.g. extractSessionID("/v1/combat/sessions/abc/advance", "/v1/combat/sessions/", "/advance") -> "abc".
// An empty suffix matches everything after prefix. Returns ok=false if the
// path doesn't have the expected prefix/suffix or the resulting id would be empty.
func extractSessionID(path, prefix, suffix string) (string, bool) {
	if len(path) <= len(prefix)+len(suffix) {
		return "", false
	}
	if path[:len(prefix)] != prefix {
		return "", false
	}
	if suffix != "" {
		if len(path) < len(suffix) || path[len(path)-len(suffix):] != suffix {
			return "", false
		}
		return path[len(prefix) : len(path)-len(suffix)], true
	}
	return path[len(prefix):], true
}
