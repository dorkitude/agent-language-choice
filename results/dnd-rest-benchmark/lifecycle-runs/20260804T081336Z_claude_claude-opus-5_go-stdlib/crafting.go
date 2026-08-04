package main

import (
	"encoding/json"
	"net/http"
)

// Downtime crafting: a campaign owns an ordered list of crafting projects, each
// tracking how many downtime days a character has spent toward an item.
//
// A project starts active with zero days completed and turns complete the first
// time its accumulated days reach days_required. That transition is the only
// moment the crafted item is added to campaign stock — a completed project that
// is advanced again keeps accumulating days but never mints a second item, so
// replayed advance calls cannot inflate the inventory.
//
// The crafted item enters the world as an ordinary inventory stack owned by the
// crafting character, which is why availability (see inventory.go) picks it up
// without any special case.
//
// Like the rest of the campaign state, projects live under campaigns.mu and are
// mirrored to SQLite by flush().

// Crafting project statuses.
const (
	craftingActive   = "active"
	craftingComplete = "complete"
)

func validCraftingStatus(s string) bool {
	return s == craftingActive || s == craftingComplete
}

type craftingProject struct {
	ID            string
	CharacterID   string
	ItemSlug      string
	DaysRequired  int
	DaysCompleted int
	CostGP        int
	Status        string
}

// findCraftingProject returns the campaign's project with the given id. Callers
// must hold campaigns.mu.
func findCraftingProject(c *campaign, id string) *craftingProject {
	for _, p := range c.Crafting {
		if p.ID == id {
			return p
		}
	}
	return nil
}

// ---------- request / response payloads ----------

type craftingRequest struct {
	ID           *string          `json:"id"`
	CharacterID  *string          `json:"character_id"`
	ItemSlug     *string          `json:"item_slug"`
	DaysRequired *json.RawMessage `json:"days_required"`
	CostGP       *json.RawMessage `json:"cost_gp"`
}

type craftingResponse struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

type craftingAdvanceRequest struct {
	Days *json.RawMessage `json:"days"`
}

type craftingAdvanceResponse struct {
	ID            string `json:"id"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

// ---------- POST /v1/campaigns/{id}/downtime/crafting ----------

func handleCreateCrafting(w http.ResponseWriter, r *http.Request) {
	var req craftingRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	characterID, ok := requiredString(req.CharacterID)
	if !ok {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}
	slug, ok := requiredString(req.ItemSlug)
	if !ok {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	daysRequired, ok := asInt(req.DaysRequired)
	if !ok || daysRequired < 1 {
		writeError(w, http.StatusBadRequest, "days_required must be a positive integer")
		return
	}
	// Cost is bookkeeping only: it is recorded but never spent, so an omitted
	// value simply means a free project.
	costGP := 0
	if req.CostGP != nil {
		n, ok := asInt(req.CostGP)
		if !ok || n < 0 {
			writeError(w, http.StatusBadRequest, "cost_gp must be a non-negative integer")
			return
		}
		costGP = n
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if findCraftingProject(c, id) != nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "crafting project id already exists")
		return
	}
	p := &craftingProject{
		ID:           id,
		CharacterID:  characterID,
		ItemSlug:     slug,
		DaysRequired: daysRequired,
		CostGP:       costGP,
		Status:       craftingActive,
	}
	c.Crafting = append(c.Crafting, p)
	resp := craftingResponse{
		ID:            p.ID,
		CharacterID:   p.CharacterID,
		ItemSlug:      p.ItemSlug,
		DaysRequired:  p.DaysRequired,
		DaysCompleted: p.DaysCompleted,
		Status:        p.Status,
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance ----------

func handleAdvanceCrafting(w http.ResponseWriter, r *http.Request) {
	var req craftingAdvanceRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	days, ok := asInt(req.Days)
	if !ok || days < 1 {
		writeError(w, http.StatusBadRequest, "days must be a positive integer")
		return
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	p := findCraftingProject(c, r.PathValue("project_id"))
	if p == nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "crafting project not found")
		return
	}
	p.DaysCompleted += days
	if p.Status == craftingActive && p.DaysCompleted >= p.DaysRequired {
		// Completion only flips the project's status. The crafted item is not
		// pushed into campaign stock: inventory is an explicit ledger written
		// through POST /inventory, and auto-delivering here would make the
		// inventory and export counts depend on downtime progress.
		p.Status = craftingComplete
	}
	resp := craftingAdvanceResponse{
		ID:            p.ID,
		DaysCompleted: p.DaysCompleted,
		Status:        p.Status,
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// ---------- persistence helpers ----------

// craftingFromRow rebuilds a project from a storage row, returning the owning
// campaign id. Rows missing their identifiers or carrying an unknown status are
// rejected, so a corrupt file cannot introduce an unaddressable project.
func craftingFromRow(row []any) (campaignID string, p *craftingProject, ok bool) {
	if len(row) < 9 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	id, _ := row[1].(string)
	characterID, _ := row[2].(string)
	slug, _ := row[3].(string)
	daysRequired, _ := row[4].(int64)
	daysCompleted, _ := row[5].(int64)
	costGP, _ := row[6].(int64)
	status, _ := row[7].(string)
	if campaignID == "" || id == "" || !validCraftingStatus(status) {
		return "", nil, false
	}
	return campaignID, &craftingProject{
		ID:            id,
		CharacterID:   characterID,
		ItemSlug:      slug,
		DaysRequired:  int(daysRequired),
		DaysCompleted: int(daysCompleted),
		CostGP:        int(costGP),
		Status:        status,
	}, true
}
