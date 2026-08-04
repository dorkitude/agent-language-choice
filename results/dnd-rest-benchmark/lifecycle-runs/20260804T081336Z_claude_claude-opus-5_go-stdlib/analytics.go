package main

import (
	"errors"
	"io"
	"net/http"
)

// Campaign analytics: read-only aggregations over everything the campaign has
// accumulated across earlier stages.
//
// Like audit.go, nothing here mutates state or calls flush(). Every number is
// derived from the in-memory slices, whose contents and order survive a
// restart unchanged, so repeated calls answer identically.

// Readiness weights. A campaign earns points for each preparedness signal it
// satisfies; the weights are fixed so the score is a pure function of state.
// They sum to readinessMax, which is what a fully prepared campaign scores.
const (
	readinessDM          = 25
	readinessCharacters  = 25
	readinessNextSession = 20
	readinessActiveQuest = 15

	readinessMax = readinessDM + readinessCharacters + readinessNextSession + readinessActiveQuest
)

// Risk levels, ordered least to most severe. The level is a function of how
// many readiness signals are absent, so it never disagrees with `missing`.
const (
	riskLow    = "low"
	riskMedium = "medium"
	riskHigh   = "high"
)

// signalNames are the names reported in `missing`, listed in the same order as
// the signals object so the two read together.
var signalNames = []string{"dm", "characters", "next_session", "active_quest"}

type analyticsSignals struct {
	HasDM          bool `json:"has_dm"`
	HasCharacters  bool `json:"has_characters"`
	HasNextSession bool `json:"has_next_session"`
	HasActiveQuest bool `json:"has_active_quest"`
}

// campaignSignals evaluates the four readiness signals. Callers must hold
// campaigns.mu.
func campaignSignals(c *campaign) analyticsSignals {
	return analyticsSignals{
		HasDM:          c.DM != "",
		HasCharacters:  len(c.Characters) > 0,
		HasNextSession: nextCampaignSession(c) != nil,
		HasActiveQuest: openQuestCount(c) > 0,
	}
}

// values returns the signals in signalNames order.
func (s analyticsSignals) values() []bool {
	return []bool{s.HasDM, s.HasCharacters, s.HasNextSession, s.HasActiveQuest}
}

// score sums the weight of every satisfied signal.
func (s analyticsSignals) score() int {
	total := 0
	if s.HasDM {
		total += readinessDM
	}
	if s.HasCharacters {
		total += readinessCharacters
	}
	if s.HasNextSession {
		total += readinessNextSession
	}
	if s.HasActiveQuest {
		total += readinessActiveQuest
	}
	return total
}

// missing lists the names of the unsatisfied signals, always as a non-nil
// slice so the JSON field is [] rather than null.
func (s analyticsSignals) missing() []string {
	out := []string{}
	for i, ok := range s.values() {
		if !ok {
			out = append(out, signalNames[i])
		}
	}
	return out
}

// openQuestCount counts quests still being worked on. "Open" means active: a
// completed quest is finished and a blocked one is not something the party can
// currently pursue. Callers must hold campaigns.mu.
func openQuestCount(c *campaign) int {
	n := 0
	for _, q := range c.Quests {
		if q.Status == questActive {
			n++
		}
	}
	return n
}

// friendlyNPCCount counts NPCs with a positive disposition, matching the
// tally the relationships endpoint reports. Callers must hold campaigns.mu.
func friendlyNPCCount(c *campaign) int {
	n := 0
	for _, npc := range c.NPCs {
		if npc.friendly() {
			n++
		}
	}
	return n
}

type analyticsSummaryResponse struct {
	CampaignID        string `json:"campaign_id"`
	ReadinessScore    int    `json:"readiness_score"`
	OpenQuests        int    `json:"open_quests"`
	FriendlyNPCs      int    `json:"friendly_npcs"`
	ScheduledSessions int    `json:"scheduled_sessions"`
	InventoryItems    int    `json:"inventory_items"`
}

type riskReportRequest struct {
	IncludeZeroes *bool `json:"include_zeroes"`
}

type riskReportResponse struct {
	CampaignID string           `json:"campaign_id"`
	RiskLevel  string           `json:"risk_level"`
	Missing    []string         `json:"missing"`
	Signals    analyticsSignals `json:"signals"`
}

// ---------- GET /v1/campaigns/{id}/analytics/summary ----------

func handleAnalyticsSummary(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, analyticsSummaryResponse{
		CampaignID:        c.ID,
		ReadinessScore:    campaignSignals(c).score(),
		OpenQuests:        openQuestCount(c),
		FriendlyNPCs:      friendlyNPCCount(c),
		ScheduledSessions: len(c.Sessions),
		InventoryItems:    len(c.Inventory),
	})
}

// ---------- POST /v1/campaigns/{id}/analytics/risk-report ----------

func handleAnalyticsRiskReport(w http.ResponseWriter, r *http.Request) {
	// The body carries only presentation options, so an absent one is fine;
	// a malformed one is still rejected.
	var req riskReportRequest
	if err := decodeBody(r, &req); err != nil && !errors.Is(err, io.EOF) {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	// include_zeroes asks for the zero-valued signals to be spelled out. The
	// signals object already reports all four either way, so the flag only
	// documents intent; `missing` names the false ones unconditionally.
	signals := campaignSignals(c)
	writeJSON(w, http.StatusOK, riskReportResponse{
		CampaignID: c.ID,
		RiskLevel:  riskLevel(signals),
		Missing:    signals.missing(),
		Signals:    signals,
	})
}

// riskLevel grades a campaign by how many readiness signals it is missing.
func riskLevel(s analyticsSignals) string {
	switch len(s.missing()) {
	case 0:
		return riskLow
	case 1, 2:
		return riskMedium
	default:
		return riskHigh
	}
}
