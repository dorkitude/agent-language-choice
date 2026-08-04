package main

import (
	"net/http"
	"sync"
)

// playDowntimeActivity is a DM-created recurring downtime activity that
// campaign members can allocate owned characters to.
type playDowntimeActivity struct {
	CampaignID     string
	ActivityID     string
	Name           string
	CyclesRequired int
}

// downtimeActivitiesMu guards downtimeActivities, the in-memory index
// mirroring the play_downtime_activities table. Keyed by campaign id,
// holding activities in creation order.
var (
	downtimeActivitiesMu sync.Mutex
	downtimeActivities   = map[string][]*playDowntimeActivity{}
)

// findDowntimeActivity returns the activity with the given id within
// campaignID, or nil. Callers must already hold downtimeActivitiesMu.
func findDowntimeActivity(campaignID, activityID string) *playDowntimeActivity {
	for _, act := range downtimeActivities[campaignID] {
		if act.ActivityID == activityID {
			return act
		}
	}
	return nil
}

// downtimeActivityJSON renders act as its exact API shape.
func downtimeActivityJSON(act *playDowntimeActivity) map[string]any {
	return map[string]any{
		"activity_id":     act.ActivityID,
		"name":            act.Name,
		"cycles_required": act.CyclesRequired,
	}
}

// playDowntimeAllocation tracks one character's recurring progress toward a
// downtime activity within a campaign.
type playDowntimeAllocation struct {
	CampaignID      string
	CharacterID     string
	ActivityID      string
	CyclesCompleted int
	Completions     int
}

// downtimeAllocationsMu guards downtimeAllocations, the in-memory index
// mirroring the play_downtime_allocations table. Keyed by campaign id, then
// character id, then activity id.
var (
	downtimeAllocationsMu sync.Mutex
	downtimeAllocations   = map[string]map[string]map[string]*playDowntimeAllocation{}
)

// findDowntimeAllocation returns the allocation for charID and activityID
// within campaignID, or nil. Callers must already hold
// downtimeAllocationsMu.
func findDowntimeAllocation(campaignID, charID, activityID string) *playDowntimeAllocation {
	if downtimeAllocations[campaignID] == nil {
		return nil
	}
	if downtimeAllocations[campaignID][charID] == nil {
		return nil
	}
	return downtimeAllocations[campaignID][charID][activityID]
}

// downtimeAllocationJSON renders a as its exact API shape.
func downtimeAllocationJSON(a *playDowntimeAllocation) map[string]any {
	return map[string]any{
		"character_id":     a.CharacterID,
		"activity_id":      a.ActivityID,
		"cycles_completed": a.CyclesCompleted,
		"completions":      a.Completions,
	}
}

type downtimeActivityRequest struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired int    `json:"cycles_required"`
}

// createDowntimeActivityHandler lets the campaign's owning dm define a new
// recurring downtime activity.
func createDowntimeActivityHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req downtimeActivityRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create downtime activities")
		return
	}

	if req.ActivityID == "" || req.Name == "" || req.CyclesRequired < 1 || req.CyclesRequired > 10 {
		writeError(w, http.StatusBadRequest, "activity_id and name are required nonempty strings, and cycles_required must be an integer from 1 through 10")
		return
	}

	downtimeActivitiesMu.Lock()
	defer downtimeActivitiesMu.Unlock()

	if findDowntimeActivity(campaignID, req.ActivityID) != nil {
		writeError(w, http.StatusConflict, "activity_id already exists in this campaign")
		return
	}

	act := &playDowntimeActivity{
		CampaignID:     campaignID,
		ActivityID:     req.ActivityID,
		Name:           req.Name,
		CyclesRequired: req.CyclesRequired,
	}
	if err := saveDowntimeActivityToDB(act); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save downtime activity")
		return
	}
	downtimeActivities[campaignID] = append(downtimeActivities[campaignID], act)

	writeJSON(w, http.StatusCreated, downtimeActivityJSON(act))
}

type downtimeAllocationRequest struct {
	ActivityID string `json:"activity_id"`
}

// allocateDowntimeHandler lets a character's owner allocate the character to
// a recurring downtime activity.
func allocateDowntimeHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req downtimeAllocationRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may allocate downtime")
		return
	}

	downtimeActivitiesMu.Lock()
	defer downtimeActivitiesMu.Unlock()

	if findDowntimeActivity(campaignID, req.ActivityID) == nil {
		writeError(w, http.StatusNotFound, "unknown activity id")
		return
	}

	downtimeAllocationsMu.Lock()
	defer downtimeAllocationsMu.Unlock()

	if findDowntimeAllocation(campaignID, charID, req.ActivityID) != nil {
		writeError(w, http.StatusConflict, "character is already allocated to this activity")
		return
	}

	a := &playDowntimeAllocation{
		CampaignID:      campaignID,
		CharacterID:     charID,
		ActivityID:      req.ActivityID,
		CyclesCompleted: 0,
		Completions:     0,
	}
	if err := saveDowntimeAllocationToDB(a); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save downtime allocation")
		return
	}
	if downtimeAllocations[campaignID] == nil {
		downtimeAllocations[campaignID] = map[string]map[string]*playDowntimeAllocation{}
	}
	if downtimeAllocations[campaignID][charID] == nil {
		downtimeAllocations[campaignID][charID] = map[string]*playDowntimeAllocation{}
	}
	downtimeAllocations[campaignID][charID][req.ActivityID] = a

	writeJSON(w, http.StatusCreated, downtimeAllocationJSON(a))
}

// progressDowntimeHandler lets a character's owner advance a recurring
// downtime allocation by one cycle, completing and resetting it when the
// activity's cycles_required is reached.
func progressDowntimeHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, activityID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may progress downtime")
		return
	}

	downtimeActivitiesMu.Lock()
	defer downtimeActivitiesMu.Unlock()

	act := findDowntimeActivity(campaignID, activityID)
	if act == nil {
		writeError(w, http.StatusNotFound, "unknown activity id")
		return
	}

	downtimeAllocationsMu.Lock()
	defer downtimeAllocationsMu.Unlock()

	a := findDowntimeAllocation(campaignID, charID, activityID)
	if a == nil {
		writeError(w, http.StatusNotFound, "unknown allocation")
		return
	}

	a.CyclesCompleted++
	if a.CyclesCompleted >= act.CyclesRequired {
		a.CyclesCompleted = 0
		a.Completions++
	}
	if err := saveDowntimeAllocationToDB(a); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save downtime allocation")
		return
	}

	writeJSON(w, http.StatusOK, downtimeAllocationJSON(a))
}

// getDowntimeAllocationHandler returns a character's downtime allocation for
// a given activity. Any authenticated campaign member may read it.
func getDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, activityID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	playMembersMu.Lock()
	_, exists := findMemberByCharacterID(campaignID, charID)
	playMembersMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	downtimeActivitiesMu.Lock()
	activityExists := findDowntimeActivity(campaignID, activityID) != nil
	downtimeActivitiesMu.Unlock()
	if !activityExists {
		writeError(w, http.StatusNotFound, "unknown activity id")
		return
	}

	downtimeAllocationsMu.Lock()
	defer downtimeAllocationsMu.Unlock()

	a := findDowntimeAllocation(campaignID, charID, activityID)
	if a == nil {
		writeError(w, http.StatusNotFound, "unknown allocation")
		return
	}

	writeJSON(w, http.StatusOK, downtimeAllocationJSON(a))
}
