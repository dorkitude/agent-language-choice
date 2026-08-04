package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// appendProjectionEventRequest binds the payload for appending a projection
// event. The value field is deliberately parsed as raw JSON so that we can
// distinguish omission from null or a non-string value.
type appendProjectionEventRequest struct {
	EventID string          `json:"event_id"`
	Kind    string          `json:"kind"`
	Value   json.RawMessage `json:"value"`
}

// projectionEventResponse is the immutable projection event shape returned by
// the append endpoint. For increment-danger events the value field is omitted.
type projectionEventResponse struct {
	Sequence int     `json:"sequence"`
	EventID  string  `json:"event_id"`
	Kind     string  `json:"kind"`
	Value    *string `json:"value,omitempty"`
}

// projectionResponse is the deterministic read model rebuilt from the ordered
// projection event log.
type projectionResponse struct {
	Story           string   `json:"story"`
	Danger          int      `json:"danger"`
	AppliedEventIDs []string `json:"applied_event_ids"`
}

// isPlayCampaignMember reports whether the user is a member of the campaign.
// The caller must hold dbMu and must have already verified the campaign exists.
func isPlayCampaignMember(campaignID, username string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// nextProjectionSequence returns the next monotonic sequence number for a
// campaign's projection event log. The caller must hold dbMu.
func nextProjectionSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_projection_events WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// createProjectionEventHandler lets authenticated campaign player members
// append a projection event. The campaign DM may read projections but may not
// append. Duplicate event_ids per campaign return 409; invalid payloads return
// 400; unknown campaigns return 404; non-members return 403.
func createProjectionEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("projection event auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("projection event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner == username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	isMember, err := isPlayCampaignMember(campaignID, username)
	if err != nil {
		log.Printf("projection event member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req appendProjectionEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" {
		writeError(w, http.StatusBadRequest, "invalid projection event")
		return
	}
	if req.Kind != "set-story" && req.Kind != "increment-danger" {
		writeError(w, http.StatusBadRequest, "invalid projection event")
		return
	}

	var value *string
	switch req.Kind {
	case "set-story":
		if len(req.Value) == 0 || string(req.Value) == "null" {
			writeError(w, http.StatusBadRequest, "invalid projection event")
			return
		}
		var s string
		if err := json.Unmarshal(req.Value, &s); err != nil || s == "" {
			writeError(w, http.StatusBadRequest, "invalid projection event")
			return
		}
		value = &s
	case "increment-danger":
		if len(req.Value) != 0 {
			writeError(w, http.StatusBadRequest, "invalid projection event")
			return
		}
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_projection_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("projection event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "event_id already exists")
		return
	}

	nextSeq, err := nextProjectionSequence(campaignID)
	if err != nil {
		log.Printf("projection event sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	valueSQL := "NULL"
	if value != nil {
		valueSQL = sq(*value)
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (%s, %d, %s, %s, %s);",
		sq(campaignID), nextSeq, sq(req.EventID), sq(req.Kind), valueSQL)); err != nil {
		log.Printf("projection event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := incrementProjectionEvents(campaignID); err != nil {
		log.Printf("projection event counter error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, projectionEventResponse{
		Sequence: nextSeq,
		EventID:  req.EventID,
		Kind:     req.Kind,
		Value:    value,
	})
}

// queryProjectionEvents loads all projection events for a campaign ordered by
// sequence. The caller must hold dbMu.
func queryProjectionEvents(campaignID string) ([]struct {
	Sequence int     `json:"sequence"`
	EventID  string  `json:"event_id"`
	Kind     string  `json:"kind"`
	Value    *string `json:"value"`
}, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT sequence, event_id, kind, value FROM campaign_projection_events WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		Sequence int     `json:"sequence"`
		EventID  string  `json:"event_id"`
		Kind     string  `json:"kind"`
		Value    *string `json:"value"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if rows == nil {
		return []struct {
			Sequence int     `json:"sequence"`
			EventID  string  `json:"event_id"`
			Kind     string  `json:"kind"`
			Value    *string `json:"value"`
		}{}, nil
	}
	return rows, nil
}

// rebuildProjection deterministically rebuilds the campaign projection from
// the ordered event log. The caller must hold dbMu.
func rebuildProjection(campaignID string) (projectionResponse, error) {
	events, err := queryProjectionEvents(campaignID)
	if err != nil {
		return projectionResponse{}, err
	}

	proj := projectionResponse{
		Story:           "",
		Danger:          0,
		AppliedEventIDs: []string{},
	}
	for _, ev := range events {
		switch ev.Kind {
		case "set-story":
			if ev.Value != nil {
				proj.Story = *ev.Value
			}
		case "increment-danger":
			proj.Danger++
		}
		proj.AppliedEventIDs = append(proj.AppliedEventIDs, ev.EventID)
	}
	if proj.AppliedEventIDs == nil {
		proj.AppliedEventIDs = []string{}
	}
	return proj, nil
}

// requireProjectionReader authenticates the request and authorizes the campaign
// DM or a campaign member to read a projection. Unknown campaigns return 404;
// unauthenticated requests return 401; non-members return 403.
func requireProjectionReader(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("projection reader auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("projection reader campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", false
	}

	if campaign.Owner == username {
		return username, true
	}
	isMember, err := isPlayCampaignMember(campaignID, username)
	if err != nil {
		log.Printf("projection reader member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	return username, true
}

// getProjectionHandler returns the deterministic projection rebuilt from the
// campaign's ordered projection event log. The campaign DM and members may
// read it.
func getProjectionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireProjectionReader(w, r, campaignID); !ok {
		return
	}

	proj, err := rebuildProjection(campaignID)
	if err != nil {
		log.Printf("projection get rebuild error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, proj)
}

// rebuildProjectionHandler explicitly rebuilds the projection from the ordered
// event log and returns the same exact JSON as the read endpoint. The campaign
// DM and members may request it.
func rebuildProjectionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireProjectionReader(w, r, campaignID); !ok {
		return
	}

	proj, err := rebuildProjection(campaignID)
	if err != nil {
		log.Printf("projection rebuild rebuild error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, proj)
}
