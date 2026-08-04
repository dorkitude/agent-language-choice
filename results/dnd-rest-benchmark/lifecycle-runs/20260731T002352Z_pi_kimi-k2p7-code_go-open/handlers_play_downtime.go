package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayDowntimeActivityHandler lets a campaign DM create a recurring downtime activity.
func createPlayDowntimeActivityHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create downtime activities")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create downtime activities")
		return
	}

	var req downtimeActivityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	req.ActivityID = strings.TrimSpace(req.ActivityID)
	req.Name = strings.TrimSpace(req.Name)
	if req.ActivityID == "" {
		badRequest(w, "activity_id is required")
		return
	}
	if req.Name == "" {
		badRequest(w, "name is required")
		return
	}
	if req.CyclesRequired < 1 || req.CyclesRequired > 10 {
		badRequest(w, "cycles_required must be an integer from 1 through 10")
		return
	}

	if err := dbCreatePlayDowntimeActivity(id, req.ActivityID, req.Name, req.CyclesRequired); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "activity id already exists")
			return
		}
		log.Printf("create play downtime activity: %v", err)
		badRequest(w, "failed to create downtime activity")
		return
	}

	writeJSON(w, http.StatusCreated, downtimeActivity{
		ActivityID:     req.ActivityID,
		Name:           req.Name,
		CyclesRequired: req.CyclesRequired,
	})
}

// createPlayDowntimeAllocationHandler lets a player allocate a downtime activity to an owned character.
func createPlayDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role == roleDM {
		forbidden(w, "only players may allocate downtime activities")
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("character_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may allocate downtime activities")
		return
	}

	var req downtimeAllocationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	req.ActivityID = strings.TrimSpace(req.ActivityID)
	if req.ActivityID == "" {
		notFound(w, "activity not found")
		return
	}

	activity, err := dbGetPlayDowntimeActivity(id, req.ActivityID)
	if err != nil {
		log.Printf("get downtime activity: %v", err)
		badRequest(w, "failed to read activity")
		return
	}
	if activity == nil {
		notFound(w, "activity not found")
		return
	}

	if err := dbCreatePlayDowntimeAllocation(id, charID, req.ActivityID); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "allocation already exists")
			return
		}
		if isForeignKeyViolation(err) {
			notFound(w, "character or activity not found")
			return
		}
		log.Printf("create play downtime allocation: %v", err)
		badRequest(w, "failed to create downtime allocation")
		return
	}

	writeJSON(w, http.StatusCreated, downtimeAllocation{
		CharacterID:     charID,
		ActivityID:      req.ActivityID,
		CyclesCompleted: 0,
		Completions:     0,
	})
}

// progressPlayDowntimeAllocationHandler lets a character owner advance their downtime allocation.
func progressPlayDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role == roleDM {
		forbidden(w, "only players may progress downtime activities")
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("character_id")
	activityID := r.PathValue("activity_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may progress downtime activities")
		return
	}

	activity, err := dbGetPlayDowntimeActivity(id, activityID)
	if err != nil {
		log.Printf("get downtime activity: %v", err)
		badRequest(w, "failed to read activity")
		return
	}
	if activity == nil {
		notFound(w, "activity not found")
		return
	}

	allocation, err := dbProgressPlayDowntimeAllocation(id, charID, activityID)
	if err != nil {
		log.Printf("progress downtime allocation: %v", err)
		badRequest(w, "failed to progress downtime allocation")
		return
	}
	if allocation == nil {
		notFound(w, "allocation not found")
		return
	}

	writeJSON(w, http.StatusOK, allocation)
}

// getPlayDowntimeAllocationHandler lets an authenticated campaign member read an allocation.
func getPlayDowntimeAllocationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("character_id")
	activityID := r.PathValue("activity_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	activity, err := dbGetPlayDowntimeActivity(id, activityID)
	if err != nil {
		log.Printf("get downtime activity: %v", err)
		badRequest(w, "failed to read activity")
		return
	}
	if activity == nil {
		notFound(w, "activity not found")
		return
	}

	allocation, err := dbGetPlayDowntimeAllocation(id, charID, activityID)
	if err != nil {
		log.Printf("get downtime allocation: %v", err)
		badRequest(w, "failed to read allocation")
		return
	}
	if allocation == nil {
		notFound(w, "allocation not found")
		return
	}

	writeJSON(w, http.StatusOK, allocation)
}
