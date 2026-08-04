package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createWorldEventHandler schedules a deterministic campaign-level world event.
// Only the campaign owner (DM) may schedule world events. Players receive 403.
// The event_id, title, and text fields must be nonempty strings, and
// turn_number must be an integer greater than or equal to the campaign's
// current turn_number. Duplicate event IDs in the same campaign return 409.
func createWorldEventHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can schedule world events")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can schedule world events")
		return
	}

	var req worldEventCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.EventID) == "" {
		badRequest(w, "event_id is required")
		return
	}
	if strings.TrimSpace(req.Title) == "" {
		badRequest(w, "title is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	_, currentTurn, exists, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}
	if !exists {
		notFound(w, "campaign not found")
		return
	}
	if req.TurnNumber < currentTurn {
		badRequest(w, "turn_number must be greater than or equal to the current turn number")
		return
	}

	if err := dbCreateWorldEvent(id, req.EventID, req.TurnNumber, req.Title, req.Text); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "event id already exists")
			return
		}
		log.Printf("create world event: %v", err)
		badRequest(w, "failed to create world event")
		return
	}

	writeJSON(w, http.StatusCreated, worldEvent{
		EventID:    req.EventID,
		TurnNumber: req.TurnNumber,
		Title:      req.Title,
		Text:       req.Text,
		Status:     worldEventStatusScheduled,
	})
}

// resolveWorldEventHandler records an immutable resolution for a world event.
// Only the campaign owner (DM) may resolve world events. Players receive 403.
// Unknown events return 404. The resolution text must be nonempty. If the
// campaign's current turn number does not exactly match the event turn_number,
// resolution returns 409. If the event is already resolved, resolution returns
// 409 and does not change the stored resolution.
func resolveWorldEventHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can resolve world events")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can resolve world events")
		return
	}

	eventID := r.PathValue("event_id")

	event, err := dbGetWorldEvent(id, eventID)
	if err != nil {
		log.Printf("get world event: %v", err)
		badRequest(w, "failed to read world event")
		return
	}
	if event == nil {
		notFound(w, "world event not found")
		return
	}

	var req worldEventResolveRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	if event.Status == worldEventStatusResolved {
		conflict(w, "event is already resolved")
		return
	}

	_, currentTurn, exists, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}
	if !exists {
		notFound(w, "campaign not found")
		return
	}
	if currentTurn != event.TurnNumber {
		conflict(w, "campaign turn does not match event turn")
		return
	}

	if err := dbResolveWorldEvent(id, eventID, currentTurn, req.Text); err != nil {
		log.Printf("resolve world event: %v", err)
		badRequest(w, "failed to resolve world event")
		return
	}

	writeJSON(w, http.StatusCreated, worldEvent{
		EventID:    event.EventID,
		TurnNumber: event.TurnNumber,
		Title:      event.Title,
		Text:       event.Text,
		Status:     worldEventStatusResolved,
		Resolution: &worldEventResolution{
			TurnNumber: currentTurn,
			Text:       req.Text,
		},
	})
}

// getWorldEventsHandler lists all world events for a play campaign. The
// campaign owner and any bound party member may read the list. Events are
// returned ordered by turn_number ascending, then by creation order for ties.
func getWorldEventsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	events, err := dbGetWorldEvents(id)
	if err != nil {
		log.Printf("get world events: %v", err)
		badRequest(w, "failed to read world events")
		return
	}

	writeJSON(w, http.StatusOK, worldEventsResponse{Events: events})
}
