package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// moderationReport is the durable record for a campaign-scoped moderation
// report. Open reports omit the action, note, and resolver fields; resolved
// reports include them.
type moderationReport struct {
	ReportID string `json:"report_id"`
	TargetID string `json:"target_id"`
	Reason   string `json:"reason"`
	Status   string `json:"status"`
	Reporter string `json:"reporter"`
	Sequence int    `json:"sequence"`
	Action   string `json:"action,omitempty"`
	Note     string `json:"note,omitempty"`
	Resolver string `json:"resolver,omitempty"`
}

// createModerationReportRequest binds the submit-moderation-report payload.
type createModerationReportRequest struct {
	ReportID string `json:"report_id"`
	TargetID string `json:"target_id"`
	Reason   string `json:"reason"`
}

// resolveModerationReportRequest binds the resolve-moderation-report payload.
type resolveModerationReportRequest struct {
	Action string `json:"action"`
	Note   string `json:"note"`
}

// moderationReportsResponse is the list returned by the read endpoint.
type moderationReportsResponse struct {
	Reports []moderationReport `json:"reports"`
}

// createModerationReportHandler lets any authenticated campaign member (or the
// campaign DM) submit a moderation report. Duplicate report IDs within the
// campaign return 409 without mutating state.
func createModerationReportHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	username, ok := requireCampaignMemberOrDM(w, r, campaignID)
	if !ok {
		return
	}

	var req createModerationReportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ReportID == "" || req.TargetID == "" || req.Reason == "" {
		writeError(w, http.StatusBadRequest, "invalid report")
		return
	}

	var dup []moderationReport
	if err := queryRows(fmt.Sprintf(
		"SELECT report_id FROM campaign_moderation_reports WHERE campaign_id=%s AND report_id=%s LIMIT 1;",
		sq(campaignID), sq(req.ReportID)), &dup); err != nil {
		log.Printf("moderation report duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(dup) > 0 {
		writeError(w, http.StatusConflict, "report already exists")
		return
	}

	nextSeq := 1
	out, err := dbQuery(fmt.Sprintf(
		"SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_moderation_reports WHERE campaign_id=%s;",
		sq(campaignID)))
	if err != nil {
		log.Printf("moderation report sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("moderation report sequence unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(rows) > 0 {
		nextSeq = rows[0].NextSeq
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT INTO campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (%s, %s, %s, %s, 'open', %s, %d);",
		sq(campaignID), sq(req.ReportID), sq(req.TargetID), sq(req.Reason), sq(username), nextSeq)); err != nil {
		log.Printf("moderation report insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, moderationReport{
		ReportID: req.ReportID,
		TargetID: req.TargetID,
		Reason:   req.Reason,
		Status:   "open",
		Reporter: username,
		Sequence: nextSeq,
	})
}

// listModerationReportsHandler lets authenticated campaign members (including
// the DM) read all moderation reports in stable append order.
func listModerationReportsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignMemberOrDM(w, r, campaignID); !ok {
		return
	}

	var reports []moderationReport
	if err := queryRows(fmt.Sprintf(
		"SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM campaign_moderation_reports WHERE campaign_id=%s ORDER BY sequence;",
		sq(campaignID)), &reports); err != nil {
		log.Printf("moderation reports list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if reports == nil {
		reports = []moderationReport{}
	}

	writeJSON(w, http.StatusOK, moderationReportsResponse{Reports: reports})
}

// requireCampaignMemberOrDM authenticates the request and authorizes only the
// campaign DM or a campaign member. Missing authentication returns 401, unknown
// campaigns return 404, and authenticated non-members return 403. This helper
// is used by the moderation workflow so that unknown-campaign checks take
// precedence over membership checks.
func requireCampaignMemberOrDM(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}

	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("moderation auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("moderation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", false
	}
	if campaign.Owner == username {
		return username, true
	}

	_, ok, err = queryPlayCampaignMemberByUsername(campaignID, username)
	if err != nil {
		log.Printf("moderation member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	return username, true
}

// resolveModerationReportHandler lets only the campaign DM resolve an open
// moderation report. Players receive 403, unknown reports 404, and re-resolving
// an already-resolved report returns 409.
func resolveModerationReportHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	reportID := r.PathValue("report_id")
	username, ok := requireCampaignOwner(w, r, campaignID)
	if !ok {
		return
	}

	var req resolveModerationReportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if (req.Action != "allow" && req.Action != "remove") || req.Note == "" {
		writeError(w, http.StatusBadRequest, "invalid resolution")
		return
	}

	var reports []moderationReport
	if err := queryRows(fmt.Sprintf(
		"SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM campaign_moderation_reports WHERE campaign_id=%s AND report_id=%s LIMIT 1;",
		sq(campaignID), sq(reportID)), &reports); err != nil {
		log.Printf("moderation report resolve query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(reports) == 0 {
		writeError(w, http.StatusNotFound, "report not found")
		return
	}
	report := reports[0]
	if report.Status != "open" {
		writeError(w, http.StatusConflict, "report already resolved")
		return
	}

	if err := dbExec(fmt.Sprintf(
		"UPDATE campaign_moderation_reports SET status='resolved', action=%s, note=%s, resolver=%s WHERE campaign_id=%s AND report_id=%s;",
		sq(req.Action), sq(req.Note), sq(username), sq(campaignID), sq(reportID))); err != nil {
		log.Printf("moderation report resolve update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	report.Status = "resolved"
	report.Action = req.Action
	report.Note = req.Note
	report.Resolver = username

	writeJSON(w, http.StatusOK, report)
}
