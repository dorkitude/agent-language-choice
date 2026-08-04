package main

import (
	"net/http"
	"sync"
)

// moderationReport is an immutable campaign moderation report, resolvable
// exactly once by the campaign dm.
type moderationReport struct {
	CampaignID string
	ReportID   string
	TargetID   string
	Reason     string
	Status     string
	Reporter   string
	Sequence   int
	Action     string
	Note       string
	Resolver   string
}

// moderationReportsMu guards moderationReports, the in-memory index
// mirroring the play_moderation_reports table. Keyed by campaign id, holding
// reports in append order.
var (
	moderationReportsMu sync.Mutex
	moderationReports    = map[string][]*moderationReport{}
)

func moderationReportJSON(rep *moderationReport) map[string]any {
	out := map[string]any{
		"report_id": rep.ReportID,
		"target_id": rep.TargetID,
		"reason":    rep.Reason,
		"status":    rep.Status,
		"reporter":  rep.Reporter,
		"sequence":  rep.Sequence,
	}
	if rep.Status == "resolved" {
		out["action"] = rep.Action
		out["note"] = rep.Note
		out["resolver"] = rep.Resolver
	}
	return out
}

// findModerationReport returns the report with the given id in campaignID,
// or nil. Callers must already hold moderationReportsMu.
func findModerationReport(campaignID, reportID string) *moderationReport {
	for _, rep := range moderationReports[campaignID] {
		if rep.ReportID == reportID {
			return rep
		}
	}
	return nil
}

type createModerationReportRequest struct {
	ReportID string `json:"report_id"`
	TargetID string `json:"target_id"`
	Reason   string `json:"reason"`
}

// createModerationReportHandler lets any authenticated campaign member,
// including the dm, submit a moderation report.
func createModerationReportHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createModerationReportRequest
	if !decodeJSONBody(w, r, &req) {
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

	if req.ReportID == "" || req.TargetID == "" || req.Reason == "" {
		writeError(w, http.StatusBadRequest, "report_id, target_id, and reason are required nonempty strings")
		return
	}

	moderationReportsMu.Lock()
	defer moderationReportsMu.Unlock()

	if findModerationReport(campaignID, req.ReportID) != nil {
		writeError(w, http.StatusConflict, "report_id already exists in this campaign")
		return
	}

	sequence := len(moderationReports[campaignID]) + 1
	rep := &moderationReport{
		CampaignID: campaignID,
		ReportID:   req.ReportID,
		TargetID:   req.TargetID,
		Reason:     req.Reason,
		Status:     "open",
		Reporter:   actor.Username,
		Sequence:   sequence,
	}
	if err := saveModerationReportToDB(rep); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save moderation report")
		return
	}
	moderationReports[campaignID] = append(moderationReports[campaignID], rep)

	writeJSON(w, http.StatusCreated, moderationReportJSON(rep))
}

// listModerationReportsHandler returns a campaign's moderation reports in
// stable append order. Any authenticated campaign member, including the dm,
// may call this.
func listModerationReportsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	moderationReportsMu.Lock()
	defer moderationReportsMu.Unlock()

	reports := make([]map[string]any, 0, len(moderationReports[campaignID]))
	for _, rep := range moderationReports[campaignID] {
		reports = append(reports, moderationReportJSON(rep))
	}

	writeJSON(w, http.StatusOK, map[string]any{"reports": reports})
}

type resolveModerationReportRequest struct {
	Action string `json:"action"`
	Note   string `json:"note"`
}

// resolveModerationReportHandler lets only the campaign dm resolve an open
// moderation report exactly once.
func resolveModerationReportHandler(w http.ResponseWriter, r *http.Request, campaignID, reportID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req resolveModerationReportRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may resolve moderation reports")
		return
	}

	moderationReportsMu.Lock()
	defer moderationReportsMu.Unlock()

	rep := findModerationReport(campaignID, reportID)
	if rep == nil {
		writeError(w, http.StatusNotFound, "unknown moderation report id")
		return
	}

	if req.Action != "allow" && req.Action != "remove" {
		writeError(w, http.StatusBadRequest, "action must be exactly allow or remove")
		return
	}
	if req.Note == "" {
		writeError(w, http.StatusBadRequest, "note must be a nonempty string")
		return
	}

	if rep.Status == "resolved" {
		writeError(w, http.StatusConflict, "moderation report has already been resolved")
		return
	}

	rep.Status = "resolved"
	rep.Action = req.Action
	rep.Note = req.Note
	rep.Resolver = actor.Username
	if err := saveModerationReportToDB(rep); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save moderation report")
		return
	}

	writeJSON(w, http.StatusOK, moderationReportJSON(rep))
}
