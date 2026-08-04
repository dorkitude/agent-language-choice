package main

import (
	"log"
	"net/http"
	"sync"
)

// campaignMetricsMu guards campaignRejectedRateEvents, the in-memory index
// mirroring the play_campaign_metrics table. Keyed by campaign id, holding
// the count of ticket 087 rate events rejected with HTTP 429. The accepted
// rate event and projection event counters are derived directly from the
// existing campaignRateEvents and campaignProjectionEvents indexes, so they
// need no separate storage here.
var (
	campaignMetricsMu          sync.Mutex
	campaignRejectedRateEvents = map[string]int{}
)

// recordRejectedRateEvent increments campaignID's rejected-rate-event
// counter, persisting the new total to the database.
func recordRejectedRateEvent(campaignID string) {
	campaignMetricsMu.Lock()
	defer campaignMetricsMu.Unlock()
	campaignRejectedRateEvents[campaignID]++
	if err := saveCampaignMetricsToDB(campaignID, campaignRejectedRateEvents[campaignID]); err != nil {
		log.Printf("failed to save campaign metrics: %v", err)
	}
}

// getMetricsHandler lets the campaign owner read safe aggregate counters for
// a campaign. Campaign players and other authenticated users receive 403.
func getMetricsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign owner may read metrics")
		return
	}

	campaignRateEventsMu.Lock()
	accepted := len(campaignRateEvents[campaignID])
	campaignRateEventsMu.Unlock()

	campaignProjectionsMu.Lock()
	projections := len(campaignProjectionEvents[campaignID])
	campaignProjectionsMu.Unlock()

	campaignMetricsMu.Lock()
	rejected := campaignRejectedRateEvents[campaignID]
	campaignMetricsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"accepted_rate_events": accepted,
		"rejected_rate_events": rejected,
		"projection_events":    projections,
		"uptime_ticks":         1,
	})
}
