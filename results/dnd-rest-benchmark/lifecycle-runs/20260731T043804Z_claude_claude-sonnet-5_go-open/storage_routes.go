package main

import "net/http"

// storageStatusHandler and storageResetHandler are the HTTP surface over the
// persistence layer implemented in storage.go.

func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"driver":         "sqlite",
		"schema_version": schemaVersion,
		"initialized":    initialized,
	})
}

func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	if err := resetStorage(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to reset storage")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":             true,
		"schema_version": schemaVersion,
	})
}
