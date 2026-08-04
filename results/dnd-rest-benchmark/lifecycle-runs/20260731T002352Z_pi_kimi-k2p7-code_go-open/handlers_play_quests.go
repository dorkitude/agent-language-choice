package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
)

// createPlayQuestHandler creates a deterministic campaign quest. Only the
// campaign owner (DM) may create quests. Players receive 403. quest_id and
// title are required nonempty strings, and depends_on must be a JSON array of
// unique quest IDs that already exist in the same campaign. Duplicate quest
// ids within the campaign return 409.
func createPlayQuestHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create quests")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create quests")
		return
	}

	var req playQuestCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.QuestID) == "" {
		badRequest(w, "quest_id is required")
		return
	}
	if strings.TrimSpace(req.Title) == "" {
		badRequest(w, "title is required")
		return
	}
	if req.DependsOn == nil {
		badRequest(w, "depends_on is required")
		return
	}

	seen := make(map[string]struct{}, len(req.DependsOn))
	for _, dep := range req.DependsOn {
		if dep == "" {
			badRequest(w, "dependency ids must be non-empty strings")
			return
		}
		if dep == req.QuestID {
			badRequest(w, "quest cannot depend on itself")
			return
		}
		if _, ok := seen[dep]; ok {
			badRequest(w, "dependency ids must be unique")
			return
		}
		seen[dep] = struct{}{}
	}

	if len(req.DependsOn) > 0 {
		count, err := dbCountPlayQuestsByIDs(id, "", req.DependsOn)
		if err != nil {
			log.Printf("count play quest dependencies: %v", err)
			badRequest(w, "failed to validate dependencies")
			return
		}
		if count != len(req.DependsOn) {
			badRequest(w, "invalid dependency list")
			return
		}
	}

	if err := dbCreatePlayQuest(id, req.QuestID, req.Title, req.DependsOn); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "quest already exists")
			return
		}
		log.Printf("create play quest: %v", err)
		badRequest(w, "failed to create quest")
		return
	}

	writeJSON(w, http.StatusCreated, playQuest{
		QuestID:   req.QuestID,
		Title:     req.Title,
		DependsOn: req.DependsOn,
		State:     playQuestStateLocked,
	})
}

// updatePlayQuestStateHandler changes a quest's state. Only the campaign owner
// (DM) may change quest state. Players receive 403. Unknown quests return 404.
// Allowed transitions are locked -> active (when all dependencies are
// completed) and active -> completed. All other transitions return 409.
func updatePlayQuestStateHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can change quest state")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can change quest state")
		return
	}

	questID := r.PathValue("quest_id")

	var req playQuestStateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.State != playQuestStateActive && req.State != playQuestStateCompleted {
		badRequest(w, "state must be active or completed")
		return
	}

	q, err := dbGetPlayQuest(id, questID)
	if err != nil {
		log.Printf("get play quest: %v", err)
		badRequest(w, "failed to read quest")
		return
	}
	if q == nil {
		notFound(w, "quest not found")
		return
	}

	valid := false
	switch q.State {
	case playQuestStateLocked:
		if req.State == playQuestStateActive {
			count, err := dbCountPlayQuestsByIDs(id, playQuestStateCompleted, q.DependsOn)
			if err != nil {
				log.Printf("count completed dependencies: %v", err)
				badRequest(w, "failed to validate dependencies")
				return
			}
			if count == len(q.DependsOn) {
				valid = true
			}
		}
	case playQuestStateActive:
		if req.State == playQuestStateCompleted {
			valid = true
		}
	}
	if !valid {
		conflict(w, "invalid state transition")
		return
	}

	if err := dbUpdatePlayQuestState(id, questID, req.State); err != nil {
		log.Printf("update play quest state: %v", err)
		badRequest(w, "failed to update quest state")
		return
	}

	q.State = req.State
	writeJSON(w, http.StatusOK, q)
}

// getPlayQuestsHandler lists all quests for a play campaign. The campaign DM
// and any bound party member may read the list. Quests are returned in creation
// order.
func getPlayQuestsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	quests, err := dbGetPlayQuests(id)
	if err != nil {
		log.Printf("get play quests: %v", err)
		badRequest(w, "failed to read quests")
		return
	}

	writeJSON(w, http.StatusOK, playQuestsResponse{Quests: quests})
}

// configurePlayQuestRewardsHandler sets the reward payload for a play quest.
// Only the campaign owner (DM) may configure rewards. Players receive 403.
// Unknown quests return 404. The quest must be locked or active; completed
// quests reject configuration with 409. The body must contain a non-negative
// xp integer and an items object whose keys are valid catalog item IDs and
// whose values are positive integer quantities.
func configurePlayQuestRewardsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can configure quest rewards")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can configure quest rewards")
		return
	}

	questID := r.PathValue("quest_id")

	q, err := dbGetPlayQuest(id, questID)
	if err != nil {
		log.Printf("get play quest: %v", err)
		badRequest(w, "failed to read quest")
		return
	}
	if q == nil {
		notFound(w, "quest not found")
		return
	}
	if q.State != playQuestStateLocked && q.State != playQuestStateActive {
		conflict(w, "quest is already completed")
		return
	}

	var req questRewards
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Items == nil {
		badRequest(w, "items is required")
		return
	}
	if req.XP < 0 {
		badRequest(w, "xp must be non-negative")
		return
	}
	for itemID, qty := range req.Items {
		if !validInventoryItemIDs[itemID] {
			badRequest(w, "invalid item id")
			return
		}
		if qty <= 0 {
			badRequest(w, "item quantity must be positive")
			return
		}
	}

	if err := dbConfigurePlayQuestRewards(id, questID, &req); err != nil {
		if err == sql.ErrNoRows {
			notFound(w, "quest not found")
			return
		}
		if errors.Is(err, errQuestCompleted) {
			conflict(w, "quest is already completed")
			return
		}
		log.Printf("configure quest rewards: %v", err)
		badRequest(w, "failed to configure quest rewards")
		return
	}

	q.Rewards = &req
	writeJSON(w, http.StatusOK, q)
}

// awardPlayQuestRewardsHandler grants the configured quest rewards once to
// every campaign member. Only the campaign owner (DM) may award rewards.
// Players receive 403. Unknown quests return 404. The quest must be completed
// with rewards already configured; otherwise the request returns 409. A repeat
// award returns 409 and makes no changes.
func awardPlayQuestRewardsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can award quest rewards")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can award quest rewards")
		return
	}

	questID := r.PathValue("quest_id")

	q, err := dbGetPlayQuest(id, questID)
	if err != nil {
		log.Printf("get play quest: %v", err)
		badRequest(w, "failed to read quest")
		return
	}
	if q == nil {
		notFound(w, "quest not found")
		return
	}

	if err := dbAwardPlayQuestRewards(id, questID); err != nil {
		if err == sql.ErrNoRows {
			notFound(w, "quest not found")
			return
		}
		if errors.Is(err, errQuestNotCompleted) || errors.Is(err, errQuestRewardsNotConfigured) || errors.Is(err, errQuestAlreadyAwarded) {
			conflict(w, "cannot award quest rewards")
			return
		}
		log.Printf("award quest rewards: %v", err)
		badRequest(w, "failed to award quest rewards")
		return
	}

	writeJSON(w, http.StatusCreated, questRewardAwardResponse{
		QuestID: questID,
		Awarded: true,
		XP:      q.Rewards.XP,
		Items:   q.Rewards.Items,
	})
}

// getCharacterRewardsHandler returns the cumulative quest rewards granted to a
// campaign character. It is available to any authenticated campaign member.
// Unknown characters return 404.
func getCharacterRewardsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("character_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character rewards: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	rewards, err := dbGetCharacterRewards(id, charID)
	if err != nil {
		log.Printf("get character rewards: %v", err)
		badRequest(w, "failed to read rewards")
		return
	}

	writeJSON(w, http.StatusOK, rewards)
}
