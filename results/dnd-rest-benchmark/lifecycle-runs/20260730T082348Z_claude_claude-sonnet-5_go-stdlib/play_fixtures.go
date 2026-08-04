package main

import (
	"encoding/json"
	"net/http"
)

const playCanonicalFixtureID = "canonical-v1"

func playFixtureStateResponse() map[string]interface{} {
	return map[string]interface{}{
		"fixture_id": playCanonicalFixtureID,
		"status":     "seeded",
		"characters": []map[string]interface{}{
			{"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
			{"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
		},
		"story":     "The lantern is lit.",
		"event_ids": []string{"fixture-event-1", "fixture-event-2"},
	}
}

// handlePlayCampaignFixtureSub routes the "fixture-seeds" and
// "fixture-state" sub-paths of a play campaign. It returns false if rest
// does not name a fixture path, so the caller can fall through to its own
// routing.
func handlePlayCampaignFixtureSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "fixture-seeds":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleSeedPlayFixture(w, r, campaignID)
		return true
	case "fixture-state":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleReadPlayFixtureState(w, r, campaignID)
		return true
	}
	return false
}

func handleSeedPlayFixture(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var raw struct {
		FixtureID *string `json:"fixture_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if raw.FixtureID == nil || *raw.FixtureID != playCanonicalFixtureID {
		writeError(w, http.StatusBadRequest, "fixture_id must be canonical-v1")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be the campaign dm")
		return
	}

	alreadySeeded := c.FixtureSeeded
	c.FixtureSeeded = true
	resp := playFixtureStateResponse()
	playMu.Unlock()

	if !alreadySeeded {
		persistState()
		writeJSON(w, http.StatusCreated, resp)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func handleReadPlayFixtureState(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}
	if !c.FixtureSeeded {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "fixture not seeded")
		return
	}
	resp := playFixtureStateResponse()
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
