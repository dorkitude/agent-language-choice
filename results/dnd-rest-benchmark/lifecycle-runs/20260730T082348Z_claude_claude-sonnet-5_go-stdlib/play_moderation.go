package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playModerationReport is an immutable (except for one open->resolved
// transition) campaign-scoped moderation report record.
type playModerationReport struct {
	ReportID string
	TargetID string
	Reason   string
	Status   string
	Reporter string
	Sequence int

	Action   string
	Note     string
	Resolver string
}

func playModerationReportResponse(rep *playModerationReport) map[string]interface{} {
	resp := map[string]interface{}{
		"report_id": rep.ReportID,
		"target_id": rep.TargetID,
		"reason":    rep.Reason,
		"status":    rep.Status,
		"reporter":  rep.Reporter,
		"sequence":  rep.Sequence,
	}
	if rep.Status == "resolved" {
		resp["action"] = rep.Action
		resp["note"] = rep.Note
		resp["resolver"] = rep.Resolver
	}
	return resp
}

// handlePlayCampaignModerationSub routes the "moderation/reports" and
// "moderation/reports/{report_id}/resolution" sub-paths of a play campaign.
// It returns false if rest does not name a moderation path, so the caller
// can fall through to its own routing.
func handlePlayCampaignModerationSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "moderation/reports" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayModerationReport(w, r, campaignID)
		case http.MethodGet:
			handleListPlayModerationReports(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}

	if repRest, ok := strings.CutPrefix(rest, "moderation/reports/"); ok && repRest != "" {
		if reportID, ok := strings.CutSuffix(repRest, "/resolution"); ok && reportID != "" {
			if r.Method != http.MethodPut {
				writeError(w, http.StatusMethodNotAllowed, "method not allowed")
				return true
			}
			handleResolvePlayModerationReport(w, r, campaignID, reportID)
			return true
		}
	}

	return false
}

func handleCreatePlayModerationReport(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ReportID string `json:"report_id"`
		TargetID string `json:"target_id"`
		Reason   string `json:"reason"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ReportID == "" || req.TargetID == "" || req.Reason == "" {
		writeError(w, http.StatusBadRequest, "report_id, target_id, and reason are required")
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
	if c.ModerationReportIDs != nil && c.ModerationReportIDs[req.ReportID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "report_id already used in this campaign")
		return
	}

	c.ModerationReportSeq++
	entry := &playModerationReport{
		ReportID: req.ReportID,
		TargetID: req.TargetID,
		Reason:   req.Reason,
		Status:   "open",
		Reporter: username,
		Sequence: c.ModerationReportSeq,
	}
	c.ModerationReports = append(c.ModerationReports, entry)
	if c.ModerationReportIDs == nil {
		c.ModerationReportIDs = make(map[string]bool)
	}
	c.ModerationReportIDs[req.ReportID] = true
	resp := playModerationReportResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleListPlayModerationReports(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	reports := make([]map[string]interface{}, 0, len(c.ModerationReports))
	for _, rep := range c.ModerationReports {
		reports = append(reports, playModerationReportResponse(rep))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"reports": reports})
}

func handleResolvePlayModerationReport(w http.ResponseWriter, r *http.Request, campaignID, reportID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Action string `json:"action"`
		Note   string `json:"note"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Action != "allow" && req.Action != "remove" {
		writeError(w, http.StatusBadRequest, "action must be allow or remove")
		return
	}
	if req.Note == "" {
		writeError(w, http.StatusBadRequest, "note is required")
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

	var target *playModerationReport
	for _, rep := range c.ModerationReports {
		if rep.ReportID == reportID {
			target = rep
			break
		}
	}
	if target == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "moderation report not found")
		return
	}
	if target.Status == "resolved" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "moderation report already resolved")
		return
	}

	target.Status = "resolved"
	target.Action = req.Action
	target.Note = req.Note
	target.Resolver = username
	resp := playModerationReportResponse(target)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}
