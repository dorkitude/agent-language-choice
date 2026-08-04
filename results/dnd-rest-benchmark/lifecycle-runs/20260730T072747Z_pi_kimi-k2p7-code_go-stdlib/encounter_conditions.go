package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// dbEncounterCondition is the raw row shape for campaign encounter conditions.
type dbEncounterCondition struct {
	Target          string `json:"target"`
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// queryEncounterConditions loads all conditions for a campaign encounter.
// The caller must hold dbMu.
func queryEncounterConditions(campaignID, encounterID string) ([]dbEncounterCondition, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT target, \"condition\", remaining_rounds FROM campaign_encounter_conditions WHERE encounter_id=%s AND campaign_id=%s ORDER BY id;", sq(encounterID), sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var conds []dbEncounterCondition
	if err := json.Unmarshal(out, &conds); err != nil {
		return nil, err
	}
	return conds, nil
}

// encounterConditionTarget returns the identifier used to target a combatant
// with conditions. Bound members use their username; monsters use monster_id.
func encounterConditionTarget(c encounterCombatant) string {
	if c.Member != "" {
		return c.Member
	}
	return c.MonsterID
}

// addEncounterConditionHandler lets the campaign owner apply a named condition
// to an encounter combatant. The target must be a monster_id or bound member
// username present in the encounter roster. It returns the target's current
// conditions with HTTP 201.
func addEncounterConditionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req conditionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Condition == "" || req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "invalid condition")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("add encounter condition query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("add encounter condition parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	found := false
	for _, c := range combatants {
		if encounterConditionTarget(c) == req.Target {
			found = true
			break
		}
	}
	if !found {
		writeError(w, http.StatusBadRequest, "invalid target")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_encounter_conditions (encounter_id, campaign_id, target, \"condition\", remaining_rounds) VALUES (%s, %s, %s, %s, %d);",
		sq(encounterID), sq(campaignID), sq(req.Target), sq(req.Condition), req.DurationRounds)); err != nil {
		log.Printf("add encounter condition insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT \"condition\", remaining_rounds FROM campaign_encounter_conditions WHERE encounter_id=%s AND campaign_id=%s AND target=%s ORDER BY id;",
		sq(encounterID), sq(campaignID), sq(req.Target)))
	if err != nil {
		log.Printf("add encounter condition list error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var conds []Condition
	if err := json.Unmarshal(out, &conds); err != nil {
		log.Printf("add encounter condition unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, conditionsResponse{
		Target:     req.Target,
		Conditions: conds,
	})
}

// encounterStatusResponse is the full encounter state returned by the status
// endpoint. It includes the initiative order, active combatant, and a
// conditions map keyed by combatant target.
type encounterStatusResponse struct {
	Round      int                    `json:"round"`
	TurnIndex  int                    `json:"turn_index"`
	Active     turnActiveCombatant    `json:"active"`
	Order      []turnActiveCombatant  `json:"order"`
	Conditions map[string][]Condition `json:"conditions"`
}

// getEncounterStatusHandler returns the full encounter state including the
// current round, turn index, active combatant, initiative order, and a
// conditions map for every combatant in the encounter.
func getEncounterStatusHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("get encounter status query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("get encounter status parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	order := sortedEncounterCombatants(combatants)

	resp := encounterStatusResponse{
		Round:      enc.Round,
		TurnIndex:  enc.TurnIndex,
		Order:      []turnActiveCombatant{},
		Conditions: map[string][]Condition{},
	}

	if len(order) > 0 {
		idx := enc.TurnIndex
		if idx < 0 {
			idx = 0
		}
		if idx >= len(order) {
			idx = idx % len(order)
		}
		active := order[idx]
		resp.Active = turnActiveCombatant{
			Name:       active.Name,
			Kind:       encounterCombatantKind(active),
			Initiative: active.Initiative,
		}
		for _, c := range order {
			resp.Order = append(resp.Order, turnActiveCombatant{
				Name:       c.Name,
				Kind:       encounterCombatantKind(c),
				Initiative: c.Initiative,
			})
		}
	}

	condRows, err := queryEncounterConditions(campaignID, encounterID)
	if err != nil {
		log.Printf("get encounter status conditions query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	for _, c := range order {
		resp.Conditions[encounterConditionTarget(c)] = []Condition{}
	}
	for _, row := range condRows {
		resp.Conditions[row.Target] = append(resp.Conditions[row.Target], Condition{
			Condition:       row.Condition,
			RemainingRounds: row.RemainingRounds,
		})
	}

	writeJSON(w, http.StatusOK, resp)
}
