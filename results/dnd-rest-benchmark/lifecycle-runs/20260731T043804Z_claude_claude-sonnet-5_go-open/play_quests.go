package main

import (
	"net/http"
	"sync"
)

// playQuest is a campaign quest record whose activation is gated by
// completed prerequisite quests.
type playQuest struct {
	CampaignID string             `json:"-"`
	QuestID    string             `json:"quest_id"`
	Title      string             `json:"title"`
	DependsOn  []string           `json:"depends_on"`
	State      string             `json:"state"`
	Rewards    *questRewardConfig `json:"-"`
}

// campaignQuestsMu guards campaignQuests, the in-memory index mirroring the
// play_quests table. Keyed by campaign id, holding quests in creation order.
var (
	campaignQuestsMu sync.Mutex
	campaignQuests   = map[string][]*playQuest{}
)

func questJSON(q *playQuest) map[string]any {
	dependsOn := q.DependsOn
	if dependsOn == nil {
		dependsOn = []string{}
	}
	out := map[string]any{
		"quest_id":   q.QuestID,
		"title":      q.Title,
		"depends_on": dependsOn,
		"state":      q.State,
	}
	if q.Rewards != nil {
		out["rewards"] = rewardsJSON(q.Rewards)
	}
	return out
}

// findPlayQuest returns the quest with the given id in campaignID, or nil.
// Callers must already hold campaignQuestsMu.
func findPlayQuest(campaignID, questID string) *playQuest {
	for _, q := range campaignQuests[campaignID] {
		if q.QuestID == questID {
			return q
		}
	}
	return nil
}

type createQuestPlayRequest struct {
	QuestID   string   `json:"quest_id"`
	Title     string   `json:"title"`
	DependsOn []string `json:"depends_on"`
}

// createPlayQuestHandler lets the campaign's owning dm create a quest,
// locked until every listed dependency quest is completed.
func createPlayQuestHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createQuestPlayRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create quests")
		return
	}

	if req.QuestID == "" || req.Title == "" {
		writeError(w, http.StatusBadRequest, "quest_id and title are required nonempty strings")
		return
	}

	dependsOn := req.DependsOn
	if dependsOn == nil {
		dependsOn = []string{}
	}
	seen := map[string]bool{}
	for _, dep := range dependsOn {
		if dep == "" || dep == req.QuestID || seen[dep] {
			writeError(w, http.StatusBadRequest, "depends_on must be unique existing quest ids, excluding the quest's own id")
			return
		}
		seen[dep] = true
	}

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()

	for _, dep := range dependsOn {
		if findPlayQuest(campaignID, dep) == nil {
			writeError(w, http.StatusBadRequest, "depends_on must be unique existing quest ids, excluding the quest's own id")
			return
		}
	}

	if findPlayQuest(campaignID, req.QuestID) != nil {
		writeError(w, http.StatusConflict, "quest_id already exists in this campaign")
		return
	}

	q := &playQuest{
		CampaignID: campaignID,
		QuestID:    req.QuestID,
		Title:      req.Title,
		DependsOn:  dependsOn,
		State:      "locked",
	}
	if err := saveQuestToDB(q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}
	campaignQuests[campaignID] = append(campaignQuests[campaignID], q)

	writeJSON(w, http.StatusCreated, questJSON(q))
}

type updateQuestStateRequest struct {
	State string `json:"state"`
}

// updateQuestStateHandler lets the campaign's owning dm transition a quest
// from locked to active (once all dependencies are completed), or from
// active to completed.
func updateQuestStateHandler(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateQuestStateRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may change quest state")
		return
	}

	if req.State != "active" && req.State != "completed" {
		writeError(w, http.StatusBadRequest, "state must be exactly active or completed")
		return
	}

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()

	q := findPlayQuest(campaignID, questID)
	if q == nil {
		writeError(w, http.StatusNotFound, "unknown quest id")
		return
	}

	switch {
	case q.State == "locked" && req.State == "active":
		for _, dep := range q.DependsOn {
			depQuest := findPlayQuest(campaignID, dep)
			if depQuest == nil || depQuest.State != "completed" {
				writeError(w, http.StatusConflict, "all dependency quests must be completed before activation")
				return
			}
		}
	case q.State == "active" && req.State == "completed":
		// allowed
	default:
		writeError(w, http.StatusConflict, "invalid quest state transition")
		return
	}

	q.State = req.State
	if err := saveQuestToDB(q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}

	writeJSON(w, http.StatusOK, questJSON(q))
}

// listPlayQuestsHandler returns all quests for a campaign in creation order.
// Any authenticated campaign member (including the dm) may call this.
func listPlayQuestsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()

	quests := make([]map[string]any, 0, len(campaignQuests[campaignID]))
	for _, q := range campaignQuests[campaignID] {
		quests = append(quests, questJSON(q))
	}

	writeJSON(w, http.StatusOK, map[string]any{"quests": quests})
}
