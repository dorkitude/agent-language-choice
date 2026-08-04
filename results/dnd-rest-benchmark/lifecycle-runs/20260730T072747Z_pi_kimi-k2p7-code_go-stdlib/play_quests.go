package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// playQuestCreateRequest binds the payload for a new play-campaign quest.
type playQuestCreateRequest struct {
	QuestID   string   `json:"quest_id"`
	Title     string   `json:"title"`
	DependsOn []string `json:"depends_on"`
}

// questRewards is the configured reward payload embedded in a quest record.
type questRewards struct {
	XP    int            `json:"xp"`
	Items map[string]int `json:"items"`
}

// playQuestResponse is the shape returned when a quest is created, updated,
// or listed. It always includes a non-null depends_on array. Rewards are
// omitted from the JSON when they have not been configured.
type playQuestResponse struct {
	QuestID   string        `json:"quest_id"`
	Title     string        `json:"title"`
	DependsOn []string      `json:"depends_on"`
	State     string        `json:"state"`
	Rewards   *questRewards `json:"rewards,omitempty"`
}

// playQuestListResponse is the shape returned by the quest listing endpoint.
type playQuestListResponse struct {
	Quests []playQuestResponse `json:"quests"`
}

// playQuestStateRequest binds the payload for a quest state transition.
type playQuestStateRequest struct {
	State string `json:"state"`
}

// questRewardsRequest binds the payload for configuring quest rewards.
type questRewardsRequest struct {
	XP    int            `json:"xp"`
	Items map[string]int `json:"items"`
}

// questAwardResponse is the shape returned after awarding quest rewards.
type questAwardResponse struct {
	QuestID string         `json:"quest_id"`
	Awarded bool           `json:"awarded"`
	XP      int            `json:"xp"`
	Items   map[string]int `json:"items"`
}

// characterQuestRewardsResponse is the shape returned when reading a
// character's cumulative quest reward grants.
type characterQuestRewardsResponse struct {
	CharacterID string         `json:"character_id"`
	XP          int            `json:"xp"`
	Items       map[string]int `json:"items"`
}

// loadPlayQuestDependencies returns the dependency quest IDs for a play quest
// in insertion order. The caller must hold dbMu.
func loadPlayQuestDependencies(campaignID, questID string) ([]string, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT depends_on FROM play_quest_dependencies WHERE campaign_id=%s AND quest_id=%s ORDER BY id;", sq(campaignID), sq(questID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		DependsOn string `json:"depends_on"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	deps := make([]string, 0, len(rows))
	for _, row := range rows {
		deps = append(deps, row.DependsOn)
	}
	return deps, nil
}

// loadPlayQuest loads a single play quest by campaign and quest id. The
// caller must hold dbMu.
func loadPlayQuest(campaignID, questID string) (*playQuestResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT quest_id, title, state, rewards_xp, rewards_items FROM play_quests WHERE campaign_id=%s AND quest_id=%s LIMIT 1;", sq(campaignID), sq(questID)))
	if err != nil {
		return nil, false, err
	}
	var rows []struct {
		QuestID      string `json:"quest_id"`
		Title        string `json:"title"`
		State        string `json:"state"`
		RewardsXP    int    `json:"rewards_xp"`
		RewardsItems string `json:"rewards_items"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	deps, err := loadPlayQuestDependencies(campaignID, questID)
	if err != nil {
		return nil, false, err
	}
	if deps == nil {
		deps = []string{}
	}
	rewards := questRewards{XP: rows[0].RewardsXP, Items: map[string]int{}}
	if rows[0].RewardsItems != "" && rows[0].RewardsItems != "null" {
		if err := json.Unmarshal([]byte(rows[0].RewardsItems), &rewards.Items); err != nil {
			return nil, false, err
		}
	}
	if rewards.Items == nil {
		rewards.Items = map[string]int{}
	}
	resp := &playQuestResponse{
		QuestID:   rows[0].QuestID,
		Title:     rows[0].Title,
		DependsOn: deps,
		State:     rows[0].State,
	}
	if questRewardsConfigured(rewards) {
		resp.Rewards = &rewards
	}
	return resp, true, nil
}

// playQuestDependenciesCompleted reports whether every dependency of the given
// quest has state 'completed'. The caller must hold dbMu.
func playQuestDependenciesCompleted(campaignID, questID string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS pending FROM play_quest_dependencies d JOIN play_quests q ON q.campaign_id=d.campaign_id AND q.quest_id=d.depends_on WHERE d.campaign_id=%s AND d.quest_id=%s AND q.state!='completed';", sq(campaignID), sq(questID)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		Pending int `json:"pending"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	if len(rows) == 0 {
		return true, nil
	}
	return rows[0].Pending == 0, nil
}

// questRewardsConfigured reports whether a quest has non-default rewards.
func questRewardsConfigured(rewards questRewards) bool {
	return rewards.XP > 0 || len(rewards.Items) > 0
}

// createPlayQuestHandler lets the campaign DM create a quest with
// dependencies. Players receive 403. Duplicate quest IDs in the same campaign
// return 409. Invalid dependencies return 400.
func createPlayQuestHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req playQuestCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.QuestID == "" || req.Title == "" {
		writeError(w, http.StatusBadRequest, "invalid quest")
		return
	}

	seen := map[string]bool{}
	for _, dep := range req.DependsOn {
		if dep == "" {
			writeError(w, http.StatusBadRequest, "invalid dependency")
			return
		}
		if seen[dep] {
			writeError(w, http.StatusBadRequest, "invalid dependency")
			return
		}
		seen[dep] = true
		if dep == req.QuestID {
			writeError(w, http.StatusBadRequest, "invalid dependency")
			return
		}
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM play_quests WHERE campaign_id=%s AND quest_id=%s LIMIT 1;", sq(campaignID), sq(req.QuestID)))
	if err != nil {
		log.Printf("create play quest duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "quest already exists")
		return
	}

	if len(req.DependsOn) > 0 {
		depQuoted := make([]string, len(req.DependsOn))
		for i, dep := range req.DependsOn {
			depQuoted[i] = sq(dep)
		}
		out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS cnt FROM play_quests WHERE campaign_id=%s AND quest_id IN (%s);", sq(campaignID), strings.Join(depQuoted, ", ")))
		if err != nil {
			log.Printf("create play quest dependency count query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var counts []struct {
			Cnt int `json:"cnt"`
		}
		if err := json.Unmarshal(out, &counts); err != nil {
			log.Printf("create play quest dependency count unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		cnt := 0
		if len(counts) > 0 {
			cnt = counts[0].Cnt
		}
		if cnt != len(req.DependsOn) {
			writeError(w, http.StatusBadRequest, "invalid dependency")
			return
		}
	}

	var sb strings.Builder
	sb.WriteString("BEGIN;")
	sb.WriteString(fmt.Sprintf("INSERT INTO play_quests (campaign_id, quest_id, title, state) VALUES (%s, %s, %s, 'locked');", sq(campaignID), sq(req.QuestID), sq(req.Title)))
	for _, dep := range req.DependsOn {
		sb.WriteString(fmt.Sprintf("INSERT INTO play_quest_dependencies (campaign_id, quest_id, depends_on) VALUES (%s, %s, %s);", sq(campaignID), sq(req.QuestID), sq(dep)))
	}
	sb.WriteString("COMMIT;")
	if err := dbExec(sb.String()); err != nil {
		log.Printf("create play quest insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	respDependsOn := req.DependsOn
	if respDependsOn == nil {
		respDependsOn = []string{}
	}
	writeJSON(w, http.StatusCreated, playQuestResponse{
		QuestID:   req.QuestID,
		Title:     req.Title,
		DependsOn: respDependsOn,
		State:     "locked",
	})
}

// updatePlayQuestStateHandler lets the campaign DM change a quest's state.
// Players receive 403. Unknown quests return 404. Invalid state values return
// 400. Disallowed transitions return 409.
func updatePlayQuestStateHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	questID := r.PathValue("quest_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req playQuestStateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.State != "active" && req.State != "completed" {
		writeError(w, http.StatusBadRequest, "invalid state")
		return
	}

	quest, ok, err := loadPlayQuest(campaignID, questID)
	if err != nil {
		log.Printf("update play quest state load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}

	if req.State == "active" {
		if quest.State != "locked" {
			writeError(w, http.StatusConflict, "invalid transition")
			return
		}
		allCompleted, err := playQuestDependenciesCompleted(campaignID, questID)
		if err != nil {
			log.Printf("update play quest dependencies completed query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !allCompleted {
			writeError(w, http.StatusConflict, "invalid transition")
			return
		}
	} else if req.State == "completed" {
		if quest.State != "active" {
			writeError(w, http.StatusConflict, "invalid transition")
			return
		}
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_quests SET state=%s WHERE campaign_id=%s AND quest_id=%s;", sq(req.State), sq(campaignID), sq(questID))); err != nil {
		log.Printf("update play quest state update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	updated, ok, err := loadPlayQuest(campaignID, questID)
	if err != nil {
		log.Printf("update play quest state reload error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

// listPlayQuestsHandler returns all quests in a play campaign in creation
// order. It is available to the campaign owner and members.
func listPlayQuestsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT quest_id, title, state, rewards_xp, rewards_items FROM play_quests WHERE campaign_id=%s ORDER BY id;", sq(campaignID)))
	if err != nil {
		log.Printf("list play quests query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		QuestID      string `json:"quest_id"`
		Title        string `json:"title"`
		State        string `json:"state"`
		RewardsXP    int    `json:"rewards_xp"`
		RewardsItems string `json:"rewards_items"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list play quests unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	quests := make([]playQuestResponse, 0, len(rows))
	for _, row := range rows {
		deps, err := loadPlayQuestDependencies(campaignID, row.QuestID)
		if err != nil {
			log.Printf("list play quests dependencies query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if deps == nil {
			deps = []string{}
		}
		rewards := questRewards{XP: row.RewardsXP, Items: map[string]int{}}
		if row.RewardsItems != "" && row.RewardsItems != "null" {
			if err := json.Unmarshal([]byte(row.RewardsItems), &rewards.Items); err != nil {
				log.Printf("list play quests rewards unmarshal error: %v", err)
				writeError(w, http.StatusInternalServerError, "internal error")
				return
			}
		}
		if rewards.Items == nil {
			rewards.Items = map[string]int{}
		}
		q := playQuestResponse{
			QuestID:   row.QuestID,
			Title:     row.Title,
			DependsOn: deps,
			State:     row.State,
		}
		if questRewardsConfigured(rewards) {
			q.Rewards = &rewards
		}
		quests = append(quests, q)
	}
	if quests == nil {
		quests = []playQuestResponse{}
	}

	writeJSON(w, http.StatusOK, playQuestListResponse{Quests: quests})
}

// configureQuestRewardsHandler lets the campaign DM configure rewards for a
// quest. Players receive 403. Unknown quests return 404. The quest must be in
// state 'locked' or 'active'; completed quests reject configuration with 409.
// Invalid reward bodies return 400.
func configureQuestRewardsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	questID := r.PathValue("quest_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req questRewardsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Items == nil || req.XP < 0 {
		writeError(w, http.StatusBadRequest, "invalid rewards")
		return
	}
	for itemID, qty := range req.Items {
		if !validInventoryItemIDs[itemID] || qty <= 0 {
			writeError(w, http.StatusBadRequest, "invalid rewards")
			return
		}
	}

	quest, ok, err := loadPlayQuest(campaignID, questID)
	if err != nil {
		log.Printf("configure quest rewards load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	if quest.State != "locked" && quest.State != "active" {
		writeError(w, http.StatusConflict, "quest cannot be configured")
		return
	}

	itemsJSON, err := json.Marshal(req.Items)
	if err != nil {
		log.Printf("configure quest rewards items marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_quests SET rewards_xp=%d, rewards_items=%s WHERE campaign_id=%s AND quest_id=%s;",
		req.XP, sq(string(itemsJSON)), sq(campaignID), sq(questID))); err != nil {
		log.Printf("configure quest rewards update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	updated, ok, err := loadPlayQuest(campaignID, questID)
	if err != nil {
		log.Printf("configure quest rewards reload error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

// awardQuestRewardsHandler lets the campaign DM award configured quest rewards
// once to every campaign member. Players receive 403. Unknown quests return
// 404. The quest must be completed and configured, and rewards must not have
// been awarded before; otherwise the request returns 409.
func awardQuestRewardsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	questID := r.PathValue("quest_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	quest, ok, err := loadPlayQuest(campaignID, questID)
	if err != nil {
		log.Printf("award quest rewards load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "quest not found")
		return
	}
	if quest.State != "completed" {
		writeError(w, http.StatusConflict, "quest not completed")
		return
	}
	if quest.Rewards == nil {
		writeError(w, http.StatusConflict, "rewards not configured")
		return
	}

	alreadyAwarded, err := queryExists(fmt.Sprintf("SELECT 1 FROM play_quests WHERE campaign_id=%s AND quest_id=%s AND rewards_awarded=1 LIMIT 1;", sq(campaignID), sq(questID)))
	if err != nil {
		log.Printf("award quest rewards awarded check error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if alreadyAwarded {
		writeError(w, http.StatusConflict, "rewards already awarded")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("award quest rewards members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	itemsJSON, err := json.Marshal(quest.Rewards.Items)
	if err != nil {
		log.Printf("award quest rewards items marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	var sb strings.Builder
	sb.WriteString("BEGIN;")
	for _, member := range members {
		sb.WriteString(fmt.Sprintf("INSERT INTO play_quest_reward_grants (campaign_id, quest_id, character_id, xp, items) VALUES (%s, %s, %s, %d, %s) ON CONFLICT(campaign_id, quest_id, character_id) DO UPDATE SET xp=excluded.xp, items=excluded.items;",
			sq(campaignID), sq(questID), sq(member.CharacterID), quest.Rewards.XP, sq(string(itemsJSON))))
		for itemID, qty := range quest.Rewards.Items {
			sb.WriteString(fmt.Sprintf(
				"INSERT INTO character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;",
				sq(campaignID), sq(member.CharacterID), sq(itemID), qty))
		}
	}
	sb.WriteString(fmt.Sprintf("UPDATE play_quests SET rewards_awarded=1 WHERE campaign_id=%s AND quest_id=%s;", sq(campaignID), sq(questID)))
	sb.WriteString("COMMIT;")
	if err := dbExec(sb.String()); err != nil {
		log.Printf("award quest rewards exec error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, questAwardResponse{
		QuestID: questID,
		Awarded: true,
		XP:      quest.Rewards.XP,
		Items:   quest.Rewards.Items,
	})
}

// getCharacterQuestRewardsHandler returns cumulative quest reward grants for a
// campaign character. It is available to authenticated campaign members.
func getCharacterQuestRewardsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get character quest rewards member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT xp, items FROM play_quest_reward_grants WHERE campaign_id=%s AND character_id=%s;", sq(campaignID), sq(characterID)))
	if err != nil {
		log.Printf("get character quest rewards query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		XP    int    `json:"xp"`
		Items string `json:"items"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("get character quest rewards unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	totalXP := 0
	totalItems := map[string]int{}
	for _, row := range rows {
		totalXP += row.XP
		if row.Items != "" && row.Items != "null" {
			var items map[string]int
			if err := json.Unmarshal([]byte(row.Items), &items); err != nil {
				log.Printf("get character quest rewards items unmarshal error: %v", err)
				writeError(w, http.StatusInternalServerError, "internal error")
				return
			}
			for itemID, qty := range items {
				totalItems[itemID] += qty
			}
		}
	}

	writeJSON(w, http.StatusOK, characterQuestRewardsResponse{
		CharacterID: characterID,
		XP:          totalXP,
		Items:       totalItems,
	})
}
