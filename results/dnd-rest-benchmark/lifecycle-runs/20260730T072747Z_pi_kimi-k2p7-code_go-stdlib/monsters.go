package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
)

// encounterCombatant is the unified combatant shape stored in an encounter's
// combatants JSON column. A combatant is either a monster (monster_id set)
// or a bound party member (member set). The omitempty tags keep the two
// shapes distinct on the wire and in storage.
type encounterCombatant struct {
	MonsterID   string `json:"monster_id,omitempty"`
	Name        string `json:"name"`
	HPMax       int    `json:"hp_max,omitempty"`
	Initiative  int    `json:"initiative"`
	HPCurrent   int    `json:"hp_current,omitempty"`
	Member      string `json:"member,omitempty"`
	CharacterID string `json:"character_id,omitempty"`
	Order       int    `json:"order,omitempty"`
}

// encounterMonster is the monster-only view of a combatant. It is used by the
// monster roster endpoints so their response shapes remain unchanged.
type encounterMonster struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
	HPCurrent  int    `json:"hp_current"`
}

// addMonsterRequest binds the payload for adding a monster to an encounter.
type addMonsterRequest struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
}

// addMonsterResponse is the shape returned after adding a monster. The
// current HP is always initialized to the maximum HP.
type addMonsterResponse struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
	HPCurrent  int    `json:"hp_current"`
}

// removeMonsterResponse is the shape returned after removing a monster.
type removeMonsterResponse struct {
	Removed string `json:"removed"`
}

// bindMemberRequest binds the payload for binding a party member to an
// encounter as a combatant.
type bindMemberRequest struct {
	Member     string `json:"member"`
	Initiative int    `json:"initiative"`
}

// bindMemberResponse is the shape returned after binding a party member.
type bindMemberResponse struct {
	Member      string `json:"member"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Initiative  int    `json:"initiative"`
}

// removeMemberResponse is the shape returned after removing a bound member.
type removeMemberResponse struct {
	Removed string `json:"removed"`
}

// encounter is the durable row for a campaign encounter. The combatants and
// loot columns are stored as JSON strings, so they are parsed manually after
// loading.
type encounter struct {
	ID             string `json:"id"`
	Name           string `json:"name"`
	Status         string `json:"status"`
	Combatants     string `json:"combatants"`
	Round          int    `json:"round"`
	TurnIndex      int    `json:"turn_index"`
	XPAwarded      int    `json:"xp_awarded"`
	Loot           string `json:"loot"`
	RewardsAwarded int    `json:"rewards_awarded"`
}

// queryEncounter loads an encounter by id within a campaign. The caller must
// hold dbMu.
func queryEncounter(campaignID, encounterID string) (*encounter, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT id, name, status, combatants, round, turn_index, xp_awarded, loot, rewards_awarded FROM campaign_encounters WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(encounterID), sq(campaignID)))
	if err != nil {
		return nil, false, err
	}
	var encounters []encounter
	if err := json.Unmarshal(out, &encounters); err != nil {
		return nil, false, err
	}
	if len(encounters) == 0 {
		return nil, false, nil
	}
	return &encounters[0], true, nil
}

// parseCombatants parses the stored JSON array in an encounter row into the
// unified combatant roster. An empty or missing combatants string is treated
// as an empty roster.
func parseCombatants(raw string) ([]encounterCombatant, error) {
	if raw == "" {
		return []encounterCombatant{}, nil
	}
	var combatants []encounterCombatant
	if err := json.Unmarshal([]byte(raw), &combatants); err != nil {
		return nil, err
	}
	if combatants == nil {
		return []encounterCombatant{}, nil
	}
	return combatants, nil
}

// updateEncounterCombatants stores the combatant roster back into the
// encounter row. The caller must hold dbMu.
func updateEncounterCombatants(campaignID, encounterID string, combatants []encounterCombatant) error {
	data, err := json.Marshal(combatants)
	if err != nil {
		return err
	}
	return dbExec(fmt.Sprintf("UPDATE campaign_encounters SET combatants=%s WHERE id=%s AND campaign_id=%s;", sq(string(data)), sq(encounterID), sq(campaignID)))
}

// combatantsToMonsters returns the monster-only subset of a unified roster.
func combatantsToMonsters(combatants []encounterCombatant) []encounterMonster {
	monsters := make([]encounterMonster, 0, len(combatants))
	for _, c := range combatants {
		if c.MonsterID == "" {
			continue
		}
		monsters = append(monsters, encounterMonster{
			MonsterID:  c.MonsterID,
			Name:       c.Name,
			HPMax:      c.HPMax,
			HPCurrent:  c.HPCurrent,
			Initiative: c.Initiative,
		})
	}
	return monsters
}

// addEncounterMonsterHandler lets the campaign owner add a monster to an
// encounter. Duplicate monster IDs within the same encounter return 409.
func addEncounterMonsterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req addMonsterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.MonsterID == "" || req.Name == "" || req.HPMax < 1 {
		writeError(w, http.StatusBadRequest, "invalid monster")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("add monster encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("add monster combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	for _, m := range combatantsToMonsters(combatants) {
		if m.MonsterID == req.MonsterID {
			writeError(w, http.StatusConflict, "monster already exists")
			return
		}
	}

	monster := encounterCombatant{
		MonsterID:  req.MonsterID,
		Name:       req.Name,
		HPMax:      req.HPMax,
		HPCurrent:  req.HPMax,
		Initiative: req.Initiative,
	}
	combatants = append(combatants, monster)

	if err := updateEncounterCombatants(campaignID, encounterID, combatants); err != nil {
		log.Printf("add monster update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, addMonsterResponse{
		MonsterID:  monster.MonsterID,
		Name:       monster.Name,
		HPMax:      monster.HPMax,
		Initiative: monster.Initiative,
		HPCurrent:  monster.HPCurrent,
	})
}

// removeEncounterMonsterHandler lets the campaign owner remove a monster from
// an encounter by its monster ID. The removed ID is echoed in the response.
func removeEncounterMonsterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")
	monsterID := r.PathValue("monster_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("remove monster encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("remove monster combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	found := false
	filtered := make([]encounterCombatant, 0, len(combatants))
	for _, m := range combatants {
		if m.MonsterID == monsterID {
			found = true
			continue
		}
		filtered = append(filtered, m)
	}
	if !found {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}

	if err := updateEncounterCombatants(campaignID, encounterID, filtered); err != nil {
		log.Printf("remove monster update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, removeMonsterResponse{Removed: monsterID})
}

// bindEncounterMemberHandler lets the campaign owner bind a party member to
// an active encounter as a combatant. Duplicate members within the encounter
// return 409; members that are not part of the campaign party return 400.
func bindEncounterMemberHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req bindMemberRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Member == "" {
		writeError(w, http.StatusBadRequest, "invalid member")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("bind member encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("bind member combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, c := range combatants {
		if c.Member == req.Member {
			writeError(w, http.StatusConflict, "member already exists")
			return
		}
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("bind member party query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var target *playCampaignMember
	for i := range members {
		if members[i].Username == req.Member {
			target = &members[i]
			break
		}
	}
	if target == nil {
		writeError(w, http.StatusBadRequest, "invalid member")
		return
	}

	combatants = append(combatants, encounterCombatant{
		Member:      req.Member,
		CharacterID: target.CharacterID,
		Name:        target.Name,
		Initiative:  req.Initiative,
	})

	if err := updateEncounterCombatants(campaignID, encounterID, combatants); err != nil {
		log.Printf("bind member update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, bindMemberResponse{
		Member:      req.Member,
		CharacterID: target.CharacterID,
		Name:        target.Name,
		Initiative:  req.Initiative,
	})
}

// removeEncounterMemberHandler lets the campaign owner unbind a party member
// from an encounter. The removed member username is echoed in the response.
func removeEncounterMemberHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")
	member := r.PathValue("member")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("remove member encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("remove member combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	found := false
	filtered := make([]encounterCombatant, 0, len(combatants))
	for _, c := range combatants {
		if c.Member == member {
			found = true
			continue
		}
		filtered = append(filtered, c)
	}
	if !found {
		writeError(w, http.StatusNotFound, "member not found")
		return
	}

	if err := updateEncounterCombatants(campaignID, encounterID, filtered); err != nil {
		log.Printf("remove member update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, removeMemberResponse{Removed: member})
}

// turnActiveCombatant is the public shape of the active combatant returned
// by the encounter turn endpoints. The Kind distinguishes monsters from
// bound party members.
type turnActiveCombatant struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`
	Initiative int    `json:"initiative"`
}

// encounterTurnResponse is the shape returned by the GET and POST encounter
// turn endpoints. It includes the round, turn index, and active combatant.
type encounterTurnResponse struct {
	Round     int                 `json:"round"`
	TurnIndex int                 `json:"turn_index"`
	Active    turnActiveCombatant `json:"active"`
}

// encounterCombatantKind returns the kind label for a combatant.
func encounterCombatantKind(c encounterCombatant) string {
	if c.Member != "" {
		return "player"
	}
	return "monster"
}

// sortedEncounterCombatants returns a deterministic order of the encounter's
// combatants. Explicit order values take priority; otherwise higher initiative
// comes first, and ties are broken by name ascending.
func sortedEncounterCombatants(combatants []encounterCombatant) []encounterCombatant {
	sorted := make([]encounterCombatant, len(combatants))
	copy(sorted, combatants)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].Order != sorted[j].Order {
			return sorted[i].Order > sorted[j].Order
		}
		if sorted[i].Initiative != sorted[j].Initiative {
			return sorted[i].Initiative > sorted[j].Initiative
		}
		return sorted[i].Name < sorted[j].Name
	})
	return sorted
}

// activeEncounterCombatant returns the active combatant for an encounter's
// current round and turn index. If the roster is empty it returns a zero
// combatant and ok=false.
func activeEncounterCombatant(enc *encounter) (encounterCombatant, bool, error) {
	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		return encounterCombatant{}, false, err
	}
	order := sortedEncounterCombatants(combatants)
	if len(order) == 0 {
		return encounterCombatant{}, false, nil
	}
	idx := enc.TurnIndex
	if idx < 0 {
		idx = 0
	}
	if idx >= len(order) {
		idx = idx % len(order)
	}
	return order[idx], true, nil
}

// getEncounterTurnHandler returns the current turn state for an encounter.
// Any campaign owner or member may read it.
func getEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("get encounter turn query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	active, ok, err := activeEncounterCombatant(enc)
	if err != nil {
		log.Printf("get encounter turn parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	resp := encounterTurnResponse{
		Round:     enc.Round,
		TurnIndex: enc.TurnIndex,
	}
	if ok {
		resp.Active = turnActiveCombatant{
			Name:       active.Name,
			Kind:       encounterCombatantKind(active),
			Initiative: active.Initiative,
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

// combatActionRequest binds the payload for a combat action submitted by the
// current encounter combatant.
type combatActionRequest struct {
	Type   string `json:"type"`
	Target string `json:"target"`
	Text   string `json:"text"`
}

// combatActionEvent is the ordered event returned when a combat action is
// recorded. The action does not advance the encounter turn.
type combatActionEvent struct {
	Sequence int    `json:"sequence"`
	Kind     string `json:"kind"`
	Actor    string `json:"actor"`
	Type     string `json:"type"`
	Target   string `json:"target"`
	Text     string `json:"text"`
}

// validCombatActionTypes lists the permitted action types for encounter combat
// actions.
var validCombatActionTypes = map[string]bool{
	"attack": true,
	"help":   true,
	"dodge":  true,
	"ready":  true,
}

// createEncounterActionHandler lets the current encounter combatant submit a
// typed combat action. The action is recorded in the campaign narration log
// but does not advance the encounter turn. Only the current combatant may call
// it; invalid types return 400 and acting out of turn returns 409.
func createEncounterActionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	var req combatActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validCombatActionTypes[req.Type] {
		writeError(w, http.StatusBadRequest, "invalid type")
		return
	}
	if req.Target == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid action")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("encounter action query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	active, ok, err := activeEncounterCombatant(enc)
	if err != nil {
		log.Printf("encounter action active query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || active.Member == "" || active.Member != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("encounter action sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (%s, %d, 'combat_action', %s, %s, %s, %s);",
		sq(campaignID), nextSeq, sq(username), sq(req.Type), sq(req.Target), sq(req.Text))); err != nil {
		log.Printf("encounter action insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, combatActionEvent{
		Sequence: nextSeq,
		Kind:     "combat_action",
		Actor:    username,
		Type:     req.Type,
		Target:   req.Target,
		Text:     req.Text,
	})
}

// advanceEncounterTurnHandler advances the encounter to the next combatant in
// deterministic initiative order. Only the campaign owner or the current active
// combatant (when the active combatant is a bound party member) may call it.
func advanceEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("advance encounter turn campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("advance encounter turn query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("advance encounter turn parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	order := sortedEncounterCombatants(combatants)
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	idx := enc.TurnIndex
	if idx < 0 {
		idx = 0
	}
	if idx >= len(order) {
		idx = idx % len(order)
	}
	active := order[idx]

	isOwner := username == campaign.Owner
	isCurrentCombatant := active.Member != "" && active.Member == username
	if !isOwner && !isCurrentCombatant {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	newRound := enc.Round
	newTurnIndex := enc.TurnIndex + 1
	if newTurnIndex >= len(order) {
		newTurnIndex = 0
		newRound++
	}

	nextActive := order[newTurnIndex]
	targetKey := encounterConditionTarget(nextActive)

	updateSQL := fmt.Sprintf("UPDATE campaign_encounters SET round=%d, turn_index=%d WHERE id=%s AND campaign_id=%s; UPDATE campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE encounter_id=%s AND campaign_id=%s AND target=%s; DELETE FROM campaign_encounter_conditions WHERE encounter_id=%s AND campaign_id=%s AND target=%s AND remaining_rounds <= 0;",
		newRound, newTurnIndex, sq(encounterID), sq(campaignID), sq(encounterID), sq(campaignID), sq(targetKey), sq(encounterID), sq(campaignID), sq(targetKey))
	if err := dbExec(updateSQL); err != nil {
		log.Printf("advance encounter turn update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, encounterTurnResponse{
		Round:     newRound,
		TurnIndex: newTurnIndex,
		Active: turnActiveCombatant{
			Name:       nextActive.Name,
			Kind:       encounterCombatantKind(nextActive),
			Initiative: nextActive.Initiative,
		},
	})
}

// damageRequest binds the payload for applying damage to an encounter
// combatant. The target is either a monster_id or a bound member username.
type damageRequest struct {
	Target string `json:"target"`
	Amount int    `json:"amount"`
}

// damageResponse is the shape returned after applying damage.
type damageResponse struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Damage   int    `json:"damage"`
}

// healRequest binds the payload for healing an encounter combatant. The target
// is either a monster_id or a bound member username.
type healRequest struct {
	Target string `json:"target"`
	Amount int    `json:"amount"`
}

// healResponse is the shape returned after healing.
type healResponse struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Healing  int    `json:"healing"`
}

// updateMemberHP updates the canonical HP for a bound party member in
// play_campaign_members. It returns the HP before and after applying the delta
// with the given maximum cap. It also transitions the member's life-state:
// reaching 0 HP becomes unconscious, while any positive HP restores the
// character to conscious and clears death-save counters. The caller must
// hold dbMu.
func updateMemberHP(campaignID, username string, delta int, capAtMax bool) (int, int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;",
		sq(campaignID), sq(username)))
	if err != nil {
		return 0, 0, err
	}
	var rows []struct {
		HPCurrent int    `json:"hp_current"`
		HPMax     int    `json:"hp_max"`
		Status    string `json:"status"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, 0, err
	}
	if len(rows) == 0 {
		return 0, 0, fmt.Errorf("target not found")
	}
	before := rows[0].HPCurrent
	after := before + delta
	if after < 0 {
		after = 0
	}
	if capAtMax && after > rows[0].HPMax {
		after = rows[0].HPMax
	}
	status := rows[0].Status
	successes := 0
	failures := 0
	if after > 0 {
		status = "conscious"
		successes = 0
		failures = 0
	} else if after == 0 && status == "conscious" {
		status = "unconscious"
		successes = 0
		failures = 0
	}
	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET hp_current=%d, status=%s, death_saves_successes=%d, death_saves_failures=%d WHERE campaign_id=%s AND username=%s;",
		after, sq(status), successes, failures, sq(campaignID), sq(username))); err != nil {
		return 0, 0, err
	}
	return before, after, nil
}

// applyDamage reduces the target combatant's HP by amount, flooring at 0. It
// mutates the monster combatant in place or updates the member's canonical
// HP row. The caller must hold dbMu.
func applyDamage(campaignID, encounterID, target string, amount int, combatants []encounterCombatant) (int, int, error) {
	for i := range combatants {
		c := &combatants[i]
		if c.MonsterID != "" && c.MonsterID == target {
			before := c.HPCurrent
			after := before - amount
			if after < 0 {
				after = 0
			}
			c.HPCurrent = after
			return before, after, nil
		}
		if c.Member != "" && c.Member == target {
			return updateMemberHP(campaignID, c.Member, -amount, false)
		}
	}
	return 0, 0, fmt.Errorf("target not found")
}

// applyHeal increases the target combatant's HP by amount, capping at hp_max.
// It mutates the monster combatant in place or updates the member's canonical
// HP row. The caller must hold dbMu.
func applyHeal(campaignID, encounterID, target string, amount int, combatants []encounterCombatant) (int, int, error) {
	for i := range combatants {
		c := &combatants[i]
		if c.MonsterID != "" && c.MonsterID == target {
			before := c.HPCurrent
			after := before + amount
			if after > c.HPMax {
				after = c.HPMax
			}
			c.HPCurrent = after
			return before, after, nil
		}
		if c.Member != "" && c.Member == target {
			return updateMemberHP(campaignID, c.Member, amount, true)
		}
	}
	return 0, 0, fmt.Errorf("target not found")
}

// damageEncounterHandler lets the campaign owner apply deterministic damage to
// an encounter combatant. Only the owner may call it. HP floors at 0.
func damageEncounterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req damageRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "invalid target")
		return
	}
	if req.Amount <= 0 {
		writeError(w, http.StatusBadRequest, "invalid amount")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("damage encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("damage combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	hpBefore, hpAfter, err := applyDamage(campaignID, encounterID, req.Target, req.Amount, combatants)
	if err != nil {
		if err.Error() == "target not found" {
			writeError(w, http.StatusBadRequest, "invalid target")
			return
		}
		log.Printf("damage apply error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := updateEncounterCombatants(campaignID, encounterID, combatants); err != nil {
		log.Printf("damage update combatants error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, damageResponse{
		Target:   req.Target,
		HPBefore: hpBefore,
		HPAfter:  hpAfter,
		Damage:   req.Amount,
	})
}

// healEncounterHandler lets the campaign owner apply deterministic healing to
// an encounter combatant. Only the owner may call it. HP caps at hp_max.
func healEncounterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req healRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "invalid target")
		return
	}
	if req.Amount <= 0 {
		writeError(w, http.StatusBadRequest, "invalid amount")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("heal encounter query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("heal combatants parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	hpBefore, hpAfter, err := applyHeal(campaignID, encounterID, req.Target, req.Amount, combatants)
	if err != nil {
		if err.Error() == "target not found" {
			writeError(w, http.StatusBadRequest, "invalid target")
			return
		}
		log.Printf("heal apply error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := updateEncounterCombatants(campaignID, encounterID, combatants); err != nil {
		log.Printf("heal update combatants error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, healResponse{
		Target:   req.Target,
		HPBefore: hpBefore,
		HPAfter:  hpAfter,
		Healing:  req.Amount,
	})
}

// applyDesiredOrder updates the Order field on the raw combatant roster so
// that sortedEncounterCombatants returns the supplied desired order. Order
// values are assigned position-relative, with earlier positions receiving
// higher values so they sort first.
func applyDesiredOrder(raw []encounterCombatant, desired []encounterCombatant) {
	pos := make(map[string]int)
	for i, c := range desired {
		pos[encounterConditionTarget(c)] = i
	}
	for i := range raw {
		key := encounterConditionTarget(raw[i])
		if p, ok := pos[key]; ok {
			raw[i].Order = len(desired) - p
		}
	}
}

// delayTurnRequest binds the payload for delaying a combatant's turn.
type delayTurnRequest struct {
	NewIndex int `json:"new_index"`
}

// delayTurnResponse is the shape returned after a successful delay. It
// contains the encounter's turn state and the full new initiative order.
type delayTurnResponse struct {
	Round     int                   `json:"round"`
	TurnIndex int                   `json:"turn_index"`
	Active    turnActiveCombatant   `json:"active"`
	Order     []turnActiveCombatant `json:"order"`
}

// delayEncounterTurnHandler lets the current encounter combatant (or the
// campaign owner) move the current combatant to a later position in the
// initiative order. The request supplies the target index in the new order.
// The delayed combatant remains the active turn actor, so the turn index
// follows them to their new position. Reordering to a non-later or
// out-of-bounds index returns 400.
func delayEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	var req delayTurnRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("delay encounter turn campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("delay encounter turn query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	combatants, err := parseCombatants(enc.Combatants)
	if err != nil {
		log.Printf("delay encounter turn parse error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	order := sortedEncounterCombatants(combatants)
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	idx := enc.TurnIndex
	if idx < 0 {
		idx = 0
	}
	if idx >= len(order) {
		idx = idx % len(order)
	}
	active := order[idx]

	isOwner := username == campaign.Owner
	isCurrentCombatant := active.Member != "" && active.Member == username
	if !isOwner && !isCurrentCombatant {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	if req.NewIndex <= idx || req.NewIndex >= len(order) {
		writeError(w, http.StatusBadRequest, "invalid index")
		return
	}

	// Build the desired order by removing the current combatant and inserting
	// them at the requested index. The delayed combatant remains the active
	// turn actor, so the turn index follows them to their new position.
	desired := make([]encounterCombatant, 0, len(order))
	desired = append(desired, order[:idx]...)
	desired = append(desired, order[idx+1:req.NewIndex+1]...)
	desired = append(desired, active)
	desired = append(desired, order[req.NewIndex+1:]...)

	applyDesiredOrder(combatants, desired)

	if err := updateEncounterCombatants(campaignID, encounterID, combatants); err != nil {
		log.Printf("delay encounter turn update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_encounters SET turn_index=%d WHERE id=%s AND campaign_id=%s;",
		req.NewIndex, sq(encounterID), sq(campaignID))); err != nil {
		log.Printf("delay encounter turn index update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	newActive := desired[req.NewIndex]
	respOrder := make([]turnActiveCombatant, 0, len(desired))
	for _, c := range desired {
		respOrder = append(respOrder, turnActiveCombatant{
			Name:       c.Name,
			Kind:       encounterCombatantKind(c),
			Initiative: c.Initiative,
		})
	}

	writeJSON(w, http.StatusOK, delayTurnResponse{
		Round:     enc.Round,
		TurnIndex: req.NewIndex,
		Active: turnActiveCombatant{
			Name:       newActive.Name,
			Kind:       encounterCombatantKind(newActive),
			Initiative: newActive.Initiative,
		},
		Order: respOrder,
	})
}

// readyActionRequest binds the payload for readying an action.
type readyActionRequest struct {
	Trigger string `json:"trigger"`
}

// readyActionResponse is the shape returned after a successful ready action.
type readyActionResponse struct {
	Actor   string `json:"actor"`
	Trigger string `json:"trigger"`
}

// readyEncounterTurnHandler lets the current encounter combatant declare a
// ready action with a trigger. Only the current combatant may call it; the
// owner may not. The ready action is recorded in the narration log but does
// not change the initiative order or advance the turn.
func readyEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	encounterID := r.PathValue("enc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	var req readyActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Trigger == "" {
		writeError(w, http.StatusBadRequest, "invalid trigger")
		return
	}

	enc, ok, err := queryEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("ready encounter turn query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	active, ok, err := activeEncounterCombatant(enc)
	if err != nil {
		log.Printf("ready encounter turn active query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || active.Member == "" || active.Member != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("ready encounter turn sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (%s, %d, 'combat_action', %s, 'ready', %s, %s);",
		sq(campaignID), nextSeq, sq(username), sq(""), sq(req.Trigger))); err != nil {
		log.Printf("ready encounter turn insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, readyActionResponse{
		Actor:   username,
		Trigger: req.Trigger,
	})
}
