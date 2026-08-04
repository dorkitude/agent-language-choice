package main

import (
	"database/sql"
	"errors"
	"net/http"
)

// Read-only rollups over an existing campaign. Neither endpoint writes, and
// neither invents a number: every field is a COUNT over a table another module
// already owns, so an export taken twice without an intervening write is
// byte-for-byte identical.
//
// Counts follow the same "count rows, not units" rule the inventory summary
// uses: a stack of three potions is one inventory item.

// countCampaignRows counts the rows one campaign owns in table. table is a
// literal from this file only, never request data. Callers must hold storeMu.
func countCampaignRows(table, campaignID string) (int, error) {
	var n int
	err := db.QueryRow(
		`SELECT COUNT(*) FROM `+table+` WHERE campaign_id = ?`, campaignID,
	).Scan(&n)
	return n, err
}

// ---------- GET /v1/campaigns/{id}/audit ----------

type campaignAuditResponse struct {
	CampaignID string `json:"campaign_id"`
	Events     int    `json:"events"`
	Quests     int    `json:"quests"`
	NPCs       int    `json:"npcs"`
	Sessions   int    `json:"sessions"`
}

func handleCampaignAudit(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	out := campaignAuditResponse{CampaignID: campaignID}
	for _, part := range []struct {
		table string
		into  *int
	}{
		{`campaign_events`, &out.Events},
		{`campaign_quests`, &out.Quests},
		{`campaign_npcs`, &out.NPCs},
		{`campaign_sessions`, &out.Sessions},
	} {
		n, err := countCampaignRows(part.table, campaignID)
		if err != nil {
			writeStorageFailure(w, "audit count failed", err)
			return
		}
		*part.into = n
	}
	writeJSON(w, http.StatusOK, out)
}

// ---------- GET /v1/campaigns/{id}/export ----------

// campaignExportResponse carries schema_version so a consumer can tell which
// shape it holds; it is the same stamp storage reports.
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

func handleCampaignExport(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	// The name lookup doubles as the existence check, so this handler resolves
	// the campaign itself instead of calling requireCampaign first.
	out := campaignExportResponse{CampaignID: campaignID, SchemaVersion: schemaVersion}
	if err := db.QueryRow(`SELECT name FROM campaigns WHERE id = ?`, campaignID).Scan(&out.Name); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeError(w, http.StatusNotFound, "campaign not found")
			return
		}
		writeStorageFailure(w, "campaign read failed", err)
		return
	}
	for _, part := range []struct {
		table string
		into  *int
	}{
		{`campaign_characters`, &out.Characters},
		{`campaign_quests`, &out.Quests},
		{`campaign_npcs`, &out.NPCs},
		{`campaign_inventory`, &out.InventoryItems},
		{`campaign_sessions`, &out.Sessions},
	} {
		n, err := countCampaignRows(part.table, campaignID)
		if err != nil {
			writeStorageFailure(w, "export count failed", err)
			return
		}
		*part.into = n
	}
	writeJSON(w, http.StatusOK, out)
}
