package main

import (
	"net/http"
	"sync"
)

// questRewardConfig holds a quest's configured xp/item rewards, plus whether
// they have already been granted to the party.
type questRewardConfig struct {
	XP      int
	Items   map[string]int
	Awarded bool
}

func rewardsJSON(rc *questRewardConfig) map[string]any {
	items := rc.Items
	if items == nil {
		items = map[string]int{}
	}
	return map[string]any{"xp": rc.XP, "items": items}
}

// characterRewardTotals tracks a character's cumulative quest reward grants.
type characterRewardTotals struct {
	CampaignID  string
	CharacterID string
	XP          int
	Items       map[string]int
}

// characterRewardsMu guards characterRewards, the in-memory index mirroring
// the play_character_rewards table. Keyed by campaign id, then character id.
var (
	characterRewardsMu sync.Mutex
	characterRewards   = map[string]map[string]*characterRewardTotals{}
)

type configureQuestRewardsRequest struct {
	XP    int            `json:"xp"`
	Items map[string]int `json:"items"`
}

// configureQuestRewardsHandler lets the campaign's owning dm set the
// deterministic xp/item rewards a quest grants once completed. Only allowed
// while the quest is locked or active; completed quests reject
// reconfiguration.
func configureQuestRewardsHandler(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req configureQuestRewardsRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may configure quest rewards")
		return
	}

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()

	q := findPlayQuest(campaignID, questID)
	if q == nil {
		writeError(w, http.StatusNotFound, "unknown quest id")
		return
	}
	if q.State == "completed" {
		writeError(w, http.StatusConflict, "completed quests cannot have rewards configured")
		return
	}

	if req.XP < 0 {
		writeError(w, http.StatusBadRequest, "xp must be a nonnegative integer")
		return
	}
	items := map[string]int{}
	for itemID, qty := range req.Items {
		if !inventoryCatalog[itemID] {
			writeError(w, http.StatusBadRequest, "items keys must be valid catalog item ids")
			return
		}
		if qty <= 0 {
			writeError(w, http.StatusBadRequest, "items quantities must be positive integers")
			return
		}
		items[itemID] = qty
	}

	awarded := false
	if q.Rewards != nil {
		awarded = q.Rewards.Awarded
	}
	q.Rewards = &questRewardConfig{XP: req.XP, Items: items, Awarded: awarded}
	if err := saveQuestToDB(q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}

	writeJSON(w, http.StatusOK, questJSON(q))
}

// awardQuestRewardsHandler lets the campaign's owning dm grant a completed
// quest's configured rewards, exactly once, to every campaign member's
// character.
func awardQuestRewardsHandler(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may award quest rewards")
		return
	}

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()

	q := findPlayQuest(campaignID, questID)
	if q == nil {
		writeError(w, http.StatusNotFound, "unknown quest id")
		return
	}
	if q.State != "completed" || q.Rewards == nil {
		writeError(w, http.StatusConflict, "quest must be completed with rewards configured before awarding")
		return
	}
	if q.Rewards.Awarded {
		writeError(w, http.StatusConflict, "quest rewards have already been awarded")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	characterRewardsMu.Lock()
	defer characterRewardsMu.Unlock()

	for _, m := range playMembers[campaignID] {
		if err := grantQuestRewardsToCharacter(campaignID, m.CharacterID, q.Rewards); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save character rewards")
			return
		}
	}

	q.Rewards.Awarded = true
	if err := saveQuestToDB(q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"quest_id": q.QuestID,
		"awarded":  true,
		"xp":       q.Rewards.XP,
		"items":    rewardsJSON(q.Rewards)["items"],
	})
}

// grantQuestRewardsToCharacter adds rc's xp and items to charID's cumulative
// reward totals within campaignID, and deposits the reward items into the
// character's actual inventory. Callers must already hold
// characterRewardsMu and playMembersMu.
func grantQuestRewardsToCharacter(campaignID, charID string, rc *questRewardConfig) error {
	if characterRewards[campaignID] == nil {
		characterRewards[campaignID] = map[string]*characterRewardTotals{}
	}
	totals, exists := characterRewards[campaignID][charID]
	if !exists {
		totals = &characterRewardTotals{CampaignID: campaignID, CharacterID: charID, Items: map[string]int{}}
		characterRewards[campaignID][charID] = totals
	}
	totals.XP += rc.XP
	for itemID, qty := range rc.Items {
		totals.Items[itemID] += qty
	}
	if err := saveCharacterRewardsToDB(totals); err != nil {
		return err
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	for itemID, qty := range rc.Items {
		if inventoryItems[campaignID] == nil {
			inventoryItems[campaignID] = map[string]map[string]*playInventoryItem{}
		}
		if inventoryItems[campaignID][charID] == nil {
			inventoryItems[campaignID][charID] = map[string]*playInventoryItem{}
		}
		item, exists := inventoryItems[campaignID][charID][itemID]
		if !exists {
			item = &playInventoryItem{CampaignID: campaignID, CharacterID: charID, ItemID: itemID, Quantity: 0}
			inventoryItems[campaignID][charID][itemID] = item
		}
		item.Quantity += qty
		if err := saveInventoryItemToDB(item); err != nil {
			return err
		}
	}
	return nil
}

// getCharacterRewardsHandler returns a character's cumulative quest reward
// grants. Any authenticated campaign member (including the dm) may call this.
func getCharacterRewardsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	playMembersMu.Lock()
	_, exists := findMemberByCharacterID(campaignID, charID)
	playMembersMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	characterRewardsMu.Lock()
	defer characterRewardsMu.Unlock()

	totals, hasTotals := characterRewards[campaignID][charID]
	xp := 0
	items := map[string]int{}
	if hasTotals {
		xp = totals.XP
		for itemID, qty := range totals.Items {
			items[itemID] = qty
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": charID,
		"xp":           xp,
		"items":        items,
	})
}
