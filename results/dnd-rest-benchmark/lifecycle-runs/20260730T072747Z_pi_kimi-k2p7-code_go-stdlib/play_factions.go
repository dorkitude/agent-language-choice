package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// createPlayFactionRequest binds the payload for creating a new play faction.
type createPlayFactionRequest struct {
	FactionID string `json:"faction_id"`
	Name      string `json:"name"`
}

// playFactionResponse is the shape returned for a play faction.
type playFactionResponse struct {
	FactionID string `json:"faction_id"`
	Name      string `json:"name"`
}

// changeReputationRequest binds the payload for changing a character's reputation.
type changeReputationRequest struct {
	CharacterID string `json:"character_id"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// reputationEntry is a single immutable reputation history record.
type reputationEntry struct {
	FactionID   string `json:"faction_id"`
	CharacterID string `json:"character_id"`
	Reputation  int    `json:"reputation"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// reputationResponse is the shape returned for a reputation query.
type reputationResponse struct {
	FactionID string            `json:"faction_id"`
	Entries   []reputationEntry `json:"entries"`
}

// queryPlayFaction loads a play faction by campaign and faction id.
func queryPlayFaction(campaignID, factionID string) (*playFactionResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT faction_id, name FROM play_factions WHERE campaign_id=%s AND faction_id=%s LIMIT 1;", sq(campaignID), sq(factionID)))
	if err != nil {
		return nil, false, err
	}
	var rows []playFactionResponse
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// createPlayFactionHandler creates a new faction in a play campaign.
func createPlayFactionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createPlayFactionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.FactionID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid faction")
		return
	}

	_, exists, err := queryPlayFaction(campaignID, req.FactionID)
	if err != nil {
		log.Printf("create play faction query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "faction already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (%s, %s, %s);",
		sq(campaignID), sq(req.FactionID), sq(req.Name))); err != nil {
		log.Printf("create play faction insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, playFactionResponse{
		FactionID: req.FactionID,
		Name:      req.Name,
	})
}

// changeReputationHandler changes a character's reputation with a faction.
func changeReputationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	factionID := r.PathValue("faction_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	faction, ok, err := queryPlayFaction(campaignID, factionID)
	if err != nil {
		log.Printf("change reputation faction query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}

	var req changeReputationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "invalid character_id")
		return
	}
	if req.Reason == "" {
		writeError(w, http.StatusBadRequest, "invalid reason")
		return
	}
	if req.Delta == 0 || req.Delta < -25 || req.Delta > 25 {
		writeError(w, http.StatusBadRequest, "invalid delta")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, req.CharacterID)
	if err != nil {
		log.Printf("change reputation member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || member == nil {
		writeError(w, http.StatusBadRequest, "invalid character_id")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT reputation FROM faction_reputation_history WHERE campaign_id=%s AND faction_id=%s AND character_id=%s ORDER BY id DESC LIMIT 1;", sq(campaignID), sq(factionID), sq(req.CharacterID)))
	if err != nil {
		log.Printf("change reputation current query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var currentRows []struct {
		Reputation int `json:"reputation"`
	}
	if err := json.Unmarshal(out, &currentRows); err != nil {
		log.Printf("change reputation current unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	current := 0
	if len(currentRows) > 0 {
		current = currentRows[0].Reputation
	}

	newReputation := current + req.Delta
	if newReputation > 100 {
		newReputation = 100
	}
	if newReputation < -100 {
		newReputation = -100
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO faction_reputation_history (campaign_id, faction_id, character_id, delta, reputation, reason) VALUES (%s, %s, %s, %d, %d, %s);",
		sq(campaignID), sq(factionID), sq(req.CharacterID), req.Delta, newReputation, sq(req.Reason))); err != nil {
		log.Printf("change reputation insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, reputationEntry{
		FactionID:   faction.FactionID,
		CharacterID: req.CharacterID,
		Reputation:  newReputation,
		Delta:       req.Delta,
		Reason:      req.Reason,
	})
}

// getReputationHandler returns reputation history for a faction.
func getReputationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	factionID := r.PathValue("faction_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("get reputation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	faction, ok, err := queryPlayFaction(campaignID, factionID)
	if err != nil {
		log.Printf("get reputation faction query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}

	sql := fmt.Sprintf("SELECT faction_id, character_id, reputation, delta, reason FROM faction_reputation_history WHERE campaign_id=%s AND faction_id=%s", sq(campaignID), sq(factionID))
	if campaign.Owner != username {
		member, ok, err := queryPlayCampaignMemberByUsername(campaignID, username)
		if err != nil {
			log.Printf("get reputation member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !ok {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		sql += fmt.Sprintf(" AND character_id=%s", sq(member.CharacterID))
	}
	sql += " ORDER BY id;"

	out, err := dbQuery(sql)
	if err != nil {
		log.Printf("get reputation entries query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var entries []reputationEntry
	if err := json.Unmarshal(out, &entries); err != nil {
		log.Printf("get reputation entries unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if entries == nil {
		entries = []reputationEntry{}
	}

	writeJSON(w, http.StatusOK, reputationResponse{
		FactionID: faction.FactionID,
		Entries:   entries,
	})
}
