package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// serviceMetrics is the exact shape returned by the campaign service metrics
// endpoint. It exposes only safe aggregate counters and no campaign
// story, character, event, or actor content.
type serviceMetrics struct {
	AcceptedRateEvents int `json:"accepted_rate_events"`
	RejectedRateEvents int `json:"rejected_rate_events"`
	ProjectionEvents   int `json:"projection_events"`
	UptimeTicks        int `json:"uptime_ticks"`
}

// incrementAcceptedRateEvents increments the accepted rate event counter for
// the campaign. The caller must hold dbMu and must have already verified the
// campaign exists.
func incrementAcceptedRateEvents(campaignID string) error {
	return dbExec(fmt.Sprintf("INSERT INTO campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events) VALUES (%s, 1, 0, 0) ON CONFLICT(campaign_id) DO UPDATE SET accepted_rate_events = accepted_rate_events + 1;", sq(campaignID)))
}

// incrementRejectedRateEvents increments the rejected rate event counter for
// the campaign. The caller must hold dbMu and must have already verified the
// campaign exists.
func incrementRejectedRateEvents(campaignID string) error {
	return dbExec(fmt.Sprintf("INSERT INTO campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events) VALUES (%s, 0, 1, 0) ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = rejected_rate_events + 1;", sq(campaignID)))
}

// incrementProjectionEvents increments the accepted projection event counter
// for the campaign. The caller must hold dbMu and must have already verified
// the campaign exists.
func incrementProjectionEvents(campaignID string) error {
	return dbExec(fmt.Sprintf("INSERT INTO campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events) VALUES (%s, 0, 0, 1) ON CONFLICT(campaign_id) DO UPDATE SET projection_events = projection_events + 1;", sq(campaignID)))
}

// queryCampaignMetrics loads the current service metrics for a campaign. If no
// metrics row exists yet, all counters are returned as zero. The caller must
// hold dbMu.
func queryCampaignMetrics(campaignID string) (serviceMetrics, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT accepted_rate_events, rejected_rate_events, projection_events FROM campaign_service_metrics WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return serviceMetrics{}, err
	}
	var rows []struct {
		AcceptedRateEvents int `json:"accepted_rate_events"`
		RejectedRateEvents int `json:"rejected_rate_events"`
		ProjectionEvents   int `json:"projection_events"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return serviceMetrics{}, err
	}
	if len(rows) == 0 {
		return serviceMetrics{UptimeTicks: 1}, nil
	}
	return serviceMetrics{
		AcceptedRateEvents: rows[0].AcceptedRateEvents,
		RejectedRateEvents: rows[0].RejectedRateEvents,
		ProjectionEvents:   rows[0].ProjectionEvents,
		UptimeTicks:        1,
	}, nil
}

// getCampaignMetricsHandler returns the campaign-scoped service metrics. Only
// the campaign owner may read the counters; campaign players and other
// authenticated users receive 403. Unknown campaigns return 404 and
// unauthenticated requests return 401.
func getCampaignMetricsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("metrics auth query error: %v", err)
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
		log.Printf("metrics campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	metrics, err := queryCampaignMetrics(campaignID)
	if err != nil {
		log.Printf("metrics query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, metrics)
}
