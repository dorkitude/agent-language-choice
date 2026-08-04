package main

import (
	"database/sql"
	"errors"
	"log"
	"net/http"
	"strings"
)

// Quests are a third ordered child of a campaign, alongside the roster and the
// event log. A quest owns a list of milestones; progress is recorded by naming
// the milestones that are now finished, and the counts in every response are
// derived from the milestone rows rather than stored separately.
//
// Milestones keep an insert-time position like the other child tables so a
// quest replays its milestones in the order the DM wrote them.

// Quest status values. Anything outside this set is a 400 on write, and the
// summary counts exactly these three buckets.
const (
	questActive    = "active"
	questCompleted = "completed"
	questBlocked   = "blocked"
)

func validQuestStatus(status string) bool {
	switch status {
	case questActive, questCompleted, questBlocked:
		return true
	}
	return false
}

// ---------- POST /v1/campaigns/{id}/quests ----------

type questRequest struct {
	ID         *string  `json:"id"`
	Title      *string  `json:"title"`
	Status     *string  `json:"status"`
	Milestones []string `json:"milestones"`
}

type questResponse struct {
	ID              string `json:"id"`
	Title           string `json:"title"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

func handleCampaignQuests(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req questRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	title, ok := requireField(w, req.Title, "title")
	if !ok {
		return
	}
	status := questActive
	if req.Status != nil {
		status = strings.TrimSpace(*req.Status)
		if !validQuestStatus(status) {
			writeError(w, http.StatusBadRequest, "status is invalid")
			return
		}
	}
	// Blank entries would be unaddressable by the progress endpoint, so they are
	// dropped rather than counted toward the total.
	milestones := make([]string, 0, len(req.Milestones))
	for _, name := range req.Milestones {
		if trimmed := strings.TrimSpace(name); trimmed != "" {
			milestones = append(milestones, trimmed)
		}
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "quest lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "quest id already exists")
		return
	}

	position, err := nextPosition(`campaign_quests`, campaignID)
	if err != nil {
		writeStorageFailure(w, "quest position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_quests (campaign_id, id, position, title, status) VALUES (?, ?, ?, ?, ?)`,
		campaignID, id, position, title, status,
	); err != nil {
		log.Printf("quest insert failed: %v", err)
		writeError(w, http.StatusConflict, "quest id already exists")
		return
	}
	// A repeated milestone name is stored once: progress addresses milestones by
	// name, so duplicates could never be told apart.
	seen := make(map[string]bool, len(milestones))
	next := 1
	for _, name := range milestones {
		if seen[name] {
			continue
		}
		seen[name] = true
		if _, err := db.Exec(
			`INSERT INTO campaign_quest_milestones (campaign_id, quest_id, position, name, done)
			 VALUES (?, ?, ?, ?, 0)`,
			campaignID, id, next, name,
		); err != nil {
			writeStorageFailure(w, "milestone insert failed", err)
			return
		}
		next++
	}

	writeJSON(w, http.StatusCreated, questResponse{
		ID:              id,
		Title:           title,
		Status:          status,
		MilestonesTotal: len(seen),
		MilestonesDone:  0,
	})
}

// ---------- POST /v1/campaigns/{id}/quests/{quest_id}/progress ----------

type questProgressRequest struct {
	Completed []string `json:"completed"`
	Status    *string  `json:"status"`
}

// questProgressResponse drops the title: the caller already knows it, and the
// interesting part of a progress write is the status and the counts.
type questProgressResponse struct {
	ID              string `json:"id"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

func handleCampaignQuestProgress(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	questID, ok := requirePathValue(w, r, "quest_id", "quest id")
	if !ok {
		return
	}
	var req questProgressRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Status != nil && !validQuestStatus(strings.TrimSpace(*req.Status)) {
		writeError(w, http.StatusBadRequest, "status is invalid")
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	var status string
	err := db.QueryRow(
		`SELECT status FROM campaign_quests WHERE campaign_id = ? AND id = ?`, campaignID, questID,
	).Scan(&status)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "quest read failed", err)
		return
	}

	// Marking an already-done milestone, or a name this quest does not have, is a
	// no-op: replaying a progress call must not change the counts.
	for _, name := range req.Completed {
		trimmed := strings.TrimSpace(name)
		if trimmed == "" {
			continue
		}
		if _, err := db.Exec(
			`UPDATE campaign_quest_milestones SET done = 1
			 WHERE campaign_id = ? AND quest_id = ? AND name = ?`,
			campaignID, questID, trimmed,
		); err != nil {
			writeStorageFailure(w, "milestone update failed", err)
			return
		}
	}

	total, done, err := milestoneCounts(campaignID, questID)
	if err != nil {
		writeStorageFailure(w, "milestone count failed", err)
		return
	}

	// An explicit status wins; otherwise finishing every milestone completes the
	// quest on its own. A blocked quest stays blocked until the caller says
	// otherwise, so only an active quest auto-completes.
	switch {
	case req.Status != nil:
		status = strings.TrimSpace(*req.Status)
	case status == questActive && total > 0 && done == total:
		status = questCompleted
	}
	if _, err := db.Exec(
		`UPDATE campaign_quests SET status = ? WHERE campaign_id = ? AND id = ?`,
		status, campaignID, questID,
	); err != nil {
		writeStorageFailure(w, "quest update failed", err)
		return
	}

	writeJSON(w, http.StatusOK, questProgressResponse{
		ID:              questID,
		Status:          status,
		MilestonesTotal: total,
		MilestonesDone:  done,
	})
}

// ---------- GET /v1/campaigns/{id}/quests/summary ----------

type questSummaryResponse struct {
	CampaignID string `json:"campaign_id"`
	Active     int    `json:"active"`
	Completed  int    `json:"completed"`
	Blocked    int    `json:"blocked"`
}

func handleCampaignQuestSummary(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	out := questSummaryResponse{CampaignID: campaignID}
	rows, err := db.Query(
		`SELECT status, COUNT(*) FROM campaign_quests WHERE campaign_id = ? GROUP BY status`, campaignID,
	)
	if err != nil {
		writeStorageFailure(w, "quest summary failed", err)
		return
	}
	defer rows.Close()
	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			writeStorageFailure(w, "quest summary scan failed", err)
			return
		}
		switch status {
		case questActive:
			out.Active = count
		case questCompleted:
			out.Completed = count
		case questBlocked:
			out.Blocked = count
		}
	}
	if err := rows.Err(); err != nil {
		writeStorageFailure(w, "quest summary failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// ---------- shared helpers ----------

// milestoneCounts returns the quest's total and finished milestone counts.
// Callers must already hold storeMu.
func milestoneCounts(campaignID, questID string) (total, done int, err error) {
	err = db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(done), 0) FROM campaign_quest_milestones
		 WHERE campaign_id = ? AND quest_id = ?`, campaignID, questID,
	).Scan(&total, &done)
	return total, done, err
}
