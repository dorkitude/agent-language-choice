package main

import (
	"database/sql"
	"errors"
	"net/http"
)

// Deterministic analytics over the campaign state the earlier stages accumulated.
// Like audit.go these endpoints are pure readers: every number is a COUNT or a
// boolean derived from stored rows, so the same state always renders the same
// document.
//
// Counting rules are inherited rather than reinvented, so a campaign's analytics
// agree with the per-domain summaries:
//
//   - an "open" quest is one whose status is still questActive (quests.go)
//   - a "friendly" NPC is one with a positive disposition (npcs.go)
//   - inventory counts rows, not units, as the inventory summary does
//
// The readiness score is a fixed weighting of the four maintenance signals, not
// a function of the counts: a campaign is ready when it has a DM, a party, a
// scheduled session and something to do, and the magnitudes of those piles do
// not make it any readier.
const (
	readinessBase   = 25 // awarded to any campaign that exists at all
	readinessSignal = 15 // per satisfied signal; 25 + 4*15 = 100 - 15 = 85 at full
)

// campaignSignals is the shared basis of both endpoints. Field order is the
// order the signals are reported and the order names appear in "missing".
type campaignSignals struct {
	HasDM          bool `json:"has_dm"`
	HasCharacters  bool `json:"has_characters"`
	HasNextSession bool `json:"has_next_session"`
	HasActiveQuest bool `json:"has_active_quest"`
}

// each pairs every signal with the name it is reported under, so the score, the
// signals object and the missing list cannot drift apart.
func (s campaignSignals) each() []struct {
	name string
	set  bool
} {
	return []struct {
		name string
		set  bool
	}{
		{"has_dm", s.HasDM},
		{"has_characters", s.HasCharacters},
		{"has_next_session", s.HasNextSession},
		{"has_active_quest", s.HasActiveQuest},
	}
}

// satisfied counts the signals that hold.
func (s campaignSignals) satisfied() int {
	n := 0
	for _, signal := range s.each() {
		if signal.set {
			n++
		}
	}
	return n
}

// campaignMetrics is everything both endpoints need from the database, read in
// one place so the two documents can never disagree about the same campaign.
type campaignMetrics struct {
	openQuests        int
	friendlyNPCs      int
	scheduledSessions int
	inventoryItems    int
	characters        int
	dm                string
}

func (m campaignMetrics) signals() campaignSignals {
	return campaignSignals{
		HasDM:          m.dm != "",
		HasCharacters:  m.characters > 0,
		HasNextSession: m.scheduledSessions > 0,
		HasActiveQuest: m.openQuests > 0,
	}
}

// readCampaignMetrics loads one campaign's aggregates, reporting sql.ErrNoRows
// when the campaign does not exist. Callers must already hold storeMu.
func readCampaignMetrics(campaignID string) (campaignMetrics, error) {
	var out campaignMetrics
	if err := db.QueryRow(
		`SELECT dm FROM campaigns WHERE id = ?`, campaignID,
	).Scan(&out.dm); err != nil {
		return out, err
	}
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = ?`,
		campaignID, questActive,
	).Scan(&out.openQuests); err != nil {
		return out, err
	}
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0`, campaignID,
	).Scan(&out.friendlyNPCs); err != nil {
		return out, err
	}
	for _, part := range []struct {
		table string
		into  *int
	}{
		{`campaign_sessions`, &out.scheduledSessions},
		{`campaign_inventory`, &out.inventoryItems},
		{`campaign_characters`, &out.characters},
	} {
		n, err := countCampaignRows(part.table, campaignID)
		if err != nil {
			return out, err
		}
		*part.into = n
	}
	return out, nil
}

// loadCampaignMetrics reads the metrics and writes the response itself on any
// failure, so a handler only has to check ok. Callers must already hold storeMu.
func loadCampaignMetrics(w http.ResponseWriter, campaignID, context string) (campaignMetrics, bool) {
	metrics, err := readCampaignMetrics(campaignID)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeError(w, http.StatusNotFound, "campaign not found")
			return metrics, false
		}
		writeStorageFailure(w, context, err)
		return metrics, false
	}
	return metrics, true
}

// ---------- GET /v1/campaigns/{id}/analytics/summary ----------

type analyticsSummaryResponse struct {
	CampaignID        string `json:"campaign_id"`
	ReadinessScore    int    `json:"readiness_score"`
	OpenQuests        int    `json:"open_quests"`
	FriendlyNPCs      int    `json:"friendly_npcs"`
	ScheduledSessions int    `json:"scheduled_sessions"`
	InventoryItems    int    `json:"inventory_items"`
}

func handleCampaignAnalyticsSummary(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	metrics, ok := loadCampaignMetrics(w, campaignID, "analytics summary failed")
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, analyticsSummaryResponse{
		CampaignID:        campaignID,
		ReadinessScore:    readinessBase + readinessSignal*metrics.signals().satisfied(),
		OpenQuests:        metrics.openQuests,
		FriendlyNPCs:      metrics.friendlyNPCs,
		ScheduledSessions: metrics.scheduledSessions,
		InventoryItems:    metrics.inventoryItems,
	})
}

// ---------- POST /v1/campaigns/{id}/analytics/risk-report ----------

// riskReportRequest has no required fields: a report over stored state needs no
// input. include_zeroes defaults to true and decides whether the unsatisfied
// signals are enumerated in "missing" or merely reflected in risk_level.
type riskReportRequest struct {
	IncludeZeroes *bool `json:"include_zeroes"`
}

type riskReportResponse struct {
	CampaignID string          `json:"campaign_id"`
	RiskLevel  string          `json:"risk_level"`
	Missing    []string        `json:"missing"`
	Signals    campaignSignals `json:"signals"`
}

// Risk rises with the number of unsatisfied signals, independent of
// include_zeroes: suppressing the list does not suppress the finding.
const (
	riskLow    = "low"
	riskMedium = "medium"
	riskHigh   = "high"
)

func riskLevel(missing int) string {
	switch {
	case missing == 0:
		return riskLow
	case missing <= 2:
		return riskMedium
	default:
		return riskHigh
	}
}

func handleCampaignAnalyticsRiskReport(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	// An absent body is as valid as {}: every field is optional.
	var req riskReportRequest
	if r.ContentLength == 0 {
		if !requireMethod(w, r, http.MethodPost) {
			return
		}
	} else if !decodeBody(w, r, &req) {
		return
	}
	includeZeroes := req.IncludeZeroes == nil || *req.IncludeZeroes

	storeMu.Lock()
	defer storeMu.Unlock()

	metrics, ok := loadCampaignMetrics(w, campaignID, "analytics risk report failed")
	if !ok {
		return
	}
	signals := metrics.signals()

	// Non-nil so an unproblematic campaign renders [] rather than null.
	missing := []string{}
	unsatisfied := 0
	for _, signal := range signals.each() {
		if signal.set {
			continue
		}
		unsatisfied++
		if includeZeroes {
			missing = append(missing, signal.name)
		}
	}
	writeJSON(w, http.StatusOK, riskReportResponse{
		CampaignID: campaignID,
		RiskLevel:  riskLevel(unsatisfied),
		Missing:    missing,
		Signals:    signals,
	})
}
