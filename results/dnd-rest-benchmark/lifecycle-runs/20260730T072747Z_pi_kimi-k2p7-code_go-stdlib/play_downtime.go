package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// downtimeActivity is the response shape for a recurring downtime activity.
type downtimeActivity struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired int    `json:"cycles_required"`
}

// downtimeActivityRequest binds the payload for creating an activity.
type downtimeActivityRequest struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired int    `json:"cycles_required"`
}

// downtimeAllocation is the response shape for a downtime allocation.
type downtimeAllocation struct {
	CharacterID     string `json:"character_id"`
	ActivityID      string `json:"activity_id"`
	CyclesCompleted int    `json:"cycles_completed"`
	Completions     int    `json:"completions"`
}

// downtimeAllocationRequest binds the payload for creating an allocation.
type downtimeAllocationRequest struct {
	ActivityID string `json:"activity_id"`
}

// queryDowntimeActivity loads a single downtime activity by campaign and id.
// The caller must hold dbMu.
func queryDowntimeActivity(campaignID, activityID string) (*downtimeActivity, bool, error) {
	var rows []downtimeActivity
	if err := queryRows(fmt.Sprintf("SELECT activity_id, name, cycles_required FROM downtime_activities WHERE campaign_id=%s AND activity_id=%s LIMIT 1;", sq(campaignID), sq(activityID)), &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// downtimeActivityExists reports whether an activity exists in a campaign.
// The caller must hold dbMu.
func downtimeActivityExists(campaignID, activityID string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM downtime_activities WHERE campaign_id=%s AND activity_id=%s LIMIT 1;", sq(campaignID), sq(activityID)))
}

// downtimeAllocationExists reports whether an allocation exists.
// The caller must hold dbMu.
func downtimeAllocationExists(campaignID, characterID, activityID string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM downtime_allocations WHERE campaign_id=%s AND character_id=%s AND activity_id=%s LIMIT 1;", sq(campaignID), sq(characterID), sq(activityID)))
}

// queryDowntimeAllocation loads a single allocation by campaign, character,
// and activity. The caller must hold dbMu.
func queryDowntimeAllocation(campaignID, characterID, activityID string) (*downtimeAllocation, bool, error) {
	var rows []downtimeAllocation
	if err := queryRows(fmt.Sprintf("SELECT character_id, activity_id, cycles_completed, completions FROM downtime_allocations WHERE campaign_id=%s AND character_id=%s AND activity_id=%s LIMIT 1;", sq(campaignID), sq(characterID), sq(activityID)), &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// createDowntimeActivityHandler creates a recurring downtime activity for a
// campaign. Only the campaign owner (DM) may create activities.
func createDowntimeActivityHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	if _, ok := requireCampaignOwner(w, r, r.PathValue("id")); !ok {
		return
	}
	campaignID := r.PathValue("id")

	var req downtimeActivityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ActivityID == "" || req.Name == "" || req.CyclesRequired < 1 || req.CyclesRequired > 10 {
		writeError(w, http.StatusBadRequest, "invalid activity")
		return
	}

	exists, err := downtimeActivityExists(campaignID, req.ActivityID)
	if err != nil {
		log.Printf("downtime activity exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "activity already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (%s, %s, %s, %d);",
		sq(campaignID), sq(req.ActivityID), sq(req.Name), req.CyclesRequired)); err != nil {
		log.Printf("downtime activity insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, downtimeActivity{
		ActivityID:     req.ActivityID,
		Name:           req.Name,
		CyclesRequired: req.CyclesRequired,
	})
}

// createDowntimeAllocationHandler allocates an activity to a character. Only
// the character's owner may allocate downtime.
func createDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}
	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("downtime allocation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var req downtimeAllocationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ActivityID == "" {
		writeError(w, http.StatusBadRequest, "invalid activity")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("downtime allocation member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	activityExists, err := downtimeActivityExists(campaignID, req.ActivityID)
	if err != nil {
		log.Printf("downtime allocation activity exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !activityExists {
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}

	allocationExists, err := downtimeAllocationExists(campaignID, characterID, req.ActivityID)
	if err != nil {
		log.Printf("downtime allocation exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if allocationExists {
		writeError(w, http.StatusConflict, "allocation already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (%s, %s, %s, 0, 0);",
		sq(campaignID), sq(characterID), sq(req.ActivityID))); err != nil {
		log.Printf("downtime allocation insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, downtimeAllocation{
		CharacterID:     characterID,
		ActivityID:      req.ActivityID,
		CyclesCompleted: 0,
		Completions:     0,
	})
}

// progressDowntimeAllocationHandler advances a character's downtime allocation.
// Only the character's owner may progress. When cycles_completed reaches the
// activity's cycles_required, it resets to 0 and completions is incremented.
func progressDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}
	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	activityID := r.PathValue("activity_id")

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("downtime progress campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("downtime progress member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	activity, ok, err := queryDowntimeActivity(campaignID, activityID)
	if err != nil {
		log.Printf("downtime progress activity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}

	allocation, ok, err := queryDowntimeAllocation(campaignID, characterID, activityID)
	if err != nil {
		log.Printf("downtime progress allocation query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "allocation not found")
		return
	}

	cyclesCompleted := allocation.CyclesCompleted + 1
	completions := allocation.Completions
	if cyclesCompleted == activity.CyclesRequired {
		cyclesCompleted = 0
		completions++
	}

	if err := dbExec(fmt.Sprintf("UPDATE downtime_allocations SET cycles_completed=%d, completions=%d WHERE campaign_id=%s AND character_id=%s AND activity_id=%s;",
		cyclesCompleted, completions, sq(campaignID), sq(characterID), sq(activityID))); err != nil {
		log.Printf("downtime progress update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, downtimeAllocation{
		CharacterID:     characterID,
		ActivityID:      activityID,
		CyclesCompleted: cyclesCompleted,
		Completions:     completions,
	})
}

// getDowntimeAllocationHandler returns an allocation. Any campaign owner or
// member may read it.
func getDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	activityID := r.PathValue("activity_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("downtime get allocation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if _, ok, err := queryPlayCampaignMember(campaignID, characterID); err != nil {
		log.Printf("downtime get allocation member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	if _, ok, err := queryDowntimeActivity(campaignID, activityID); err != nil {
		log.Printf("downtime get allocation activity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "activity not found")
		return
	}

	allocation, ok, err := queryDowntimeAllocation(campaignID, characterID, activityID)
	if err != nil {
		log.Printf("downtime get allocation query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "allocation not found")
		return
	}

	writeJSON(w, http.StatusOK, *allocation)
}
