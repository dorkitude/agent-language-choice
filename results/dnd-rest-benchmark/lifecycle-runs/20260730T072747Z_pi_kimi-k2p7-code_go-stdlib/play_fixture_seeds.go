package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// fixtureSeedRequest binds the payload for seeding a canonical fixture.
type fixtureSeedRequest struct {
	FixtureID string `json:"fixture_id"`
}

// fixtureCharacter is one character in a seeded fixture.
type fixtureCharacter struct {
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// fixtureStateResponse is the exact shape returned for fixture seed and read.
type fixtureStateResponse struct {
	FixtureID  string             `json:"fixture_id"`
	Status     string             `json:"status"`
	Characters []fixtureCharacter `json:"characters"`
	Story      string             `json:"story"`
	EventIDs   []string           `json:"event_ids"`
}

const canonicalFixtureID = "canonical-v1"
const canonicalFixtureStory = "The lantern is lit."

var canonicalFixtureCharacters = []fixtureCharacter{
	{CharacterID: "fixture-hero", Name: "Ari", Class: "fighter"},
	{CharacterID: "fixture-mage", Name: "Bea", Class: "wizard"},
}

var canonicalFixtureEventIDs = []string{
	"fixture-event-1",
	"fixture-event-2",
}

// queryFixtureState loads the seeded fixture for a campaign, if any. The
// caller must hold dbMu.
func queryFixtureState(campaignID string) (*fixtureStateResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT fixture_id, status, story FROM campaign_fixture_state WHERE campaign_id=%s LIMIT 1;",
		sq(campaignID)))
	if err != nil {
		return nil, false, err
	}
	var rows []struct {
		FixtureID string `json:"fixture_id"`
		Status    string `json:"status"`
		Story     string `json:"story"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}

	characters, err := queryFixtureCharacters(campaignID)
	if err != nil {
		return nil, true, err
	}
	events, err := queryFixtureEvents(campaignID)
	if err != nil {
		return nil, true, err
	}

	return &fixtureStateResponse{
		FixtureID:  rows[0].FixtureID,
		Status:     rows[0].Status,
		Characters: characters,
		Story:      rows[0].Story,
		EventIDs:   events,
	}, true, nil
}

// queryFixtureCharacters loads the fixture characters for a campaign in
// canonical order. The caller must hold dbMu.
func queryFixtureCharacters(campaignID string) ([]fixtureCharacter, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT character_id, name, class FROM campaign_fixture_characters WHERE campaign_id=%s ORDER BY sort_order;",
		sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var characters []fixtureCharacter
	if err := json.Unmarshal(out, &characters); err != nil {
		return nil, err
	}
	if characters == nil {
		return []fixtureCharacter{}, nil
	}
	return characters, nil
}

// queryFixtureEvents loads the fixture event ids for a campaign in canonical
// order. The caller must hold dbMu.
func queryFixtureEvents(campaignID string) ([]string, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT event_id FROM campaign_fixture_events WHERE campaign_id=%s ORDER BY sort_order;",
		sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		EventID string `json:"event_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	events := make([]string, len(rows))
	for i, r := range rows {
		events[i] = r.EventID
	}
	return events, nil
}

// seedFixtureHandler creates the canonical fixture for a campaign. Only the
// campaign DM may call this endpoint. Repeating a valid seed is idempotent.
func seedFixtureHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req fixtureSeedRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.FixtureID != canonicalFixtureID {
		writeError(w, http.StatusBadRequest, "invalid fixture_id")
		return
	}

	existing, exists, err := queryFixtureState(campaignID)
	if err != nil {
		log.Printf("fixture seed query state error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeJSON(w, http.StatusOK, existing)
		return
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT INTO campaign_fixture_state (campaign_id, fixture_id, status, story) VALUES (%s, %s, 'seeded', %s);",
		sq(campaignID), sq(canonicalFixtureID), sq(canonicalFixtureStory))); err != nil {
		log.Printf("fixture seed insert state error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for i, c := range canonicalFixtureCharacters {
		if err := dbExec(fmt.Sprintf(
			"INSERT INTO campaign_fixture_characters (campaign_id, character_id, name, class, sort_order) VALUES (%s, %s, %s, %s, %d);",
			sq(campaignID), sq(c.CharacterID), sq(c.Name), sq(c.Class), i)); err != nil {
			log.Printf("fixture seed insert character error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	for i, e := range canonicalFixtureEventIDs {
		if err := dbExec(fmt.Sprintf(
			"INSERT INTO campaign_fixture_events (campaign_id, event_id, sort_order) VALUES (%s, %s, %d);",
			sq(campaignID), sq(e), i)); err != nil {
			log.Printf("fixture seed insert event error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusCreated, fixtureStateResponse{
		FixtureID:  canonicalFixtureID,
		Status:     "seeded",
		Characters: canonicalFixtureCharacters,
		Story:      canonicalFixtureStory,
		EventIDs:   canonicalFixtureEventIDs,
	})
}

// getFixtureStateHandler reads the seeded fixture for a campaign. Authenticated
// campaign members, including the DM, may read. If no fixture has been seeded,
// the endpoint returns 404.
func getFixtureStateHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignMemberOrDM(w, r, campaignID); !ok {
		return
	}

	state, exists, err := queryFixtureState(campaignID)
	if err != nil {
		log.Printf("fixture state query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "fixture not seeded")
		return
	}

	writeJSON(w, http.StatusOK, state)
}
