package main

import (
	"net/http"
	"sync"
)

const canonicalFixtureID = "canonical-v1"

// fixtureCharacter is one of the canonical fixture's pregenerated characters.
type fixtureCharacter struct {
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// fixtureState holds a campaign's seeded canonical fixture state.
type fixtureState struct {
	CampaignID string
	FixtureID  string
	Status     string
	Characters []fixtureCharacter
	Story      string
	EventIDs   []string
}

// fixtureStatesMu guards fixtureStates, the in-memory index mirroring the
// play_fixture_states table. Keyed by campaign id.
var (
	fixtureStatesMu sync.Mutex
	fixtureStates   = map[string]*fixtureState{}
)

func canonicalFixtureState(campaignID string) *fixtureState {
	return &fixtureState{
		CampaignID: campaignID,
		FixtureID:  canonicalFixtureID,
		Status:     "seeded",
		Characters: []fixtureCharacter{
			{CharacterID: "fixture-hero", Name: "Ari", Class: "fighter"},
			{CharacterID: "fixture-mage", Name: "Bea", Class: "wizard"},
		},
		Story:    "The lantern is lit.",
		EventIDs: []string{"fixture-event-1", "fixture-event-2"},
	}
}

func fixtureStateJSON(s *fixtureState) map[string]any {
	characters := make([]map[string]any, 0, len(s.Characters))
	for _, c := range s.Characters {
		characters = append(characters, map[string]any{
			"character_id": c.CharacterID,
			"name":         c.Name,
			"class":        c.Class,
		})
	}
	return map[string]any{
		"fixture_id": s.FixtureID,
		"status":     s.Status,
		"characters": characters,
		"story":      s.Story,
		"event_ids":  s.EventIDs,
	}
}

type createFixtureSeedRequest struct {
	FixtureID any `json:"fixture_id"`
}

// createFixtureSeedHandler lets only the campaign dm atomically seed the
// canonical fixture state for a campaign. Idempotent on repeated valid seeds.
func createFixtureSeedHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createFixtureSeedRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may seed fixture state")
		return
	}

	fixtureID, isString := req.FixtureID.(string)
	if !isString || fixtureID != canonicalFixtureID {
		writeError(w, http.StatusBadRequest, "fixture_id must be exactly canonical-v1")
		return
	}

	fixtureStatesMu.Lock()
	defer fixtureStatesMu.Unlock()

	if existing, present := fixtureStates[campaignID]; present {
		writeJSON(w, http.StatusOK, fixtureStateJSON(existing))
		return
	}

	s := canonicalFixtureState(campaignID)
	if err := saveFixtureStateToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save fixture state")
		return
	}
	fixtureStates[campaignID] = s

	writeJSON(w, http.StatusCreated, fixtureStateJSON(s))
}

// getFixtureStateHandler lets any authenticated campaign member, including
// the dm, read the campaign's seeded fixture state.
func getFixtureStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	fixtureStatesMu.Lock()
	defer fixtureStatesMu.Unlock()

	s, present := fixtureStates[campaignID]
	if !present {
		writeError(w, http.StatusNotFound, "no fixture seeded for this campaign")
		return
	}

	writeJSON(w, http.StatusOK, fixtureStateJSON(s))
}
