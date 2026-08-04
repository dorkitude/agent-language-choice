package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// Campaign cast: factions and the NPCs that belong to them.
//
// A faction is a named group with a stance toward the party; an NPC optionally
// names the faction it belongs to and carries a numeric disposition. An NPC is
// counted as friendly when its own disposition is positive — disposition is the
// per-NPC attitude, while a faction's stance describes the group.
//
// Both collections live on the campaign under campaigns.mu and are mirrored to
// SQLite by flush(), like rosters, events, and quests.

// Accepted faction stances. The first three are the canonical set; the last two
// are common synonyms the API accepts rather than rejecting outright.
var factionStances = []string{"friendly", "neutral", "hostile", "allied", "unfriendly"}

func validFactionStance(s string) bool {
	for _, known := range factionStances {
		if s == known {
			return true
		}
	}
	return false
}

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

// friendly reports whether the NPC counts toward the relationship summary's
// friendly tally.
func (n *npc) friendly() bool { return n.Disposition > 0 }

// findFaction / findNPC return a campaign's member by id. Callers must hold
// campaigns.mu.

func findFaction(c *campaign, id string) *faction {
	for _, f := range c.Factions {
		if f.ID == id {
			return f
		}
	}
	return nil
}

func findNPC(c *campaign, id string) *npc {
	for _, n := range c.NPCs {
		if n.ID == id {
			return n
		}
	}
	return nil
}

// ---------- request / response payloads ----------

type factionRequest struct {
	ID     *string `json:"id"`
	Name   *string `json:"name"`
	Stance *string `json:"stance"`
}

type npcRequest struct {
	ID          *string          `json:"id"`
	Name        *string          `json:"name"`
	FactionID   *string          `json:"faction_id"`
	Disposition *json.RawMessage `json:"disposition"`
}

type relationshipsResponse struct {
	CampaignID   string `json:"campaign_id"`
	Factions     int    `json:"factions"`
	NPCs         int    `json:"npcs"`
	FriendlyNPCs int    `json:"friendly_npcs"`
}

// ---------- POST /v1/campaigns/{id}/factions ----------

func handleCreateFaction(w http.ResponseWriter, r *http.Request) {
	var req factionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	stance, ok := requiredString(req.Stance)
	if !ok {
		writeError(w, http.StatusBadRequest, "stance is required")
		return
	}
	stance = strings.ToLower(stance)
	if !validFactionStance(stance) {
		writeError(w, http.StatusBadRequest, "stance must be friendly, neutral, or hostile")
		return
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if findFaction(c, id) != nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "faction id already exists")
		return
	}
	f := &faction{ID: id, Name: name, Stance: stance}
	c.Factions = append(c.Factions, f)
	resp := *f
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/campaigns/{id}/npcs ----------

func handleCreateNPC(w http.ResponseWriter, r *http.Request) {
	var req npcRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	// An NPC need not belong to a faction, but a named faction must exist.
	factionID := ""
	if req.FactionID != nil {
		s, ok := requiredString(req.FactionID)
		if !ok {
			writeError(w, http.StatusBadRequest, "faction_id must not be blank")
			return
		}
		factionID = s
	}
	// Disposition defaults to indifferent when omitted, but a present value must
	// be a real integer.
	disposition := 0
	if req.Disposition != nil {
		v, ok := asInt(req.Disposition)
		if !ok {
			writeError(w, http.StatusBadRequest, "disposition must be an integer")
			return
		}
		disposition = v
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if factionID != "" && findFaction(c, factionID) == nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}
	if findNPC(c, id) != nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "npc id already exists")
		return
	}
	n := &npc{ID: id, Name: name, FactionID: factionID, Disposition: disposition}
	c.NPCs = append(c.NPCs, n)
	resp := *n
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- GET /v1/campaigns/{id}/relationships ----------

func handleRelationships(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	resp := relationshipsResponse{
		CampaignID: c.ID,
		Factions:   len(c.Factions),
		NPCs:       len(c.NPCs),
	}
	for _, n := range c.NPCs {
		if n.friendly() {
			resp.FriendlyNPCs++
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

// ---------- persistence helpers ----------

// factionFromRow / npcFromRow rebuild a member from a storage row, returning the
// owning campaign id. Rows missing their identifying columns are rejected so a
// corrupt file cannot introduce anonymous members.

func factionFromRow(row []any) (campaignID string, f *faction, ok bool) {
	if len(row) < 4 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	id, _ := row[1].(string)
	name, _ := row[2].(string)
	stance, _ := row[3].(string)
	if campaignID == "" || id == "" || !validFactionStance(stance) {
		return "", nil, false
	}
	return campaignID, &faction{ID: id, Name: name, Stance: stance}, true
}

func npcFromRow(row []any) (campaignID string, n *npc, ok bool) {
	if len(row) < 5 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	id, _ := row[1].(string)
	name, _ := row[2].(string)
	factionID, _ := row[3].(string)
	disposition, _ := row[4].(int64)
	if campaignID == "" || id == "" {
		return "", nil, false
	}
	return campaignID, &npc{
		ID:          id,
		Name:        name,
		FactionID:   factionID,
		Disposition: int(disposition),
	}, true
}
