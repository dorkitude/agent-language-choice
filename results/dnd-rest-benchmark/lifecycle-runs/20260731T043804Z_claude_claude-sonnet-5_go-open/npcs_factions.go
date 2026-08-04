package main

import (
	"net/http"
)

type campaignFaction struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

type campaignNPC struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

type createFactionRequest struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

func createFactionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createFactionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Stance == "" {
		writeError(w, http.StatusBadRequest, "stance is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	for _, f := range c.Factions {
		if f.ID == req.ID {
			writeError(w, http.StatusConflict, "faction id already exists")
			return
		}
	}

	f := &campaignFaction{ID: req.ID, Name: req.Name, Stance: req.Stance}
	if err := saveCampaignFactionToDB(c.ID, f); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save faction")
		return
	}
	c.Factions = append(c.Factions, f)

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":     f.ID,
		"name":   f.Name,
		"stance": f.Stance,
	})
}

type createNPCRequest struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition *int   `json:"disposition"`
}

func createNPCHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createNPCRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Disposition == nil {
		writeError(w, http.StatusBadRequest, "disposition is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
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
			writeError(w, http.StatusBadRequest, "unknown faction id")
			return
		}
	}

	for _, n := range c.NPCs {
		if n.ID == req.ID {
			writeError(w, http.StatusConflict, "npc id already exists")
			return
		}
	}

	n := &campaignNPC{ID: req.ID, Name: req.Name, FactionID: req.FactionID, Disposition: *req.Disposition}
	if err := saveCampaignNPCToDB(c.ID, n); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save npc")
		return
	}
	c.NPCs = append(c.NPCs, n)

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":          n.ID,
		"name":        n.Name,
		"faction_id":  n.FactionID,
		"disposition": n.Disposition,
	})
}

func relationshipSummaryHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	friendlyNPCs := 0
	for _, n := range c.NPCs {
		if n.Disposition > 0 {
			friendlyNPCs++
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":   c.ID,
		"factions":      len(c.Factions),
		"npcs":          len(c.NPCs),
		"friendly_npcs": friendlyNPCs,
	})
}
