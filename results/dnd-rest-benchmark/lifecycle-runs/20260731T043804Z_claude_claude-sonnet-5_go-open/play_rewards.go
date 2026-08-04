package main

import (
	"net/http"
	"sync"
)

type playEncounterReward struct {
	CampaignID  string       `json:"-"`
	EncounterID string       `json:"encounter_id"`
	XP          int          `json:"xp"`
	Loot        []dmLootItem `json:"loot"`
}

// playEncounterRewardsMu guards playEncounterRewards, the in-memory index
// mirroring the play_encounter_rewards table. It is keyed by campaign id,
// then encounter id.
var (
	playEncounterRewardsMu sync.Mutex
	playEncounterRewards   = map[string]map[string]*playEncounterReward{}
)

type awardEncounterRewardsRequest struct {
	XP   int          `json:"xp"`
	Loot []dmLootItem `json:"loot"`
}

// awardEncounterRewardsHandler lets the owning dm grant deterministic xp and
// loot for a closed-out encounter. Only the owner may call this; rewards may
// be awarded only once per encounter, so a duplicate call returns 409.
func awardEncounterRewardsHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req awardEncounterRewardsRequest
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
		writeError(w, http.StatusForbidden, "only the owning dm may award encounter rewards")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	enc, exists := playEncounters[campaignID][encID]
	if !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	playEncounterRewardsMu.Lock()
	defer playEncounterRewardsMu.Unlock()

	if _, exists := playEncounterRewards[campaignID][encID]; exists {
		writeError(w, http.StatusConflict, "rewards have already been awarded for this encounter")
		return
	}

	loot := req.Loot
	if loot == nil {
		loot = []dmLootItem{}
	}
	reward := &playEncounterReward{
		CampaignID:  campaignID,
		EncounterID: encID,
		XP:          req.XP,
		Loot:        loot,
	}
	if err := savePlayEncounterRewardToDB(reward); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter reward")
		return
	}
	if playEncounterRewards[campaignID] == nil {
		playEncounterRewards[campaignID] = map[string]*playEncounterReward{}
	}
	playEncounterRewards[campaignID][encID] = reward

	enc.XPAwarded = req.XP
	if err := savePlayEncounterToDB(enc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter")
		return
	}

	writeJSON(w, http.StatusOK, reward)
}

// closeEncounterHandler lets the owning dm mark an encounter closed. Rewards
// may be awarded before or after closing; xp_awarded reports 0 if the
// encounter was closed without ever having rewards awarded.
func closeEncounterHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may close an encounter")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	enc, exists := playEncounters[campaignID][encID]
	if !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	enc.Status = "closed"
	if err := savePlayEncounterToDB(enc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         enc.ID,
		"status":     enc.Status,
		"xp_awarded": enc.XPAwarded,
	})
}

// endEncounterHandler lets the owning dm close out the campaign's active
// encounter (if still open) and restores the campaign to the exploration
// phase, resuming the turn queue from the actor it had before combat began.
// Only the owner may call this; if the campaign was not in combat, it
// returns 409.
func endEncounterHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may end an encounter")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	enc, exists := playEncounters[campaignID][encID]
	if !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	if c.CurrentEncounterID != encID {
		writeError(w, http.StatusConflict, "campaign is not in combat")
		return
	}

	if enc.Status == "active" {
		enc.Status = "closed"
		if err := savePlayEncounterToDB(enc); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save encounter")
			return
		}
	}

	c.CurrentEncounterID = ""
	c.CurrentActor = c.Owner
	c.Phase = "exploration"
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":   c.ID,
		"status":        c.Status,
		"phase":         "exploration",
		"current_actor": c.CurrentActor,
	})
}
