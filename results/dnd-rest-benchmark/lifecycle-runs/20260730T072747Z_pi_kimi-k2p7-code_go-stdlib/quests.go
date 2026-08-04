package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// questCreateRequest is the payload for creating a campaign quest.
type questCreateRequest struct {
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Status     string   `json:"status"`
	Milestones []string `json:"milestones"`
}

// questCreateResponse is returned when a quest is created. It mirrors the
// request but replaces the milestone list with aggregate counts.
type questCreateResponse struct {
	ID              string `json:"id"`
	Title           string `json:"title"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

// questProgressRequest marks specific milestones as completed.
type questProgressRequest struct {
	Completed []string `json:"completed"`
}

// questProgressResponse reports the current milestone tally after an update.
type questProgressResponse struct {
	ID              string `json:"id"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

// questSummary aggregates quest counts by status for a campaign.
type questSummary struct {
	CampaignID string `json:"campaign_id"`
	Active     int    `json:"active"`
	Completed  int    `json:"completed"`
	Blocked    int    `json:"blocked"`
}

// validQuestStatus limits the status values used by the summary endpoint.
func validQuestStatus(s string) bool {
	switch s {
	case "active", "completed", "blocked":
		return true
	}
	return false
}

// queryQuestExists returns true when a quest with the given ID exists.
func queryQuestExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM quests WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// questMilestoneCounts returns the total and completed milestone counts for a quest.
func questMilestoneCounts(questID string) (total, done int, err error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS total FROM quest_milestones WHERE quest_id=%s;", sq(questID)))
	if err != nil {
		return 0, 0, err
	}
	var totals []struct {
		Total int `json:"total"`
	}
	if err := json.Unmarshal(out, &totals); err != nil {
		return 0, 0, err
	}
	if len(totals) > 0 {
		total = totals[0].Total
	}

	out, err = dbQuery(fmt.Sprintf("SELECT COUNT(*) AS done FROM quest_milestones WHERE quest_id=%s AND done=1;", sq(questID)))
	if err != nil {
		return 0, 0, err
	}
	var dones []struct {
		Done int `json:"done"`
	}
	if err := json.Unmarshal(out, &dones); err != nil {
		return 0, 0, err
	}
	if len(dones) > 0 {
		done = dones[0].Done
	}
	return total, done, nil
}

// createQuestHandler creates a quest with its milestones under a campaign.
func createQuestHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req questCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Title == "" || req.Status == "" || !validQuestStatus(req.Status) {
		writeError(w, http.StatusBadRequest, "invalid quest")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("create quest campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	dup, err := queryQuestExists(req.ID)
	if err != nil {
		log.Printf("create quest duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "quest already exists")
		return
	}

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("INSERT INTO quests (id, campaign_id, title, status) VALUES (%s, %s, %s, %s);",
		sq(req.ID), sq(campaignID), sq(req.Title), sq(req.Status)))
	for _, m := range req.Milestones {
		sb.WriteString(fmt.Sprintf("INSERT INTO quest_milestones (quest_id, label, done) VALUES (%s, %s, 0);",
			sq(req.ID), sq(m)))
	}
	if err := dbExec(sb.String()); err != nil {
		log.Printf("create quest insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	total, done, err := questMilestoneCounts(req.ID)
	if err != nil {
		log.Printf("create quest milestone counts error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, questCreateResponse{
		ID:              req.ID,
		Title:           req.Title,
		Status:          req.Status,
		MilestonesTotal: total,
		MilestonesDone:  done,
	})
}

// updateQuestProgressHandler marks requested milestones as completed for a quest.
func updateQuestProgressHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	questID := r.PathValue("quest_id")

	var req questProgressRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	out, err := dbQuery(fmt.Sprintf("SELECT id, status FROM quests WHERE id=%s AND campaign_id=%s LIMIT 1;",
		sq(questID), sq(campaignID)))
	if err != nil {
		log.Printf("update quest progress query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var quests []struct {
		ID     string `json:"id"`
		Status string `json:"status"`
	}
	if err := json.Unmarshal(out, &quests); err != nil {
		log.Printf("update quest progress unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(quests) == 0 {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	status := quests[0].Status

	if len(req.Completed) > 0 {
		parts := make([]string, len(req.Completed))
		for i, m := range req.Completed {
			parts[i] = sq(m)
		}
		sql := fmt.Sprintf("UPDATE quest_milestones SET done=1 WHERE quest_id=%s AND label IN (%s);",
			sq(questID), strings.Join(parts, ", "))
		if err := dbExec(sql); err != nil {
			log.Printf("update quest progress error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	total, done, err := questMilestoneCounts(questID)
	if err != nil {
		log.Printf("update quest progress counts error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, questProgressResponse{
		ID:              questID,
		Status:          status,
		MilestonesTotal: total,
		MilestonesDone:  done,
	})
}

// getQuestSummaryHandler returns the count of quests by status for a campaign.
func getQuestSummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("quest summary campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT status, COUNT(*) AS count FROM quests WHERE campaign_id=%s GROUP BY status;", sq(campaignID)))
	if err != nil {
		log.Printf("quest summary query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		Status string `json:"status"`
		Count  int    `json:"count"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("quest summary unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	summary := questSummary{CampaignID: campaignID}
	for _, row := range rows {
		switch row.Status {
		case "active":
			summary.Active = row.Count
		case "completed":
			summary.Completed = row.Count
		case "blocked":
			summary.Blocked = row.Count
		}
	}

	writeJSON(w, http.StatusOK, summary)
}
