package main

import "net/http"

// Audit and export views over stored campaign state.
//
// Both endpoints are read-only aggregations: they count what is already in the
// campaign rather than recording anything, so they add no fields to the store
// and never call flush(). Counts come straight from the in-memory slices, whose
// insertion order and contents are the same after a restart, which is what
// makes the answers deterministic.

// exportSchemaVersion identifies the shape of the export document. It is the
// export's own contract version and is deliberately independent of the SQLite
// schemaVersion in store.go: the persisted layout can change without changing
// what an export looks like to a client.
const exportSchemaVersion = 1

type campaignAuditResponse struct {
	CampaignID string `json:"campaign_id"`
	Events     int    `json:"events"`
	Quests     int    `json:"quests"`
	NPCs       int    `json:"npcs"`
	Sessions   int    `json:"sessions"`
}

type campaignExportResponse struct {
	CampaignID     string `json:"campaign_id"`
	Name           string `json:"name"`
	Characters     int    `json:"characters"`
	Quests         int    `json:"quests"`
	NPCs           int    `json:"npcs"`
	InventoryItems int    `json:"inventory_items"`
	Sessions       int    `json:"sessions"`
	SchemaVersion  int    `json:"schema_version"`
}

// ---------- GET /v1/campaigns/{id}/audit ----------

func handleCampaignAudit(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, campaignAuditResponse{
		CampaignID: c.ID,
		Events:     len(c.Events),
		Quests:     len(c.Quests),
		NPCs:       len(c.NPCs),
		Sessions:   len(c.Sessions),
	})
}

// ---------- GET /v1/campaigns/{id}/export ----------

func handleCampaignExport(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, campaignExportResponse{
		CampaignID:     c.ID,
		Name:           c.Name,
		Characters:     len(c.Characters),
		Quests:         len(c.Quests),
		NPCs:           len(c.NPCs),
		InventoryItems: len(c.Inventory),
		Sessions:       len(c.Sessions),
		SchemaVersion:  exportSchemaVersion,
	})
}
