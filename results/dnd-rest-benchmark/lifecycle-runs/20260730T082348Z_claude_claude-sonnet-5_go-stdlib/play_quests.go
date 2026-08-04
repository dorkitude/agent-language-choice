package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playQuest is a campaign quest record whose activation is gated by
// prerequisite quests reaching the completed state.
type playQuest struct {
	QuestID   string
	Title     string
	DependsOn []string
	State     string

	// Rewards holds the quest's configured completion rewards, or nil if
	// none have been configured yet.
	Rewards *playQuestRewards

	// RewardsAwarded records whether the configured rewards have already
	// been granted to campaign members. Rewards may be awarded exactly
	// once.
	RewardsAwarded bool
}

// playQuestRewards is a quest's configured XP and item rewards.
type playQuestRewards struct {
	XP    int
	Items map[string]int
}

func playQuestRewardsResponse(rw *playQuestRewards) map[string]interface{} {
	items := rw.Items
	if items == nil {
		items = map[string]int{}
	}
	return map[string]interface{}{
		"xp":    rw.XP,
		"items": items,
	}
}

func playQuestResponse(q *playQuest) map[string]interface{} {
	resp := map[string]interface{}{
		"quest_id":   q.QuestID,
		"title":      q.Title,
		"depends_on": q.DependsOn,
		"state":      q.State,
	}
	if q.Rewards != nil {
		resp["rewards"] = playQuestRewardsResponse(q.Rewards)
	}
	return resp
}

// findPlayQuest locates a quest by id within c.
func findPlayQuest(c *playCampaign, questID string) *playQuest {
	for _, q := range c.Quests {
		if q.QuestID == questID {
			return q
		}
	}
	return nil
}

// handlePlayCampaignQuestSub routes the "quests" and "quests/..." sub-paths
// of a play campaign. It returns false if rest does not name a quest path,
// so the caller can fall through to its own routing.
func handlePlayCampaignQuestSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "quests" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayQuest(w, r, campaignID)
		case http.MethodGet:
			handleListPlayQuests(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "quests/") {
		return false
	}
	questRest := strings.TrimPrefix(rest, "quests/")
	if questID, ok := strings.CutSuffix(questRest, "/state"); ok && questID != "" {
		if r.Method != http.MethodPut {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleUpdatePlayQuestState(w, r, campaignID, questID)
		return true
	}
	if questID, ok := strings.CutSuffix(questRest, "/rewards/award"); ok && questID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAwardPlayQuestRewards(w, r, campaignID, questID)
		return true
	}
	if questID, ok := strings.CutSuffix(questRest, "/rewards"); ok && questID != "" {
		if r.Method != http.MethodPut {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleConfigurePlayQuestRewards(w, r, campaignID, questID)
		return true
	}
	return false
}

// handleCreatePlayQuest lets the campaign dm create a new quest record,
// gated by an optional set of prerequisite quests already in the campaign.
func handleCreatePlayQuest(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		QuestID   string   `json:"quest_id"`
		Title     string   `json:"title"`
		DependsOn []string `json:"depends_on"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.QuestID == "" || req.Title == "" {
		writeError(w, http.StatusBadRequest, "quest_id and title are required")
		return
	}

	seen := make(map[string]bool, len(req.DependsOn))
	for _, dep := range req.DependsOn {
		if dep == "" || dep == req.QuestID || seen[dep] {
			writeError(w, http.StatusBadRequest, "depends_on must contain unique existing quest ids, excluding this quest")
			return
		}
		seen[dep] = true
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create quests")
		return
	}
	for _, dep := range req.DependsOn {
		if findPlayQuest(c, dep) == nil {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "depends_on must contain unique existing quest ids, excluding this quest")
			return
		}
	}
	if findPlayQuest(c, req.QuestID) != nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "quest_id already exists")
		return
	}

	dependsOn := req.DependsOn
	if dependsOn == nil {
		dependsOn = []string{}
	}
	q := &playQuest{
		QuestID:   req.QuestID,
		Title:     req.Title,
		DependsOn: dependsOn,
		State:     "locked",
	}
	c.Quests = append(c.Quests, q)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playQuestResponse(q))
}

// handleUpdatePlayQuestState lets the campaign dm advance a quest's state
// through the locked -> active -> completed lifecycle.
func handleUpdatePlayQuestState(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		State string `json:"state"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.State != "active" && req.State != "completed" {
		writeError(w, http.StatusBadRequest, "state must be active or completed")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may change quest state")
		return
	}
	q := findPlayQuest(c, questID)
	if q == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}

	switch {
	case q.State == "locked" && req.State == "active":
		for _, dep := range q.DependsOn {
			depQuest := findPlayQuest(c, dep)
			if depQuest == nil || depQuest.State != "completed" {
				playMu.Unlock()
				writeError(w, http.StatusConflict, "all dependencies must be completed before activation")
				return
			}
		}
		q.State = "active"
	case q.State == "active" && req.State == "completed":
		q.State = "completed"
	default:
		playMu.Unlock()
		writeError(w, http.StatusConflict, "invalid state transition")
		return
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, playQuestResponse(q))
}

// handleListPlayQuests returns every campaign quest, in creation order, to
// any authenticated campaign member.
func handleListPlayQuests(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view quests")
		return
	}

	quests := make([]map[string]interface{}, 0, len(c.Quests))
	for _, q := range c.Quests {
		quests = append(quests, playQuestResponse(q))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"quests": quests,
	})
}

// handleConfigurePlayQuestRewards lets the campaign dm configure the XP and
// item rewards a quest grants on completion. The quest must not yet be
// completed.
func handleConfigurePlayQuestRewards(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		XP    *int           `json:"xp"`
		Items map[string]int `json:"items"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.XP == nil || *req.XP < 0 {
		writeError(w, http.StatusBadRequest, "xp must be a nonnegative integer")
		return
	}
	for itemID, qty := range req.Items {
		if !validInventoryItems[itemID] || qty <= 0 {
			writeError(w, http.StatusBadRequest, "items must map valid catalog item ids to positive integer quantities")
			return
		}
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may configure quest rewards")
		return
	}
	q := findPlayQuest(c, questID)
	if q == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	if q.State != "locked" && q.State != "active" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "quest rewards may only be configured before completion")
		return
	}

	items := req.Items
	if items == nil {
		items = map[string]int{}
	}
	q.Rewards = &playQuestRewards{XP: *req.XP, Items: items}
	resp := playQuestResponse(q)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleAwardPlayQuestRewards lets the campaign dm grant a completed quest's
// configured rewards to every campaign member, exactly once.
func handleAwardPlayQuestRewards(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may award quest rewards")
		return
	}
	q := findPlayQuest(c, questID)
	if q == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	if q.State != "completed" || q.Rewards == nil || q.RewardsAwarded {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "quest rewards are not ready to be awarded")
		return
	}

	for _, m := range c.Members {
		m.RewardXP += q.Rewards.XP
		if len(q.Rewards.Items) > 0 {
			if m.RewardItems == nil {
				m.RewardItems = make(map[string]int)
			}
			if m.Items == nil {
				m.Items = make(map[string]int)
			}
			for itemID, qty := range q.Rewards.Items {
				m.RewardItems[itemID] += qty
				m.Items[itemID] += qty
			}
		}
	}
	q.RewardsAwarded = true
	resp := map[string]interface{}{
		"quest_id": q.QuestID,
		"awarded":  true,
		"xp":       q.Rewards.XP,
		"items":    q.Rewards.Items,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleGetPlayCharacterRewards returns a character's cumulative quest
// reward grants, available to any authenticated campaign member.
func handleGetPlayCharacterRewards(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view character rewards")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	items := member.RewardItems
	if items == nil {
		items = map[string]int{}
	}
	resp := map[string]interface{}{
		"character_id": charID,
		"xp":           member.RewardXP,
		"items":        items,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
