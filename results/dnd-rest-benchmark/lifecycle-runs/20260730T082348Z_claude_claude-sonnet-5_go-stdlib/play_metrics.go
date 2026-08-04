package main

import "net/http"

// handlePlayCampaignMetricsSub routes the "metrics" sub-path of a play
// campaign.
func handlePlayCampaignMetricsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "metrics" {
		return false
	}
	handleGetPlayCampaignMetrics(w, r, id)
	return true
}

func handleGetPlayCampaignMetrics(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be the campaign dm")
		return
	}

	resp := map[string]interface{}{
		"accepted_rate_events": c.MetricsAcceptedRateEvents,
		"rejected_rate_events": c.MetricsRejectedRateEvents,
		"projection_events":    c.MetricsProjectionEvents,
		"uptime_ticks":         1,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
