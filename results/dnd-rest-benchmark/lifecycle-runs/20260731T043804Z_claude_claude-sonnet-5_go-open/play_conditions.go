package main

import (
	"net/http"
	"sync"
)

type playCondition struct {
	ID              int64  `json:"-"`
	CampaignID      string `json:"-"`
	EncounterID     string `json:"-"`
	Target          string `json:"-"`
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// playConditionsMu guards playConditions, the in-memory index mirroring the
// play_conditions table. It is keyed by campaign id, then encounter id, then
// target id (a monster's monster_id or a bound combatant's member username).
var (
	playConditionsMu sync.Mutex
	playConditions   = map[string]map[string]map[string][]*playCondition{}
)

// encounterTargetExists reports whether target names a monster or bound
// combatant within an encounter. Callers must hold playMonstersMu and
// playCombatantsMu.
func encounterTargetExists(campaignID, encID, target string) bool {
	if _, exists := playMonsters[campaignID][encID][target]; exists {
		return true
	}
	_, exists := playCombatants[campaignID][encID][target]
	return exists
}

// decrementConditionsOnTurnStart decrements the remaining-rounds counter for
// each of target's active conditions, removing any that reach zero. Callers
// must hold playConditionsMu.
func decrementConditionsOnTurnStart(campaignID, encID, target string) error {
	conditions := playConditions[campaignID][encID][target]
	if len(conditions) == 0 {
		return nil
	}

	remaining := conditions[:0]
	for _, c := range conditions {
		c.RemainingRounds--
		if c.RemainingRounds <= 0 {
			if err := deletePlayConditionFromDB(c.ID); err != nil {
				return err
			}
			continue
		}
		if err := updatePlayConditionRemainingInDB(c.ID, c.RemainingRounds); err != nil {
			return err
		}
		remaining = append(remaining, c)
	}

	if len(remaining) == 0 {
		delete(playConditions[campaignID][encID], target)
	} else {
		playConditions[campaignID][encID][target] = remaining
	}
	return nil
}

type addPlayConditionRequest struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds *int   `json:"duration_rounds"`
}

// addPlayConditionHandler lets the owning dm apply a named condition to an
// encounter combatant for a fixed number of rounds. Only the owner may call
// this.
func addPlayConditionHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req addPlayConditionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "target is required")
		return
	}
	if req.Condition == "" {
		writeError(w, http.StatusBadRequest, "condition is required")
		return
	}
	if req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be a positive integer")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may apply a condition")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	if _, exists := playEncounters[campaignID][encID]; !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	playMonstersMu.Lock()
	defer playMonstersMu.Unlock()
	playCombatantsMu.Lock()
	defer playCombatantsMu.Unlock()

	if !encounterTargetExists(campaignID, encID, req.Target) {
		writeError(w, http.StatusBadRequest, "target must name a combatant in the encounter")
		return
	}

	playConditionsMu.Lock()
	defer playConditionsMu.Unlock()

	cond := &playCondition{
		CampaignID:      campaignID,
		EncounterID:     encID,
		Target:          req.Target,
		Condition:       req.Condition,
		RemainingRounds: *req.DurationRounds,
	}
	if err := insertPlayConditionToDB(cond); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save condition")
		return
	}

	if playConditions[campaignID] == nil {
		playConditions[campaignID] = map[string]map[string][]*playCondition{}
	}
	if playConditions[campaignID][encID] == nil {
		playConditions[campaignID][encID] = map[string][]*playCondition{}
	}
	playConditions[campaignID][encID][req.Target] = append(playConditions[campaignID][encID][req.Target], cond)

	writeJSON(w, http.StatusCreated, map[string]any{
		"target":     req.Target,
		"conditions": playConditions[campaignID][encID][req.Target],
	})
}

// getEncounterStatusHandler returns the full state of an encounter, including
// its turn order and any active conditions. Any owner or member of the
// campaign may call it.
func getEncounterStatusHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
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

	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	enc, exists := playEncounters[campaignID][encID]
	if !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	playMonstersMu.Lock()
	defer playMonstersMu.Unlock()
	playCombatantsMu.Lock()
	defer playCombatantsMu.Unlock()

	order := effectiveTurnOrder(enc, campaignID, encID)

	orderOut := make([]map[string]any, 0, len(order))
	for _, cb := range order {
		orderOut = append(orderOut, map[string]any{
			"name":       cb.Name,
			"kind":       cb.Kind,
			"initiative": cb.Initiative,
		})
	}

	var active any
	if len(order) > 0 {
		activeCombatant := order[enc.TurnIndex%len(order)]
		active = map[string]any{
			"name":       activeCombatant.Name,
			"kind":       activeCombatant.Kind,
			"initiative": activeCombatant.Initiative,
		}
	}

	playConditionsMu.Lock()
	defer playConditionsMu.Unlock()

	conditionsOut := map[string][]playCondition{}
	for target, conds := range playConditions[campaignID][encID] {
		if len(conds) == 0 {
			continue
		}
		list := make([]playCondition, 0, len(conds))
		for _, cond := range conds {
			list = append(list, *cond)
		}
		conditionsOut[target] = list
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         enc.ID,
		"name":       enc.Name,
		"status":     enc.Status,
		"round":      enc.Round,
		"turn_index": enc.TurnIndex,
		"active":     active,
		"order":      orderOut,
		"conditions": conditionsOut,
	})
}
