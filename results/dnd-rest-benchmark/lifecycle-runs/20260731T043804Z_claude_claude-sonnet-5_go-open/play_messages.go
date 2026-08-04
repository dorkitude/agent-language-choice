package main

import (
	"net/http"
	"sync"
)

// playMessage is a party chat message visible to campaign members and the dm.
type playMessage struct {
	CampaignID string
	Sequence   int
	Actor      string
	Text       string
}

// campaignMessagesMu guards campaignMessages, keyed by campaign id, holding
// messages in creation order.
var (
	campaignMessagesMu sync.Mutex
	campaignMessages   = map[string][]*playMessage{}
)

func messageJSON(m *playMessage) map[string]any {
	return map[string]any{
		"sequence": m.Sequence,
		"kind":     "chat",
		"actor":    m.Actor,
		"text":     m.Text,
	}
}

type createMessageRequest struct {
	Text string `json:"text"`
}

// createMessageHandler lets an authenticated campaign member or the dm post a
// party chat message. Spectator tokens are never valid session credentials,
// so requireActor rejects them with 401 before this handler runs.
func createMessageHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createMessageRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if _, ok := requireCampaignAccess(w, c, actor); !ok {
		return
	}

	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	campaignMessagesMu.Lock()
	defer campaignMessagesMu.Unlock()

	m := &playMessage{
		CampaignID: campaignID,
		Sequence:   len(campaignMessages[campaignID]) + 1,
		Actor:      actor.Username,
		Text:       req.Text,
	}
	campaignMessages[campaignID] = append(campaignMessages[campaignID], m)

	writeJSON(w, http.StatusCreated, messageJSON(m))
}
