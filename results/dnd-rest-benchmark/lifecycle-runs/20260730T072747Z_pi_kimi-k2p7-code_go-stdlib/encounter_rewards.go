package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// lootItem is a single piece of loot awarded for an encounter.
type lootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// rewardRequest binds the payload for awarding encounter rewards.
type rewardRequest struct {
	XP   int        `json:"xp"`
	Loot []lootItem `json:"loot"`
}

// rewardRecord is the durable reward record returned when rewards are awarded.
type rewardRecord struct {
	ID   string     `json:"id"`
	XP   int        `json:"xp"`
	Loot []lootItem `json:"loot"`
}

// closeEncounterResponse is the shape returned after closing an encounter.
type closeEncounterResponse struct {
	ID        string `json:"id"`
	Status    string `json:"status"`
	XPAwarded int    `json:"xp_awarded"`
}

// awardEncounterRewardsHandler lets the campaign owner award deterministic XP
// and loot for an encounter. Rewards may be awarded only once per encounter;
// duplicate attempts return 409. The endpoint returns 200 with the reward record.
func awardEncounterRewardsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req rewardRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.XP < 0 {
		writeError(w, http.StatusBadRequest, "invalid xp")
		return
	}
	for _, item := range req.Loot {
		if item.Slug == "" || item.Quantity <= 0 {
			writeError(w, http.StatusBadRequest, "invalid loot")
			return
		}
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("award rewards encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	if enc.RewardsAwarded > 0 {
		writeError(w, http.StatusConflict, "rewards already awarded")
		return
	}

	loot := req.Loot
	if loot == nil {
		loot = []lootItem{}
	}
	lootJSON, err := json.Marshal(loot)
	if err != nil {
		log.Printf("award rewards loot marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_encounters SET xp_awarded=%d, loot=%s, rewards_awarded=1 WHERE id=%s AND campaign_id=%s;",
		req.XP, sq(string(lootJSON)), sq(encounterID), sq(campaignID))); err != nil {
		log.Printf("award rewards update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, rewardRecord{
		ID:   encounterID,
		XP:   req.XP,
		Loot: loot,
	})
}

// closeEncounterHandler marks a campaign encounter as closed. Only the owner
// may call it. Closing before rewards are awarded is allowed and returns
// xp_awarded: 0. The endpoint is idempotent for already-closed encounters.
func closeEncounterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("close encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	if enc.Status != "closed" {
		if err := dbExec(fmt.Sprintf("UPDATE campaign_encounters SET status='closed' WHERE id=%s AND campaign_id=%s;",
			sq(encounterID), sq(campaignID))); err != nil {
			log.Printf("close encounter update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, closeEncounterResponse{
		ID:        encounterID,
		Status:    "closed",
		XPAwarded: enc.XPAwarded,
	})
}

// endEncounterResponse is the shape returned after ending a combat encounter
// and restoring the campaign to its exploration turn queue.
type endEncounterResponse struct {
	CampaignID   string `json:"campaign_id"`
	Status       string `json:"status"`
	Phase        string `json:"phase"`
	CurrentActor string `json:"current_actor"`
}

// endEncounterHandler ends an active combat encounter and restores the campaign
// to its exploration turn queue. Control always returns to the campaign owner
// (DM) after combat so the owner can narrate the next exploration turn. Only
// the owner may call it. If the campaign is not in combat, it returns 409.
func endEncounterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	owner, ok := requireCampaignOwner(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("end encounter campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	if campaign.Phase != "combat" {
		writeError(w, http.StatusConflict, "campaign not in combat")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("end encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	if enc.Status != "closed" {
		if err := dbExec(fmt.Sprintf("UPDATE campaign_encounters SET status='closed' WHERE id=%s AND campaign_id=%s;",
			sq(encounterID), sq(campaignID))); err != nil {
			log.Printf("end encounter close update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	// After combat, control always returns to the DM so the owner can
	// narrate the next exploration turn. The pre_combat_actor field is not
	// used for restoration.
	restoredActor := campaign.Owner

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET phase='exploration', turn_actor=%s WHERE id=%s;",
		sq(restoredActor), sq(campaignID))); err != nil {
		log.Printf("end encounter phase update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, endEncounterResponse{
		CampaignID:   campaignID,
		Status:       campaign.Status,
		Phase:        "exploration",
		CurrentActor: restoredActor,
	})
}
