package main

import "net/http"

// campaignAuditHandler reports deterministic counts of a campaign's tracked
// state for audit purposes.
func campaignAuditHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": c.ID,
		"events":      len(c.Events),
		"quests":      len(c.Quests),
		"npcs":        len(c.NPCs),
		"sessions":    len(c.Sessions),
	})
}

// campaignExportHandler returns a deterministic JSON summary of a campaign's
// full state, suitable for archival or migration.
func campaignExportHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":     c.ID,
		"name":            c.Name,
		"characters":      len(c.Characters),
		"quests":          len(c.Quests),
		"npcs":            len(c.NPCs),
		"inventory_items": len(c.Inventory),
		"sessions":        len(c.Sessions),
		"schema_version":  1,
	})
}
