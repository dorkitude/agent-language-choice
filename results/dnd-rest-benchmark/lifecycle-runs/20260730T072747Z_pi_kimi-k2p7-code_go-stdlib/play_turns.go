package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type travelRequest struct {
	DestinationID string `json:"destination_id"`
}

// travelEvent is the ordered event returned when a player consumes a turn to
// travel along a valid location edge.
type travelEvent struct {
	Sequence      int    `json:"sequence"`
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	DestinationID string `json:"destination_id"`
	TravelTurns   int    `json:"travel_turns"`
	NextActor     string `json:"next_actor"`
}

// restRequest binds the payload for a rest turn.
type restRequest struct {
	Type string `json:"type"`
}

// restEvent is the ordered event returned when a player consumes a turn to
// rest. A long rest restores the acting character to full HP and clears any
// death-save counters.
type restEvent struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Type      string `json:"type"`
	HPCurrent int    `json:"hp_current"`
	HPMax     int    `json:"hp_max"`
	NextActor string `json:"next_actor"`
}

func resolveCurrentLocation(campaignID string, campaign *playCampaign) (string, bool, error) {
	if campaign.CurrentLocationID != "" {
		if _, ok, err := queryCampaignLocation(campaignID, campaign.CurrentLocationID); err != nil {
			return "", false, err
		} else if ok {
			return campaign.CurrentLocationID, true, nil
		}
	}
	if campaign.CurrentSceneID != "" {
		if _, ok, err := queryCampaignLocation(campaignID, campaign.CurrentSceneID); err != nil {
			return "", false, err
		} else if ok {
			return campaign.CurrentSceneID, true, nil
		}
	}
	out, err := dbQuery(fmt.Sprintf("SELECT id FROM campaign_locations WHERE campaign_id=%s ORDER BY rowid ASC LIMIT 1;", sq(campaignID)))
	if err != nil {
		return "", false, err
	}
	var rows []struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return "", false, err
	}
	if len(rows) == 0 {
		return "", false, nil
	}
	return rows[0].ID, true, nil
}

// travelTurnHandler lets the active player of a play campaign consume an
// exploration turn to travel to a destination. The destination must be a
// valid outbound connection from the party's current location. The location
// graph and current scene are not modified, but the party's current location
// is updated to the destination. The turn passes to the DM after the travel
// event is recorded.
func travelTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireCampaignOwnerOrMember(w, r, r.PathValue("id"))
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req travelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.DestinationID == "" {
		writeError(w, http.StatusBadRequest, "invalid destination")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("travel campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Status != "active" {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	if username == campaign.Owner {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("travel members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	currentActor := campaign.TurnActor
	if currentActor == "" && len(members) > 0 {
		currentActor = members[0].Username
	}
	if currentActor != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	currentLocation, ok, err := resolveCurrentLocation(campaignID, campaign)
	if err != nil {
		log.Printf("travel current location query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusConflict, "invalid destination")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT travel_turns FROM location_connections WHERE campaign_id=%s AND from_id=%s AND to_id=%s LIMIT 1;",
		sq(campaignID), sq(currentLocation), sq(req.DestinationID)))
	if err != nil {
		log.Printf("travel connection query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var connRows []struct {
		TravelTurns int `json:"travel_turns"`
	}
	if err := json.Unmarshal(out, &connRows); err != nil {
		log.Printf("travel connection unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(connRows) == 0 {
		writeError(w, http.StatusConflict, "invalid destination")
		return
	}
	travelTurns := connRows[0].TravelTurns

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("travel sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, destination_id, travel_turns, text) VALUES (%s, %d, 'travel', %s, %s, %d, '');",
		sq(campaignID), nextSeq, sq(username), sq(req.DestinationID), travelTurns)); err != nil {
		log.Printf("travel insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET turn_actor=%s, current_location_id=%s WHERE id=%s;",
		sq(campaign.Owner), sq(req.DestinationID), sq(campaignID))); err != nil {
		log.Printf("travel turn actor update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, travelEvent{
		Sequence:      nextSeq,
		Kind:          "travel",
		Actor:         username,
		DestinationID: req.DestinationID,
		TravelTurns:   travelTurns,
		NextActor:     "dm",
	})
}

// restTurnHandler lets the active player of a play campaign consume an
// exploration turn to rest. Only the current actor may call it. A long rest
// restores the acting character to full HP and clears any death-save counters.
// The turn passes to the DM after the rest event is recorded.
func restTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireCampaignOwnerOrMember(w, r, r.PathValue("id"))
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req restRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Type != "long" && req.Type != "short" {
		writeError(w, http.StatusBadRequest, "invalid type")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("rest campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Status != "active" {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	if username == campaign.Owner {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("rest members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	currentActor := campaign.TurnActor
	if currentActor == "" && len(members) > 0 {
		currentActor = members[0].Username
	}
	if currentActor != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	var callerMember *playCampaignMember
	for i := range members {
		if members[i].Username == username {
			callerMember = &members[i]
			break
		}
	}
	if callerMember == nil {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	hpCurrent := callerMember.HPCurrent
	hpMax := callerMember.HPMax
	if req.Type == "long" {
		hpCurrent = hpMax
		if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET hp_current=%d, status='conscious', death_saves_successes=0, death_saves_failures=0 WHERE character_id=%s;",
			hpCurrent, sq(callerMember.CharacterID))); err != nil {
			log.Printf("rest hp update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("rest sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (%s, %d, 'rest', %s, %s, '');",
		sq(campaignID), nextSeq, sq(username), sq(req.Type))); err != nil {
		log.Printf("rest insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET turn_actor=%s WHERE id=%s;",
		sq(campaign.Owner), sq(campaignID))); err != nil {
		log.Printf("rest turn actor update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, restEvent{
		Sequence:  nextSeq,
		Kind:      "rest",
		Actor:     username,
		Type:      req.Type,
		HPCurrent: hpCurrent,
		HPMax:     hpMax,
		NextActor: "dm",
	})
}

// campaignDocumentRequest binds the payload for updating a campaign document.
type campaignDocumentRequest struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// ownerCampaignDocumentResponse is the full document view returned to the
// campaign owner on both GET and PUT.
type ownerCampaignDocumentResponse struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// playerCampaignDocumentResponse is the public document view returned to a
// player member; it deliberately omits the DM-private notes field and the
// campaign ID so the response matches the exact public document shape.
type playerCampaignDocumentResponse struct {
	Story string `json:"story"`
}

// requireCampaignOwner authenticates the request and authorizes only the
// owner of the identified play campaign. It returns the authenticated username
// on success, or writes 401/403/404 and returns false on failure.
