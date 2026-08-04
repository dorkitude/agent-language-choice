package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// Campaign quest tracking: quests hang off a campaign, carry an ordered
// milestone checklist, and record which milestones are done.
//
// A quest owns two parallel slices: Milestones (the checklist text, in the
// order supplied) and Done (one flag per milestone). Keeping them parallel —
// rather than a set of completed titles — means duplicate milestone text stays
// countable, since each entry is ticked off independently.
//
// Like the rest of the campaign state, quests live in memory under
// campaigns.mu and are mirrored to SQLite by flush().

// Quest lifecycle statuses. A quest may be created in any of them, and reaching
// the last milestone promotes an active quest to completed.
const (
	questActive    = "active"
	questCompleted = "completed"
	questBlocked   = "blocked"
)

// questStatuses is the accepted set, listed in summary-response order.
var questStatuses = []string{questActive, questCompleted, questBlocked}

func validQuestStatus(s string) bool {
	for _, known := range questStatuses {
		if s == known {
			return true
		}
	}
	return false
}

type quest struct {
	ID         string
	Title      string
	Status     string
	Milestones []string
	Done       []bool
}

// doneCount reports how many milestones are ticked off.
func (q *quest) doneCount() int {
	n := 0
	for _, d := range q.Done {
		if d {
			n++
		}
	}
	return n
}

// complete marks the first not-yet-done milestone whose text equals name,
// reporting whether such a milestone exists at all. Re-completing an already
// finished milestone is a no-op success, so replayed progress calls are
// idempotent.
func (q *quest) complete(name string) bool {
	found := false
	for i, m := range q.Milestones {
		if m != name {
			continue
		}
		found = true
		if !q.Done[i] {
			q.Done[i] = true
			return true
		}
	}
	return found
}

// settle promotes an active quest to completed once every milestone is done. A
// blocked or already-completed quest keeps its status, and a quest with no
// milestones is never auto-completed.
func (q *quest) settle() {
	if q.Status != questActive || len(q.Milestones) == 0 {
		return
	}
	if q.doneCount() == len(q.Milestones) {
		q.Status = questCompleted
	}
}

// find returns the campaign's quest with the given id. Callers must hold
// campaigns.mu.
func findQuest(c *campaign, id string) *quest {
	for _, q := range c.Quests {
		if q.ID == id {
			return q
		}
	}
	return nil
}

// ---------- request / response payloads ----------

type questRequest struct {
	ID         *string   `json:"id"`
	Title      *string   `json:"title"`
	Status     *string   `json:"status"`
	Milestones *[]string `json:"milestones"`
}

type questResponse struct {
	ID              string `json:"id"`
	Title           string `json:"title"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

type questProgressRequest struct {
	Completed *[]string `json:"completed"`
	Status    *string   `json:"status"`
}

type questProgressResponse struct {
	ID              string `json:"id"`
	Status          string `json:"status"`
	MilestonesTotal int    `json:"milestones_total"`
	MilestonesDone  int    `json:"milestones_done"`
}

type questSummaryResponse struct {
	CampaignID string `json:"campaign_id"`
	Active     int    `json:"active"`
	Completed  int    `json:"completed"`
	Blocked    int    `json:"blocked"`
}

// ---------- POST /v1/campaigns/{id}/quests ----------

func handleCreateQuest(w http.ResponseWriter, r *http.Request) {
	var req questRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	title, ok := requiredString(req.Title)
	if !ok {
		writeError(w, http.StatusBadRequest, "title is required")
		return
	}
	status, ok := requiredString(req.Status)
	if !ok {
		writeError(w, http.StatusBadRequest, "status is required")
		return
	}
	status = strings.ToLower(status)
	if !validQuestStatus(status) {
		writeError(w, http.StatusBadRequest, "status must be active, completed, or blocked")
		return
	}
	// Milestones are optional; an omitted list simply means a quest with
	// nothing to tick off yet. A present list must hold non-blank strings.
	milestones := []string{}
	if req.Milestones != nil {
		for _, m := range *req.Milestones {
			m = strings.TrimSpace(m)
			if m == "" {
				writeError(w, http.StatusBadRequest, "milestones must be non-empty strings")
				return
			}
			milestones = append(milestones, m)
		}
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if findQuest(c, id) != nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "quest id already exists")
		return
	}
	q := &quest{
		ID:         id,
		Title:      title,
		Status:     status,
		Milestones: milestones,
		Done:       make([]bool, len(milestones)),
	}
	c.Quests = append(c.Quests, q)
	resp := questResponse{
		ID:              q.ID,
		Title:           q.Title,
		Status:          q.Status,
		MilestonesTotal: len(q.Milestones),
		MilestonesDone:  q.doneCount(),
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/campaigns/{id}/quests/{quest_id}/progress ----------

func handleQuestProgress(w http.ResponseWriter, r *http.Request) {
	var req questProgressRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Completed == nil {
		writeError(w, http.StatusBadRequest, "completed is required")
		return
	}
	// An explicit status is optional and lets a quest be blocked or reopened
	// without touching its checklist.
	status := ""
	if req.Status != nil {
		s, ok := requiredString(req.Status)
		if !ok {
			writeError(w, http.StatusBadRequest, "status must not be blank")
			return
		}
		status = strings.ToLower(s)
		if !validQuestStatus(status) {
			writeError(w, http.StatusBadRequest, "status must be active, completed, or blocked")
			return
		}
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	q := findQuest(c, r.PathValue("quest_id"))
	if q == nil {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	// Validate the whole batch before applying any of it, so a bad name cannot
	// leave the quest half-updated.
	names := make([]string, 0, len(*req.Completed))
	for _, name := range *req.Completed {
		name = strings.TrimSpace(name)
		if name == "" {
			campaigns.mu.Unlock()
			writeError(w, http.StatusBadRequest, "completed must be non-empty strings")
			return
		}
		known := false
		for _, m := range q.Milestones {
			if m == name {
				known = true
				break
			}
		}
		if !known {
			campaigns.mu.Unlock()
			writeError(w, http.StatusBadRequest, "unknown milestone")
			return
		}
		names = append(names, name)
	}
	for _, name := range names {
		q.complete(name)
	}
	if status != "" {
		q.Status = status
	}
	q.settle()
	resp := questProgressResponse{
		ID:              q.ID,
		Status:          q.Status,
		MilestonesTotal: len(q.Milestones),
		MilestonesDone:  q.doneCount(),
	}
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// ---------- GET /v1/campaigns/{id}/quests/summary ----------

func handleQuestSummary(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	resp := questSummaryResponse{CampaignID: c.ID}
	for _, q := range c.Quests {
		switch q.Status {
		case questActive:
			resp.Active++
		case questCompleted:
			resp.Completed++
		case questBlocked:
			resp.Blocked++
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

// ---------- persistence helpers ----------

// questRows renders one campaign's quests as storage rows. Milestone text and
// the done flags are JSON-encoded because the writer only handles flat columns.
// Callers must hold campaigns.mu.
func questRows(c *campaign) [][]any {
	out := make([][]any, 0, len(c.Quests))
	for i, q := range c.Quests {
		milestones, _ := json.Marshal(q.Milestones)
		done, _ := json.Marshal(q.Done)
		out = append(out, []any{
			c.ID, q.ID, q.Title, q.Status, string(milestones), string(done), int64(i),
		})
	}
	return out
}

// questFromRow rebuilds a quest from a storage row, returning the owning
// campaign id. A row whose flag list disagrees with its milestone list is
// rejected, since the two must stay parallel.
func questFromRow(row []any) (campaignID string, q *quest, ok bool) {
	if len(row) < 6 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	id, _ := row[1].(string)
	title, _ := row[2].(string)
	status, _ := row[3].(string)
	milestonesJSON, _ := row[4].(string)
	doneJSON, _ := row[5].(string)
	if campaignID == "" || id == "" || !validQuestStatus(status) {
		return "", nil, false
	}
	milestones := []string{}
	_ = json.Unmarshal([]byte(milestonesJSON), &milestones)
	done := []bool{}
	_ = json.Unmarshal([]byte(doneJSON), &done)
	if len(done) != len(milestones) {
		return "", nil, false
	}
	return campaignID, &quest{
		ID:         id,
		Title:      title,
		Status:     status,
		Milestones: milestones,
		Done:       done,
	}, true
}
