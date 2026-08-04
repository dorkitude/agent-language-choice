package main

import (
	"encoding/json"
	"net/http"
	"sort"
)

type playEncounter struct {
	ID         string
	Name       string
	Status     string
	Combatants []interface{}

	// Monsters indexes every monster combatant added to this encounter by
	// monster id.
	Monsters map[string]*playMonster

	// MemberCombatants indexes every party member bound to this encounter as
	// a combatant, keyed by member username.
	MemberCombatants map[string]*playMemberCombatant

	// Round and TurnIndex track combat turn authority: TurnIndex is the
	// index into the deterministic initiative-ordered combatant list (see
	// playEncounterOrder) of the currently active combatant. Round starts
	// at 1 and increments each time TurnIndex wraps back to 0.
	Round     int
	TurnIndex int

	// Conditions indexes each combatant's active named conditions by target
	// (a monster id or party member username).
	Conditions map[string][]condition

	// OrderOverride, when non-empty, lists combatant targets (monster ids or
	// member usernames) in an explicitly chosen initiative order, set by a
	// delay action. Any combatant not named here (e.g. bound after the
	// override was set) is appended in the usual initiative-sorted order.
	// Empty/nil means the initiative order is derived purely from
	// Initiative values (see playEncounterOrder).
	OrderOverride []string

	// ReadyActions records ready-action declarations made in this encounter,
	// most recent last.
	ReadyActions []playReadyAction

	// Rewards holds the encounter's XP/loot award once granted by the owner.
	// Nil until POST .../rewards succeeds; awarding twice returns 409.
	Rewards *playEncounterRewards
}

// playEncounterRewards is the deterministic reward record for an encounter.
type playEncounterRewards struct {
	XP   int                 `json:"xp"`
	Loot []playEncounterLoot `json:"loot"`
}

// playEncounterLoot is a single loot line item within an encounter reward.
type playEncounterLoot struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// playReadyAction is a recorded "ready" declaration: a combatant forgoing
// their turn to act later on a named trigger, without altering turn order.
type playReadyAction struct {
	Actor   string `json:"actor"`
	Trigger string `json:"trigger"`
}

// playTurnCombatant is a single entry in an encounter's deterministic
// initiative order, combining monster and party-member combatants.
type playTurnCombatant struct {
	Name       string
	Kind       string
	Initiative int
	Member     string

	// Target is the canonical identifier used to key conditions and to
	// resolve hp: a monster id for a monster, or a username for a player.
	Target string
}

// playEncounterOrder returns enc's combatants in initiative order: highest
// initiative first, ties broken by name. If enc.OrderOverride is set (via a
// delay action), that explicit ordering is used instead, with any combatant
// missing from it (e.g. bound afterward) appended in initiative order.
func playEncounterOrder(enc *playEncounter) []playTurnCombatant {
	byTarget := make(map[string]playTurnCombatant, len(enc.Monsters)+len(enc.MemberCombatants))
	for _, m := range enc.Monsters {
		byTarget[m.ID] = playTurnCombatant{Name: m.Name, Kind: "monster", Initiative: m.Initiative, Target: m.ID}
	}
	for _, mc := range enc.MemberCombatants {
		byTarget[mc.Member] = playTurnCombatant{Name: mc.Name, Kind: "player", Initiative: mc.Initiative, Member: mc.Member, Target: mc.Member}
	}

	sortRemaining := func(remaining []playTurnCombatant) {
		sort.Slice(remaining, func(i, j int) bool {
			if remaining[i].Initiative != remaining[j].Initiative {
				return remaining[i].Initiative > remaining[j].Initiative
			}
			return remaining[i].Name < remaining[j].Name
		})
	}

	if len(enc.OrderOverride) == 0 {
		order := make([]playTurnCombatant, 0, len(byTarget))
		for _, tc := range byTarget {
			order = append(order, tc)
		}
		sortRemaining(order)
		return order
	}

	order := make([]playTurnCombatant, 0, len(byTarget))
	seen := make(map[string]bool, len(byTarget))
	for _, target := range enc.OrderOverride {
		if tc, ok := byTarget[target]; ok && !seen[target] {
			order = append(order, tc)
			seen[target] = true
		}
	}
	var rest []playTurnCombatant
	for target, tc := range byTarget {
		if !seen[target] {
			rest = append(rest, tc)
		}
	}
	sortRemaining(rest)
	return append(order, rest...)
}

type playMemberCombatant struct {
	Member      string
	CharacterID string
	Name        string
	Initiative  int
}

type playMonster struct {
	ID         string
	Name       string
	HPMax      int
	Initiative int
	HPCurrent  int
}

func playEncounterResponse(e *playEncounter) map[string]interface{} {
	combatants := e.Combatants
	if combatants == nil {
		combatants = []interface{}{}
	}
	return map[string]interface{}{
		"id":         e.ID,
		"name":       e.Name,
		"status":     e.Status,
		"combatants": combatants,
	}
}

// handleCreatePlayEncounter starts a campaign-bound encounter from the
// current party state. Only the owner may call this; a duplicate encounter
// id or a campaign already in combat returns 409. The encounter is
// independent from the exploration turn queue until the campaign returns to
// exploration.
func handleCreatePlayEncounter(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "id and name are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may start an encounter")
		return
	}
	if c.InCombat {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "campaign is already in combat")
		return
	}
	if c.Encounters == nil {
		c.Encounters = map[string]*playEncounter{}
	}
	if _, exists := c.Encounters[req.ID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter id already exists")
		return
	}

	enc := &playEncounter{
		ID:         req.ID,
		Name:       req.Name,
		Status:     "active",
		Combatants: []interface{}{},
		Round:      1,
	}
	c.Encounters[enc.ID] = enc
	c.InCombat = true
	c.CurrentActor = c.Owner
	c.Phase = "dm"
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playEncounterResponse(enc))
}

func playMonsterResponse(m *playMonster) map[string]interface{} {
	return map[string]interface{}{
		"monster_id": m.ID,
		"name":       m.Name,
		"hp_max":     m.HPMax,
		"initiative": m.Initiative,
		"hp_current": m.HPCurrent,
	}
}

// handleCreateEncounterMonster adds a deterministic monster combatant to an
// existing encounter. Only the owner may call this; a duplicate monster id
// returns 409.
func handleCreateEncounterMonster(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		MonsterID  string `json:"monster_id"`
		Name       string `json:"name"`
		HPMax      *int   `json:"hp_max"`
		Initiative *int   `json:"initiative"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.MonsterID == "" || req.Name == "" || req.HPMax == nil || req.Initiative == nil {
		writeError(w, http.StatusBadRequest, "monster_id, name, hp_max, and initiative are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may add a monster")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	if enc.Monsters == nil {
		enc.Monsters = map[string]*playMonster{}
	}
	if _, exists := enc.Monsters[req.MonsterID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "monster id already exists")
		return
	}

	m := &playMonster{
		ID:         req.MonsterID,
		Name:       req.Name,
		HPMax:      *req.HPMax,
		Initiative: *req.Initiative,
		HPCurrent:  *req.HPMax,
	}
	enc.Monsters[m.ID] = m
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playMonsterResponse(m))
}

// handleRemoveEncounterMonster removes a monster combatant from an encounter.
// Only the owner may call this.
func handleRemoveEncounterMonster(w http.ResponseWriter, r *http.Request, campaignID, encID, monsterID string) {
	if r.Method != http.MethodDelete {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner may remove a monster")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	if _, exists := enc.Monsters[monsterID]; !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}
	delete(enc.Monsters, monsterID)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{"removed": monsterID})
}

func playMemberCombatantResponse(mc *playMemberCombatant) map[string]interface{} {
	return map[string]interface{}{
		"member":       mc.Member,
		"character_id": mc.CharacterID,
		"name":         mc.Name,
		"initiative":   mc.Initiative,
	}
}

// handleBindEncounterCombatant binds an existing party member to an active
// encounter as a combatant. Only the owner may call this; a member already
// bound to the encounter returns 409, and a member not on the party roster
// returns 400.
func handleBindEncounterCombatant(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Member     string `json:"member"`
		Initiative *int   `json:"initiative"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Member == "" || req.Initiative == nil {
		writeError(w, http.StatusBadRequest, "member and initiative are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may bind a combatant")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	var member *playMember
	for _, m := range c.Members {
		if m.Username == req.Member {
			member = m
			break
		}
	}
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "member is not part of the party")
		return
	}
	if enc.MemberCombatants == nil {
		enc.MemberCombatants = map[string]*playMemberCombatant{}
	}
	if _, exists := enc.MemberCombatants[req.Member]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "member already bound to encounter")
		return
	}

	mc := &playMemberCombatant{
		Member:      req.Member,
		CharacterID: member.CharacterID,
		Name:        member.Name,
		Initiative:  *req.Initiative,
	}
	enc.MemberCombatants[req.Member] = mc
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playMemberCombatantResponse(mc))
}

// handleUnbindEncounterCombatant removes a party member combatant from an
// encounter. Only the owner may call this.
func handleUnbindEncounterCombatant(w http.ResponseWriter, r *http.Request, campaignID, encID, member string) {
	if r.Method != http.MethodDelete {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner may unbind a combatant")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	if _, exists := enc.MemberCombatants[member]; !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "combatant not found")
		return
	}
	delete(enc.MemberCombatants, member)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{"removed": member})
}

func playActiveCombatantResponse(active playTurnCombatant) map[string]interface{} {
	return map[string]interface{}{
		"name":       active.Name,
		"kind":       active.Kind,
		"initiative": active.Initiative,
	}
}

// handleGetEncounterTurn returns the current combatant for encID. Any
// campaign member (including the owner) may call this.
func handleGetEncounterTurn(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner or a member may view the turn state")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	if len(order) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	idx := enc.TurnIndex % len(order)
	round := enc.Round
	active := order[idx]
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"round":      round,
		"turn_index": idx,
		"active":     playActiveCombatantResponse(active),
	})
}

// handleAdvanceEncounterTurn advances encID to the next combatant in
// deterministic initiative order. Only the owner or the current combatant
// (a bound party member whose turn it is) may call this; acting out of turn
// returns 409.
func handleAdvanceEncounterTurn(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner or a member may advance the turn")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	if len(order) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	idx := enc.TurnIndex % len(order)
	current := order[idx]
	isCurrentCombatant := current.Kind == "player" && current.Member == username
	if c.Owner != username && !isCurrentCombatant {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "only the owner or the current combatant may advance the turn")
		return
	}

	next := idx + 1
	if next >= len(order) {
		next = 0
		enc.Round++
	}
	enc.TurnIndex = next
	round := enc.Round
	active := order[next]
	decrementEncounterConditions(enc, active.Target)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"round":      round,
		"turn_index": next,
		"active":     playActiveCombatantResponse(active),
	})
}

// handleDelayEncounterTurn moves the current combatant to a later position
// (new_index) in encID's initiative order. It does not advance whose turn is
// active: the delaying combatant remains the current combatant at their new
// position. Only the owner or the current combatant may call this; an
// out-of-range new_index returns 400.
func handleDelayEncounterTurn(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		NewIndex *int `json:"new_index"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may delay the turn")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	if len(order) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	idx := enc.TurnIndex % len(order)
	current := order[idx]
	isCurrentCombatant := current.Kind == "player" && current.Member == username
	if c.Owner != username && !isCurrentCombatant {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "only the owner or the current combatant may delay the turn")
		return
	}
	if req.NewIndex == nil || *req.NewIndex < 0 || *req.NewIndex >= len(order) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "new_index is out of range")
		return
	}

	remaining := make([]playTurnCombatant, 0, len(order)-1)
	for i, tc := range order {
		if i != idx {
			remaining = append(remaining, tc)
		}
	}
	insertAt := *req.NewIndex
	if insertAt > len(remaining) {
		insertAt = len(remaining)
	}
	newOrder := make([]playTurnCombatant, 0, len(order))
	newOrder = append(newOrder, remaining[:insertAt]...)
	newOrder = append(newOrder, current)
	newOrder = append(newOrder, remaining[insertAt:]...)

	override := make([]string, 0, len(newOrder))
	newIdx := 0
	for i, tc := range newOrder {
		override = append(override, tc.Target)
		if tc.Target == current.Target {
			newIdx = i
		}
	}
	enc.OrderOverride = override
	enc.TurnIndex = newIdx
	playMu.Unlock()
	persistState()

	respOrder := make([]map[string]interface{}, 0, len(newOrder))
	for _, tc := range newOrder {
		respOrder = append(respOrder, playActiveCombatantResponse(tc))
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"order": respOrder,
	})
}

// handleReadyEncounterTurn records the current combatant's ready-action
// trigger. It does not change the turn order. Only the current combatant may
// call this.
func handleReadyEncounterTurn(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Trigger string `json:"trigger"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Trigger == "" {
		writeError(w, http.StatusBadRequest, "trigger is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a member of this campaign may ready an action")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	if len(order) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	idx := enc.TurnIndex % len(order)
	current := order[idx]
	isCurrentCombatant := current.Kind == "player" && current.Member == username
	if !isCurrentCombatant {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "it is not this combatant's turn")
		return
	}

	ready := playReadyAction{Actor: username, Trigger: req.Trigger}
	enc.ReadyActions = append(enc.ReadyActions, ready)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"actor":   ready.Actor,
		"trigger": ready.Trigger,
	})
}

// validCombatActionTypes are the recognized typed combat action verbs.
var validCombatActionTypes = map[string]bool{
	"attack": true,
	"help":   true,
	"dodge":  true,
	"ready":  true,
}

// handleEncounterAction records a typed combat action from the current
// combatant. The action is recorded but does not itself advance the
// encounter turn. Only the current combatant (a bound party member whose
// turn it is) may call this; acting out of turn or with an invalid type
// returns 400/409.
func handleEncounterAction(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Type   string `json:"type"`
		Target string `json:"target"`
		Text   string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validCombatActionTypes[req.Type] {
		writeError(w, http.StatusBadRequest, "type must be one of attack, help, dodge, ready")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a member of this campaign may submit a combat action")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	if len(order) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	idx := enc.TurnIndex % len(order)
	current := order[idx]
	isCurrentCombatant := current.Kind == "player" && current.Member == username
	if !isCurrentCombatant {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "it is not this combatant's turn")
		return
	}

	ev := &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "combat_action",
		Actor:    username,
		Type:     req.Type,
		Target:   req.Target,
		Text:     req.Text,
	}
	c.Events = append(c.Events, ev)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence": ev.Sequence,
		"kind":     ev.Kind,
		"actor":    ev.Actor,
		"type":     ev.Type,
		"target":   ev.Target,
		"text":     ev.Text,
	})
}

// resolveEncounterCombatantHP finds the hp fields for a combatant named
// target within enc, which may be a monster id or a party member's
// username. It returns a pointer to the combatant's current hp (so callers
// can mutate it in place) and the combatant's max hp.
func resolveEncounterCombatantHP(c *playCampaign, enc *playEncounter, target string) (hpCurrent *int, hpMax int, ok bool) {
	if m, exists := enc.Monsters[target]; exists {
		return &m.HPCurrent, m.HPMax, true
	}
	if _, exists := enc.MemberCombatants[target]; exists {
		for _, mem := range c.Members {
			if mem.Username == target {
				return &mem.HPCurrent, mem.HPMax, true
			}
		}
	}
	return nil, 0, false
}

// handleEncounterDamage applies deterministic damage to a combatant in an
// active encounter. Only the owner may call this; hp floors at 0.
func handleEncounterDamage(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Target string `json:"target"`
		Amount *int   `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Amount == nil {
		writeError(w, http.StatusBadRequest, "target and amount are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may apply damage")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	hpCurrent, _, found := resolveEncounterCombatantHP(c, enc, req.Target)
	if !found {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "combatant not found")
		return
	}

	hpBefore := *hpCurrent
	hpAfter := hpBefore - *req.Amount
	if hpAfter < 0 {
		hpAfter = 0
	}
	*hpCurrent = hpAfter
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"target":    req.Target,
		"hp_before": hpBefore,
		"hp_after":  hpAfter,
		"damage":    *req.Amount,
	})
}

// handleEncounterHeal applies deterministic healing to a combatant in an
// active encounter. Only the owner may call this; hp caps at hp_max.
func handleEncounterHeal(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Target string `json:"target"`
		Amount *int   `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Amount == nil {
		writeError(w, http.StatusBadRequest, "target and amount are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may apply healing")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	hpCurrent, hpMax, found := resolveEncounterCombatantHP(c, enc, req.Target)
	if !found {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "combatant not found")
		return
	}

	hpBefore := *hpCurrent
	hpAfter := hpBefore + *req.Amount
	if hpAfter > hpMax {
		hpAfter = hpMax
	}
	*hpCurrent = hpAfter
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"target":    req.Target,
		"hp_before": hpBefore,
		"hp_after":  hpAfter,
		"healing":   *req.Amount,
	})
}

// handlePlayCharacterDamage applies deterministic damage to a party member's
// character outside of an encounter. Only the campaign owner may call this;
// hp floors at 0 and, on reaching 0, the character's status becomes
// "unconscious".

func encounterHasCombatant(enc *playEncounter, target string) bool {
	if _, exists := enc.Monsters[target]; exists {
		return true
	}
	if _, exists := enc.MemberCombatants[target]; exists {
		return true
	}
	return false
}

// decrementEncounterConditions ticks down every remaining_rounds value for
// target's active conditions by one, dropping any condition that reaches
// zero. It is called at the start of target's turn.
func decrementEncounterConditions(enc *playEncounter, target string) {
	conds, exists := enc.Conditions[target]
	if !exists || len(conds) == 0 {
		return
	}
	remaining := make([]condition, 0, len(conds))
	for _, cond := range conds {
		cond.RemainingRounds--
		if cond.RemainingRounds > 0 {
			remaining = append(remaining, cond)
		}
	}
	enc.Conditions[target] = remaining
}

// handleEncounterConditions applies a named condition with a duration to a
// combatant in an active encounter. Only the owner may call this.
func handleEncounterConditions(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Condition == "" {
		writeError(w, http.StatusBadRequest, "target and condition are required")
		return
	}
	if req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be a positive integer")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may apply a condition")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	if !encounterHasCombatant(enc, req.Target) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "target must name a combatant in the encounter")
		return
	}
	if enc.Conditions == nil {
		enc.Conditions = map[string][]condition{}
	}
	enc.Conditions[req.Target] = append(enc.Conditions[req.Target], condition{
		Condition:       req.Condition,
		RemainingRounds: *req.DurationRounds,
	})
	conditions := enc.Conditions[req.Target]
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"target":     req.Target,
		"conditions": conditions,
	})
}

// handleEncounterStatus returns the full state of an encounter: round,
// turn_index, the active combatant, the deterministic initiative order, and
// every combatant's active conditions. Any campaign member may call this.
func handleEncounterStatus(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner or a member may view encounter status")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	order := playEncounterOrder(enc)
	orderOut := make([]map[string]interface{}, 0, len(order))
	for _, oc := range order {
		orderOut = append(orderOut, playActiveCombatantResponse(oc))
	}
	var active map[string]interface{}
	if len(order) > 0 {
		active = playActiveCombatantResponse(order[enc.TurnIndex%len(order)])
	}
	conditionsOut := map[string][]condition{}
	for target, conds := range enc.Conditions {
		conditionsOut[target] = conds
	}
	resp := map[string]interface{}{
		"round":      enc.Round,
		"turn_index": enc.TurnIndex,
		"active":     active,
		"order":      orderOut,
		"conditions": conditionsOut,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func playEncounterRewardsResponse(enc *playEncounter) map[string]interface{} {
	loot := enc.Rewards.Loot
	if loot == nil {
		loot = []playEncounterLoot{}
	}
	return map[string]interface{}{
		"id":   enc.ID,
		"xp":   enc.Rewards.XP,
		"loot": loot,
	}
}

// handleEncounterRewards awards deterministic XP and loot for an encounter.
// Only the owner may call this; a second award for the same encounter
// returns 409.
func handleEncounterRewards(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		XP   int                 `json:"xp"`
		Loot []playEncounterLoot `json:"loot"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may award rewards")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}
	if enc.Rewards != nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "rewards already awarded for this encounter")
		return
	}

	loot := req.Loot
	if loot == nil {
		loot = []playEncounterLoot{}
	}
	enc.Rewards = &playEncounterRewards{XP: req.XP, Loot: loot}
	resp := playEncounterRewardsResponse(enc)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleEncounterClose marks an encounter closed. Only the owner may call
// this. Closing before rewards are awarded is allowed and reports
// xp_awarded: 0.
func handleEncounterClose(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner may close an encounter")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	enc.Status = "closed"
	xpAwarded := 0
	if enc.Rewards != nil {
		xpAwarded = enc.Rewards.XP
	}
	resp := map[string]interface{}{
		"id":         enc.ID,
		"status":     enc.Status,
		"xp_awarded": xpAwarded,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleEncounterEnd closes encID if still active and restores the campaign
// to the exploration phase, resuming the turn queue from the actor it had
// before combat began. Only the owner may call this; a campaign not
// currently in combat returns 409.
func handleEncounterEnd(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only the owner may end an encounter")
		return
	}
	if !c.InCombat {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "campaign is not in combat")
		return
	}
	enc, exists := c.Encounters[encID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	if enc.Status == "active" {
		enc.Status = "closed"
	}
	c.InCombat = false
	c.Phase = "exploration"

	resp := map[string]interface{}{
		"campaign_id":   c.ID,
		"status":        c.Status,
		"phase":         c.Phase,
		"current_actor": c.CurrentActor,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}
