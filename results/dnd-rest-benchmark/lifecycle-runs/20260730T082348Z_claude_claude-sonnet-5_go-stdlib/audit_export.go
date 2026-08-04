package main

import "net/http"

func handleCampaignAudit(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	resp := map[string]interface{}{
		"campaign_id": c.ID,
		"events":      len(c.Events),
		"quests":      len(c.Quests),
		"npcs":        len(c.NPCs),
		"sessions":    len(c.Sessions),
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignExport(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	resp := map[string]interface{}{
		"campaign_id":     c.ID,
		"name":            c.Name,
		"characters":      len(c.Characters),
		"quests":          len(c.Quests),
		"npcs":            len(c.NPCs),
		"inventory_items": len(c.Inventory),
		"sessions":        len(c.Sessions),
		"schema_version":  1,
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignAuditExportSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "audit" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCampaignAudit(w, r, campaignID)
		return true
	}
	if rest == "export" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCampaignExport(w, r, campaignID)
		return true
	}
	return false
}
