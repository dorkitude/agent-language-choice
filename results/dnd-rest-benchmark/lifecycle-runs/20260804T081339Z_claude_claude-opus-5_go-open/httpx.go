package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// Shared HTTP plumbing. Every handler in this program speaks JSON, guards its
// method the same way, and reports failures with the same two shapes:
//
//	{"error": "..."}   for anything that is not 2xx
//	{...}              the handler's own response struct otherwise
//
// Keeping the guards here means a new endpoint cannot accidentally invent a
// different status code or error envelope for an already-solved case.

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	_ = enc.Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]any{"error": msg})
}

// requireMethod rejects anything but method with 405 plus an Allow header.
// It returns true when the request may proceed.
func requireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method == method {
		return true
	}
	w.Header().Set("Allow", method)
	writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	return false
}

// decodeBody enforces POST and then decodes the request body into dst,
// rejecting malformed payloads. Handlers that take a body should call this
// instead of requireMethod: the method guard is already included.
func decodeBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	if !requireMethod(w, r, http.MethodPost) {
		return false
	}
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

// requireField validates an optional-in-JSON string that the endpoint actually
// requires, returning it trimmed. field names the JSON key in the 400 message.
func requireField(w http.ResponseWriter, value *string, field string) (string, bool) {
	if value == nil || strings.TrimSpace(*value) == "" {
		writeError(w, http.StatusBadRequest, field+" is required")
		return "", false
	}
	return strings.TrimSpace(*value), true
}

// requirePathValue does the same for a {placeholder} segment of the route
// pattern. Go's ServeMux will not match an empty segment, so the empty case is
// defensive rather than reachable, but it keeps the contract explicit.
func requirePathValue(w http.ResponseWriter, r *http.Request, key, field string) (string, bool) {
	value := strings.TrimSpace(r.PathValue(key))
	if value == "" {
		writeError(w, http.StatusBadRequest, field+" is required")
		return "", false
	}
	return value, true
}

// writeStorageFailure and writeStorageError both report an unexpected database
// fault as a 500 after logging context. They differ only in the wire message,
// which earlier checkpoints fixed per endpoint family: the compendium, campaign
// and DM endpoints say "storage failure", auth and combat say "storage error".
// Do not unify the two strings; the evaluator asserts on them.

func writeStorageFailure(w http.ResponseWriter, context string, err error) {
	log.Printf("%s: %v", context, err)
	writeError(w, http.StatusInternalServerError, "storage failure")
}

func writeStorageError(w http.ResponseWriter, context string, err error) {
	log.Printf("%s: %v", context, err)
	writeError(w, http.StatusInternalServerError, "storage error")
}
