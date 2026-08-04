package main

import (
	"encoding/json"
	"net/http"
)

type faction struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

type npc struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

func factionResponse(f *faction) map[string]interface{} {
	return map[string]interface{}{
		"id":     f.ID,
		"name":   f.Name,
		"stance": f.Stance,
	}
}

func npcResponse(n *npc) map[string]interface{} {
	return map[string]interface{}{
		"id":          n.ID,
		"name":        n.Name,
		"faction_id":  n.FactionID,
		"disposition": n.Disposition,
	}
}

func handleCreateFaction(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID     string `json:"id"`
		Name   string `json:"name"`
		Stance string `json:"stance"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Stance == "" {
		writeError(w, http.StatusBadRequest, "id, name, and stance are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, f := range c.Factions {
		if f.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "faction id already exists")
			return
		}
	}
	f := &faction{ID: req.ID, Name: req.Name, Stance: req.Stance}
	c.Factions = append(c.Factions, f)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, factionResponse(f))
}

func handleCreateNPC(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID          string `json:"id"`
		Name        string `json:"name"`
		FactionID   string `json:"faction_id"`
		Disposition *int   `json:"disposition"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Disposition == nil {
		writeError(w, http.StatusBadRequest, "id, name, and disposition are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, n := range c.NPCs {
		if n.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "npc id already exists")
			return
		}
	}
	if req.FactionID != "" {
		found := false
		for _, f := range c.Factions {
			if f.ID == req.FactionID {
				found = true
				break
			}
		}
		if !found {
			campaignMu.Unlock()
			writeError(w, http.StatusBadRequest, "faction_id must name a faction in the campaign")
			return
		}
	}
	n := &npc{ID: req.ID, Name: req.Name, FactionID: req.FactionID, Disposition: *req.Disposition}
	c.NPCs = append(c.NPCs, n)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, npcResponse(n))
}

func handleRelationshipSummary(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	friendly := 0
	for _, n := range c.NPCs {
		if n.Disposition > 0 {
			friendly++
		}
	}
	resp := map[string]interface{}{
		"campaign_id":   c.ID,
		"factions":      len(c.Factions),
		"npcs":          len(c.NPCs),
		"friendly_npcs": friendly,
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignNPCFactionSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "factions":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreateFaction(w, r, campaignID)
		return true
	case "npcs":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreateNPC(w, r, campaignID)
		return true
	case "relationships":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleRelationshipSummary(w, r, campaignID)
		return true
	}
	return false
}
