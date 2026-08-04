package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// worldEventCreateRequest binds the payload for scheduling a world event.
type worldEventCreateRequest struct {
	EventID   string `json:"event_id"`
	TurnNumber int    `json:"turn_number"`
	Title     string `json:"title"`
	Text      string `json:"text"`
}

// worldEventResolveRequest binds the payload for resolving a world event.
type worldEventResolveRequest struct {
	Text string `json:"text"`
}

// worldEventResolution is the immutable resolution record stored when a
// world event is resolved exactly once.
type worldEventResolution struct {
	TurnNumber int    `json:"turn_number"`
	Text       string `json:"text"`
}

// worldEventResponse is the shape returned for a scheduled or resolved world
// event. The resolution field is omitted for scheduled events.
type worldEventResponse struct {
	EventID    string                 `json:"event_id"`
	TurnNumber int                    `json:"turn_number"`
	Title      string                 `json:"title"`
	Text       string                 `json:"text"`
	Status     string                 `json:"status"`
	Resolution *worldEventResolution  `json:"resolution,omitempty"`
}

// worldEventListResponse is the shape returned by the world event listing
// endpoint.
type worldEventListResponse struct {
	Events []worldEventResponse `json:"events"`
}

// loadWorldEvent loads a single campaign world event by campaign and event id.
// The caller must hold dbMu.
func loadWorldEvent(campaignID, eventID string) (*worldEventResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT event_id, turn_number, title, text, status, resolution_text FROM campaign_world_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(eventID)))
	if err != nil {
		return nil, false, err
	}
	var rows []struct {
		EventID         string `json:"event_id"`
		TurnNumber      int    `json:"turn_number"`
		Title           string `json:"title"`
		Text            string `json:"text"`
		Status          string `json:"status"`
		ResolutionText  string `json:"resolution_text"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	resp := &worldEventResponse{
		EventID:    rows[0].EventID,
		TurnNumber: rows[0].TurnNumber,
		Title:      rows[0].Title,
		Text:       rows[0].Text,
		Status:     rows[0].Status,
	}
	if rows[0].Status == "resolved" && rows[0].ResolutionText != "" {
		resp.Resolution = &worldEventResolution{
			TurnNumber: rows[0].TurnNumber,
			Text:       rows[0].ResolutionText,
		}
	}
	return resp, true, nil
}

// createWorldEventHandler lets the campaign DM schedule a deterministic world
// event. Players receive 403. Duplicate event IDs in the same campaign return
// 409. Invalid bodies return 400.
func createWorldEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("create world event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var req worldEventCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Title == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid event")
		return
	}
	if req.TurnNumber < campaign.TurnNumber {
		writeError(w, http.StatusBadRequest, "invalid turn number")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_world_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("create world event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "event already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (%s, %s, %d, %s, %s, 'scheduled');",
		sq(campaignID), sq(req.EventID), req.TurnNumber, sq(req.Title), sq(req.Text))); err != nil {
		log.Printf("create world event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, worldEventResponse{
		EventID:    req.EventID,
		TurnNumber: req.TurnNumber,
		Title:      req.Title,
		Text:       req.Text,
		Status:     "scheduled",
	})
}

// resolveWorldEventHandler lets the campaign DM resolve a scheduled world
// event exactly once. Players receive 403. Unknown events return 404. The
// resolution text must be nonempty. If the campaign's current turn number
// does not match the event's turn number, or if the event is already resolved,
// resolution returns 409.
func resolveWorldEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	eventID := r.PathValue("event_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("resolve world event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var req worldEventResolveRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid resolution")
		return
	}

	event, ok, err := loadWorldEvent(campaignID, eventID)
	if err != nil {
		log.Printf("resolve world event load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "event not found")
		return
	}

	if event.Status == "resolved" {
		writeError(w, http.StatusConflict, "event already resolved")
		return
	}
	if campaign.TurnNumber != event.TurnNumber {
		writeError(w, http.StatusConflict, "wrong turn")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_world_events SET status='resolved', resolution_text=%s WHERE campaign_id=%s AND event_id=%s;",
		sq(req.Text), sq(campaignID), sq(eventID))); err != nil {
		log.Printf("resolve world event update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, worldEventResponse{
		EventID:    event.EventID,
		TurnNumber: event.TurnNumber,
		Title:      event.Title,
		Text:       event.Text,
		Status:     "resolved",
		Resolution: &worldEventResolution{
			TurnNumber: event.TurnNumber,
			Text:       req.Text,
		},
	})
}

// listWorldEventsHandler returns all world events for a campaign ordered by
// turn_number ascending, then creation order. It is available to authenticated
// campaign members.
func listWorldEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT event_id, turn_number, title, text, status, resolution_text FROM campaign_world_events WHERE campaign_id=%s ORDER BY turn_number, id;", sq(campaignID)))
	if err != nil {
		log.Printf("list world events query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		EventID        string `json:"event_id"`
		TurnNumber     int    `json:"turn_number"`
		Title          string `json:"title"`
		Text           string `json:"text"`
		Status         string `json:"status"`
		ResolutionText string `json:"resolution_text"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list world events unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	events := make([]worldEventResponse, 0, len(rows))
	for _, row := range rows {
		e := worldEventResponse{
			EventID:    row.EventID,
			TurnNumber: row.TurnNumber,
			Title:      row.Title,
			Text:       row.Text,
			Status:     row.Status,
		}
		if row.Status == "resolved" && row.ResolutionText != "" {
			e.Resolution = &worldEventResolution{
				TurnNumber: row.TurnNumber,
				Text:       row.ResolutionText,
			}
		}
		events = append(events, e)
	}
	if events == nil {
		events = []worldEventResponse{}
	}

	writeJSON(w, http.StatusOK, worldEventListResponse{Events: events})
}
