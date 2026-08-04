package main

import (
	"net/http"
	"sync"
)

// sessionZeroSettings is a campaign's pre-start session-zero configuration,
// set once by the dm while the campaign is still in lobby.
type sessionZeroSettings struct {
	CampaignID string
	Rules      string
	Tone       string
	Consent    []string
}

// sessionZeroMu guards sessionZeroByCampaign, the in-memory index mirroring
// the play_session_zero table. Keyed by campaign id.
var (
	sessionZeroMu         sync.Mutex
	sessionZeroByCampaign = map[string]*sessionZeroSettings{}
)

func sessionZeroJSON(s *sessionZeroSettings) map[string]any {
	return map[string]any{
		"rules":   s.Rules,
		"tone":    s.Tone,
		"consent": s.Consent,
	}
}

type updateSessionZeroRequest struct {
	Rules   string   `json:"rules"`
	Tone    string   `json:"tone"`
	Consent []string `json:"consent"`
}

func validSessionZeroRequest(req *updateSessionZeroRequest) bool {
	if req.Rules == "" || req.Tone == "" {
		return false
	}
	if len(req.Consent) == 0 {
		return false
	}
	seen := make(map[string]bool, len(req.Consent))
	for _, c := range req.Consent {
		if c == "" || seen[c] {
			return false
		}
		seen[c] = true
	}
	return true
}

// updateSessionZeroHandler lets the campaign's owning dm set session-zero
// settings while the campaign is still in lobby.
func updateSessionZeroHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateSessionZeroRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may set session-zero settings")
		return
	}
	if c.Status != "lobby" {
		writeError(w, http.StatusConflict, "session-zero settings can only be changed while the campaign is in lobby")
		return
	}

	if !validSessionZeroRequest(&req) {
		writeError(w, http.StatusBadRequest, "rules and tone must be nonempty strings, and consent must be a nonempty array of unique nonempty strings")
		return
	}

	sessionZeroMu.Lock()
	defer sessionZeroMu.Unlock()

	s := &sessionZeroSettings{
		CampaignID: campaignID,
		Rules:      req.Rules,
		Tone:       req.Tone,
		Consent:    req.Consent,
	}
	if err := saveSessionZeroToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save session-zero settings")
		return
	}
	sessionZeroByCampaign[campaignID] = s

	writeJSON(w, http.StatusOK, sessionZeroJSON(s))
}

// getSessionZeroHandler returns a campaign's stored session-zero settings.
// Any authenticated campaign member, including the dm, may call this.
func getSessionZeroHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	sessionZeroMu.Lock()
	defer sessionZeroMu.Unlock()

	s, exists := sessionZeroByCampaign[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "session-zero settings have not been set for this campaign")
		return
	}

	writeJSON(w, http.StatusOK, sessionZeroJSON(s))
}
