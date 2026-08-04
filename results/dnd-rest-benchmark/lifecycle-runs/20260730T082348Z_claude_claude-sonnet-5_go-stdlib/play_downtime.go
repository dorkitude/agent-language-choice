package main

import (
	"encoding/json"
	"net/http"
)

// playDowntimeActivity is a DM-managed recurring downtime activity that
// campaign members may allocate owned characters to.
type playDowntimeActivity struct {
	ActivityID     string
	Name           string
	CyclesRequired int
}

func playDowntimeActivityResponse(a *playDowntimeActivity) map[string]interface{} {
	return map[string]interface{}{
		"activity_id":     a.ActivityID,
		"name":            a.Name,
		"cycles_required": a.CyclesRequired,
	}
}

// playDowntimeAllocation tracks one character's recurring progress toward a
// single downtime activity.
type playDowntimeAllocation struct {
	CharacterID     string
	ActivityID      string
	CyclesCompleted int
	Completions     int
}

func playDowntimeAllocationResponse(a *playDowntimeAllocation) map[string]interface{} {
	return map[string]interface{}{
		"character_id":     a.CharacterID,
		"activity_id":      a.ActivityID,
		"cycles_completed": a.CyclesCompleted,
		"completions":      a.Completions,
	}
}

func downtimeAllocationKey(characterID, activityID string) string {
	return characterID + "/" + activityID
}

// handlePlayCampaignDowntimeSub routes the "downtime/activities" sub-path of
// a play campaign. It returns false if rest does not name a recognized
// downtime path, so the caller can fall through to its own routing.
func handlePlayCampaignDowntimeSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest != "downtime/activities" {
		return false
	}
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleCreatePlayDowntimeActivity(w, r, campaignID)
	return true
}

type playDowntimeActivityRequest struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired *int   `json:"cycles_required"`
}

// handleCreatePlayDowntimeActivity lets the campaign dm create a new
// recurring downtime activity. Only the dm may call this; unknown campaigns
// return 404, invalid payloads return 400, and duplicate activity ids within
// the campaign return 409.
func handleCreatePlayDowntimeActivity(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playDowntimeActivityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ActivityID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "activity_id and name are required")
		return
	}
	if req.CyclesRequired == nil || *req.CyclesRequired < 1 || *req.CyclesRequired > 10 {
		writeError(w, http.StatusBadRequest, "cycles_required must be an integer from 1 through 10")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create downtime activities")
		return
	}
	if c.DowntimeActivities == nil {
		c.DowntimeActivities = make(map[string]*playDowntimeActivity)
	}
	if _, exists := c.DowntimeActivities[req.ActivityID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "activity_id already exists")
		return
	}

	act := &playDowntimeActivity{
		ActivityID:     req.ActivityID,
		Name:           req.Name,
		CyclesRequired: *req.CyclesRequired,
	}
	c.DowntimeActivities[req.ActivityID] = act
	resp := playDowntimeActivityResponse(act)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

type playDowntimeAllocationRequest struct {
	ActivityID string `json:"activity_id"`
}

// handleCreatePlayDowntimeAllocation lets the player who owns characterID
// allocate downtime to a recurring activity. Only that player may allocate;
// the dm and non-owners receive 403. Unknown characters or activities return
// 404. Duplicate allocations for the same character and activity return 409.
func handleCreatePlayDowntimeAllocation(w http.ResponseWriter, r *http.Request, campaignID, characterID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playDowntimeAllocationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ActivityID == "" {
		writeError(w, http.StatusBadRequest, "activity_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, characterID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if c.Owner == username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "the dm may not allocate downtime")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may allocate downtime")
		return
	}
	act := c.DowntimeActivities[req.ActivityID]
	if act == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}
	if c.DowntimeAllocations == nil {
		c.DowntimeAllocations = make(map[string]*playDowntimeAllocation)
	}
	key := downtimeAllocationKey(characterID, req.ActivityID)
	if _, exists := c.DowntimeAllocations[key]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "allocation already exists")
		return
	}

	alloc := &playDowntimeAllocation{
		CharacterID: characterID,
		ActivityID:  req.ActivityID,
	}
	c.DowntimeAllocations[key] = alloc
	resp := playDowntimeAllocationResponse(alloc)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handlePlayDowntimeAllocationProgress lets the player who owns characterID
// progress an existing downtime allocation by one cycle, recurring the
// activity's completion whenever cycles_required is reached.
func handlePlayDowntimeAllocationProgress(w http.ResponseWriter, r *http.Request, campaignID, characterID, activityID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, characterID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if c.Owner == username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "the dm may not progress downtime")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may progress downtime")
		return
	}
	act := c.DowntimeActivities[activityID]
	if act == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}
	alloc := c.DowntimeAllocations[downtimeAllocationKey(characterID, activityID)]
	if alloc == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "allocation not found")
		return
	}

	alloc.CyclesCompleted++
	if alloc.CyclesCompleted >= act.CyclesRequired {
		alloc.CyclesCompleted = 0
		alloc.Completions++
	}
	resp := playDowntimeAllocationResponse(alloc)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleGetPlayDowntimeAllocation returns a single downtime allocation.
// Authenticated campaign members may read any allocation. Unknown
// characters, activities, or allocations return 404.
func handleGetPlayDowntimeAllocation(w http.ResponseWriter, r *http.Request, campaignID, characterID, activityID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view downtime allocations")
		return
	}
	member := findPlayMemberByCharacterID(c, characterID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if c.DowntimeActivities[activityID] == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}
	alloc := c.DowntimeAllocations[downtimeAllocationKey(characterID, activityID)]
	if alloc == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "allocation not found")
		return
	}
	resp := playDowntimeAllocationResponse(alloc)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
