package main

import (
	"fmt"
	"net/http"
	"sort"
	"strings"
	"sync"
)

type playCampaign struct {
	ID                 string `json:"id"`
	Name               string `json:"name"`
	Owner              string `json:"owner"`
	Status             string `json:"status"`
	MaxPlayers         int    `json:"max_players"`
	CurrentActor       string `json:"-"`
	TurnNumber         int    `json:"-"`
	NudgeCount         int    `json:"-"`
	Story              string `json:"-"`
	DMNotes            string `json:"-"`
	CurrentSceneID     string `json:"-"`
	CurrentLocationID  string `json:"-"`
	CurrentEncounterID string `json:"-"`
	PreCombatActor     string `json:"-"`
	Phase              string `json:"-"`
}

// playCampaignsMu guards playCampaigns, the in-memory index mirroring the
// play_campaigns table.
var (
	playCampaignsMu sync.Mutex
	playCampaigns   = map[string]*playCampaign{}
)

type playMember struct {
	CampaignID         string `json:"-"`
	Username           string `json:"-"`
	CharacterID        string `json:"character_id"`
	Name               string `json:"name"`
	Class              string `json:"class"`
	JoinOrder          int    `json:"-"`
	HPCurrent          int    `json:"-"`
	HPMax              int    `json:"-"`
	Status             string `json:"-"`
	DeathSaveSuccesses int    `json:"-"`
	DeathSaveFailures  int    `json:"-"`
	Owner              string `json:"-"`
	Race               string `json:"-"`
	Background         string `json:"-"`
	Level              int    `json:"-"`
	ConScore           int    `json:"-"`
	StrScore           int    `json:"-"`
	DexScore           int    `json:"-"`
	IntScore           int    `json:"-"`
	WisScore           int    `json:"-"`
	ChaScore           int    `json:"-"`
}

// abilityScoreByName returns m's ability score for the given lowercase
// ability abbreviation (str, dex, con, int, wis, cha), plus whether it was
// recognized.
func abilityScoreByName(m *playMember, ability string) (int, bool) {
	switch ability {
	case "str":
		return m.StrScore, true
	case "dex":
		return m.DexScore, true
	case "con":
		return m.ConScore, true
	case "int":
		return m.IntScore, true
	case "wis":
		return m.WisScore, true
	case "cha":
		return m.ChaScore, true
	default:
		return 0, false
	}
}

// validSkills is the set of 5e skill names accepted by the skill-check
// endpoint.
var validSkills = map[string]bool{
	"acrobatics":      true,
	"animal-handling": true,
	"arcana":          true,
	"athletics":       true,
	"deception":       true,
	"history":         true,
	"insight":         true,
	"intimidation":    true,
	"investigation":   true,
	"medicine":        true,
	"nature":          true,
	"perception":      true,
	"performance":     true,
	"persuasion":      true,
	"religion":        true,
	"sleight-of-hand": true,
	"stealth":         true,
	"survival":        true,
}

// playMemberOwner returns m's effective character owner, falling back to
// the joining Username when Owner has never been explicitly claimed or
// transferred.
func playMemberOwner(m *playMember) string {
	if m.Owner != "" {
		return m.Owner
	}
	return m.Username
}

// memberConscious is the default status for a character with hp_current > 0.
const memberConscious = "conscious"

// defaultMemberHP is the starting hit points assigned to a character when it
// joins a play campaign. No earlier stage establishes character HP, so rest
// turns operate against this fixed baseline.
const defaultMemberHP = 20

// playMembersMu guards playMembers, the in-memory index mirroring the
// play_members table. It is keyed by campaign id, then username.
var (
	playMembersMu sync.Mutex
	playMembers   = map[string]map[string]*playMember{}
)

type playNarration struct {
	CampaignID string `json:"-"`
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Actor      string `json:"actor"`
	Type       string `json:"type,omitempty"`
	Target     string `json:"target,omitempty"`
	Text       string `json:"text"`
}

// playNarrationsMu guards playNarrations, the in-memory index mirroring the
// play_narrations table. It is keyed by campaign id, holding events in
// append-only sequence order starting at 1.
var (
	playNarrationsMu sync.Mutex
	playNarrations   = map[string][]*playNarration{}
)

type playScene struct {
	CampaignID string `json:"-"`
	ID         string `json:"id"`
	Name       string `json:"name"`
	Status     string `json:"status"`
}

// playScenesMu guards playScenes, the in-memory index mirroring the
// play_scenes table. It is keyed by campaign id, then scene id.
var (
	playScenesMu sync.Mutex
	playScenes   = map[string]map[string]*playScene{}
)

type playLocation struct {
	CampaignID string `json:"-"`
	ID         string `json:"id"`
	Name       string `json:"name"`
}

// playLocationsMu guards playLocations, the in-memory index mirroring the
// play_locations table. It is keyed by campaign id, then location id.
var (
	playLocationsMu sync.Mutex
	playLocations   = map[string]map[string]*playLocation{}
)

type playConnection struct {
	CampaignID  string `json:"-"`
	FromID      string `json:"from_id"`
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// playConnectionsMu guards playConnections, the in-memory index mirroring the
// play_connections table. It is keyed by campaign id, then a list of the
// campaign's connections in creation order.
var (
	playConnectionsMu sync.Mutex
	playConnections   = map[string][]*playConnection{}
)

type playEncounter struct {
	CampaignID string `json:"-"`
	ID         string `json:"id"`
	Name       string `json:"name"`
	Status     string `json:"status"`
	Round      int    `json:"-"`
	TurnIndex  int    `json:"-"`
	// OrderOverride, when non-empty, lists combatant target ids (monster ids
	// or member usernames) in the order a delayed turn placed them, taking
	// priority over the initiative-sorted order for any ids it names.
	// Combatants not named in it fall back to initiative order, appended
	// after the named ones.
	OrderOverride []string `json:"-"`
	// XPAwarded holds the xp granted by the encounter's reward record, or 0
	// if rewards have not yet been awarded. It is reported on close.
	XPAwarded int `json:"-"`
}

// playEncountersMu guards playEncounters, the in-memory index mirroring the
// play_encounters table. It is keyed by campaign id, then encounter id.
var (
	playEncountersMu sync.Mutex
	playEncounters   = map[string]map[string]*playEncounter{}
)

type playMonster struct {
	CampaignID  string `json:"-"`
	EncounterID string `json:"-"`
	MonsterID   string `json:"monster_id"`
	Name        string `json:"name"`
	HPMax       int    `json:"hp_max"`
	HPCurrent   int    `json:"hp_current"`
	Initiative  int    `json:"initiative"`
}

// playMonstersMu guards playMonsters, the in-memory index mirroring the
// play_monsters table. It is keyed by campaign id, then encounter id, then
// monster id.
var (
	playMonstersMu sync.Mutex
	playMonsters   = map[string]map[string]map[string]*playMonster{}
)

type playCombatant struct {
	CampaignID  string `json:"-"`
	EncounterID string `json:"-"`
	Member      string `json:"member"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Initiative  int    `json:"initiative"`
}

// playCombatantsMu guards playCombatants, the in-memory index mirroring the
// play_combatants table. It is keyed by campaign id, then encounter id, then
// member username.
var (
	playCombatantsMu sync.Mutex
	playCombatants   = map[string]map[string]map[string]*playCombatant{}
)

// authenticatedActor extracts the username from a "Bearer session-<username>"
// Authorization header. It returns httpStatus 401 if the header is missing
// or malformed, 403 if the header names an unknown user, and 0 on success.
func authenticatedActor(r *http.Request) (*user, int) {
	authHeader := r.Header.Get("Authorization")
	const prefix = "Bearer session-"
	if !strings.HasPrefix(authHeader, prefix) {
		return nil, http.StatusUnauthorized
	}
	username := strings.TrimPrefix(authHeader, prefix)
	if username == "" {
		return nil, http.StatusUnauthorized
	}

	usersMu.Lock()
	u, exists := users[username]
	usersMu.Unlock()
	if !exists {
		return nil, http.StatusForbidden
	}
	return u, 0
}

// requireActor wraps authenticatedActor for handlers, writing the standard
// "missing or invalid credentials" error and returning ok=false on failure.
func requireActor(w http.ResponseWriter, r *http.Request) (*user, bool) {
	actor, status := authenticatedActor(r)
	if status != 0 {
		writeError(w, status, "missing or invalid credentials")
		return nil, false
	}
	return actor, true
}

// requirePlayCampaign looks up campaignID in playCampaigns, writing a 404 and
// returning ok=false if it doesn't exist. Callers must hold playCampaignsMu.
func requirePlayCampaign(w http.ResponseWriter, campaignID string) (*playCampaign, bool) {
	c, exists := playCampaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return nil, false
	}
	return c, true
}

// isPlayMember reports whether username has a membership in campaignID. It
// takes playMembersMu itself, so callers must not already hold it.
func isPlayMember(campaignID, username string) bool {
	playMembersMu.Lock()
	defer playMembersMu.Unlock()
	_, ok := playMembers[campaignID][username]
	return ok
}

// sortedPlayMembers returns campaignID's members ordered by JoinOrder (the
// same order players joined the lobby in, which double as turn order once
// the campaign starts). It takes playMembersMu itself, so callers must not
// already hold it.
func sortedPlayMembers(campaignID string) []*playMember {
	playMembersMu.Lock()
	members := make([]*playMember, 0, len(playMembers[campaignID]))
	for _, m := range playMembers[campaignID] {
		members = append(members, m)
	}
	playMembersMu.Unlock()
	sort.Slice(members, func(i, j int) bool {
		return members[i].JoinOrder < members[j].JoinOrder
	})
	return members
}

type createPlayCampaignRequest struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	MaxPlayers *int   `json:"max_players"`
}

func createPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if actor.Role != "dm" {
		writeError(w, http.StatusForbidden, "only a dm may create a play campaign")
		return
	}

	var req createPlayCampaignRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.MaxPlayers == nil || *req.MaxPlayers <= 0 {
		writeError(w, http.StatusBadRequest, "max_players must be a positive integer")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, exists := playCampaigns[req.ID]; exists {
		writeError(w, http.StatusConflict, "play campaign id already exists")
		return
	}

	c := &playCampaign{
		ID:         req.ID,
		Name:       req.Name,
		Owner:      actor.Username,
		Status:     "lobby",
		MaxPlayers: *req.MaxPlayers,
	}
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}
	playCampaigns[c.ID] = c

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":          c.ID,
		"name":        c.Name,
		"owner":       c.Owner,
		"status":      c.Status,
		"max_players": c.MaxPlayers,
	})
}

type joinPlayCampaignRequest struct {
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

func joinPlayCampaignHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if actor.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may join a play campaign")
		return
	}

	var req joinPlayCampaignRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Class == "" {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	members := playMembers[campaignID]
	if _, alreadyMember := members[actor.Username]; alreadyMember {
		writeError(w, http.StatusConflict, "player already has a membership in this campaign")
		return
	}
	if len(members) >= c.MaxPlayers {
		writeError(w, http.StatusConflict, "play campaign is full")
		return
	}
	for _, m := range members {
		if m.CharacterID == req.CharacterID {
			writeError(w, http.StatusConflict, "character id is already in use in this campaign")
			return
		}
	}

	m := &playMember{
		CampaignID:  campaignID,
		Username:    actor.Username,
		CharacterID: req.CharacterID,
		Name:        req.Name,
		Class:       req.Class,
		JoinOrder:   len(members),
		HPCurrent:   defaultMemberHP,
		HPMax:       defaultMemberHP,
		Status:      memberConscious,
		Level:       1,
	}
	if err := savePlayMemberToDB(m); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save membership")
		return
	}
	if playMembers[campaignID] == nil {
		playMembers[campaignID] = map[string]*playMember{}
	}
	playMembers[campaignID][actor.Username] = m

	currencyMu.Lock()
	err := initCurrencyForMember(campaignID, req.CharacterID)
	currencyMu.Unlock()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to initialize currency")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"username":     actor.Username,
		"character_id": m.CharacterID,
		"name":         m.Name,
		"class":        m.Class,
	})
}

func startPlayCampaignHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may start this play campaign")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	members := playMembers[campaignID]
	if c.Status != "lobby" || len(members) < 2 {
		writeError(w, http.StatusConflict, "play campaign cannot be started")
		return
	}

	var first *playMember
	for _, m := range members {
		if first == nil || m.JoinOrder < first.JoinOrder {
			first = m
		}
	}

	c.Status = "active"
	c.CurrentActor = first.Username
	c.TurnNumber = 1
	c.Phase = "player"
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":            c.ID,
		"status":        c.Status,
		"current_actor": c.CurrentActor,
		"turn_number":   c.TurnNumber,
	})
}

type createNarrationRequest struct {
	Text string `json:"text"`
}

func createNarrationHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createNarrationRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner && !hasActiveDelegatedPower(campaignID, actor.Username, "narrate") {
		writeError(w, http.StatusForbidden, "only the owning dm may narrate in this campaign")
		return
	}

	playNarrationsMu.Lock()
	defer playNarrationsMu.Unlock()

	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "narration",
		Actor:      actor.Username,
		Text:       req.Text,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save narration")
		return
	}
	playNarrations[campaignID] = append(events, n)

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence": n.Sequence,
		"kind":     n.Kind,
		"actor":    n.Actor,
		"text":     n.Text,
	})
}

type createActionRequest struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// createActionHandler lets the active player submit an action event. Only the
// player whose turn it currently is may call this; a waiting player or the
// dm receives 409. On success the action is appended and the turn passes to
// the dm.
func createActionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createActionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Type == "" {
		writeError(w, http.StatusBadRequest, "type is required")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username == c.Owner {
		writeError(w, http.StatusConflict, "the dm may not submit a player action")
		return
	}

	if !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a member of this campaign")
		return
	}

	if actor.Username != c.CurrentActor {
		writeError(w, http.StatusConflict, "it is not this player's turn")
		return
	}

	playNarrationsMu.Lock()
	defer playNarrationsMu.Unlock()

	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "action",
		Actor:      actor.Username,
		Type:       req.Type,
		Text:       req.Text,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save action")
		return
	}
	playNarrations[campaignID] = append(events, n)

	c.CurrentActor = c.Owner
	c.Phase = "gm"
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence":   n.Sequence,
		"kind":       n.Kind,
		"actor":      n.Actor,
		"type":       n.Type,
		"text":       n.Text,
		"next_actor": "dm",
	})
}

type createResolutionRequest struct {
	Text string `json:"text"`
}

// createResolutionHandler lets the owning dm resolve the current player
// action. Only the owner may call this, and only when the current actor is
// the owner (i.e. a player action is awaiting resolution) — a player
// attempting resolution receives 409. On success a resolution event is
// appended and the turn advances to the next player in join order after the
// player whose action is being resolved.
func createResolutionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createResolutionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusConflict, "only the owner may submit a resolution")
		return
	}

	if c.CurrentActor != c.Owner {
		writeError(w, http.StatusConflict, "it is not the owner's turn")
		return
	}

	members := sortedPlayMembers(campaignID)

	playNarrationsMu.Lock()
	defer playNarrationsMu.Unlock()

	events := playNarrations[campaignID]

	var nextActor string
	if len(members) > 0 {
		var lastPlayer string
		for i := len(events) - 1; i >= 0; i-- {
			switch events[i].Kind {
			case "action", "travel":
				lastPlayer = events[i].Actor
			}
			if lastPlayer != "" {
				break
			}
		}
		nextIndex := 0
		for i, m := range members {
			if m.Username == lastPlayer {
				nextIndex = (i + 1) % len(members)
				break
			}
		}
		nextActor = members[nextIndex].Username
	}

	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "resolution",
		Actor:      "dm",
		Text:       req.Text,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save resolution")
		return
	}
	playNarrations[campaignID] = append(events, n)

	c.CurrentActor = nextActor
	c.TurnNumber++
	c.Phase = "player"
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence":    n.Sequence,
		"kind":        n.Kind,
		"actor":       n.Actor,
		"text":        n.Text,
		"next_actor":  nextActor,
		"turn_number": c.TurnNumber,
	})
}

func getTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	if actor.Username != c.Owner {
		if !isPlayMember(campaignID, actor.Username) {
			writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
			return
		}
	}

	phase := c.Phase
	if phase == "" {
		phase = "gm"
		if c.CurrentActor != c.Owner {
			phase = "player"
		}
	}

	members := sortedPlayMembers(campaignID)

	queue := make([]string, 0, len(members)*2)
	for _, m := range members {
		queue = append(queue, m.Username, c.Owner)
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":      c.ID,
		"current_actor":    c.CurrentActor,
		"phase":            phase,
		"turn_number":      c.TurnNumber,
		"queue":            queue,
		"overdue":          false,
		"logical_deadline": c.TurnNumber + 1,
	})
}

type nudgeTurnRequest struct {
	Message string `json:"message"`
}

// nudgeTurnHandler lets the owning dm send a deterministic nudge to whoever
// currently holds the turn. It requires a nonempty message and returns a
// monotonically increasing per-campaign nudge_count.
func nudgeTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req nudgeTurnRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Message == "" {
		writeError(w, http.StatusBadRequest, "message is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may nudge this campaign")
		return
	}

	c.NudgeCount++
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "nudge",
		Actor:      "dm",
		Text:       req.Message,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		playNarrationsMu.Unlock()
		writeError(w, http.StatusInternalServerError, "failed to save nudge")
		return
	}
	playNarrations[campaignID] = append(events, n)
	playNarrationsMu.Unlock()

	writeJSON(w, http.StatusCreated, map[string]any{
		"actor":       "dm",
		"target":      c.CurrentActor,
		"message":     req.Message,
		"nudge_count": c.NudgeCount,
	})
}

// getMyTurnHandler returns turn context scoped to the calling player's own
// character: whether it is currently their turn, who the current actor is,
// their own {id,name} character, and recent campaign events. Only a
// campaign member with role "player" may call this, and only their own
// character context is ever exposed.
func getMyTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if actor.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may read their own turn context")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	playMembersMu.Lock()
	member, isMember := playMembers[campaignID][actor.Username]
	playMembersMu.Unlock()
	if !isMember {
		writeError(w, http.StatusForbidden, "must be a member of this campaign")
		return
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	recentEvents := make([]*playNarration, len(events))
	copy(recentEvents, events)
	playNarrationsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":   c.ID,
		"is_my_turn":    c.CurrentActor == actor.Username,
		"current_actor": c.CurrentActor,
		"character": map[string]any{
			"id":   member.CharacterID,
			"name": member.Name,
		},
		"recent_events": recentEvents,
	})
}

// getGMStatusHandler returns GM-facing turn context for the owning dm: whether
// the campaign needs the gm's attention (true exactly when the current actor
// is the owner), the current actor, a summary of each party member, and
// recent campaign events. Only the owning dm may call this; players receive
// 403.
func getGMStatusHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may read gm status")
		return
	}

	members := sortedPlayMembers(campaignID)

	party := make([]map[string]any, 0, len(members))
	for _, m := range members {
		party = append(party, map[string]any{
			"username":     m.Username,
			"character_id": m.CharacterID,
			"name":         m.Name,
			"class":        m.Class,
		})
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	recentEvents := make([]*playNarration, len(events))
	copy(recentEvents, events)
	playNarrationsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":     c.ID,
		"needs_attention": c.CurrentActor == c.Owner,
		"current_actor":   c.CurrentActor,
		"party":           party,
		"recent_events":   recentEvents,
	})
}

// getOnboardingHandler returns role-specific onboarding guidance for an
// authenticated campaign member: fixed next-step lists for the owning dm and
// for player members. It reads only stable campaign/membership state, so the
// response never mutates the campaign or varies across repeated reads.
func getOnboardingHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	if actor.Username == c.Owner {
		writeJSON(w, http.StatusOK, map[string]any{
			"role":       "dm",
			"next_steps": []string{"configure-safety", "invite-players", "start-campaign"},
			"can_mutate": true,
		})
		return
	}

	if !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a member of this campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"role":       "player",
		"next_steps": []string{"review-party", "take-turn", "submit-action"},
		"can_mutate": true,
	})
}

type updateDocumentRequest struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// getDocumentHandler returns the durable campaign document. The owning dm
// receives both the public story and the private dm_notes; a player member
// receives only the public story field.
func getDocumentHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	if actor.Username == c.Owner {
		writeJSON(w, http.StatusOK, map[string]any{
			"story":    c.Story,
			"dm_notes": c.DMNotes,
		})
		return
	}

	if !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"story": c.Story,
	})
}

// updateDocumentHandler lets the owning dm update the durable campaign
// document. Only the owner may call this; a player receives 403.
func updateDocumentHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateDocumentRequest
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
		writeError(w, http.StatusForbidden, "only the owning dm may update this campaign's document")
		return
	}

	c.Story = req.Story
	c.DMNotes = req.DMNotes
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"story":    c.Story,
		"dm_notes": c.DMNotes,
	})
}

type createSceneRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createSceneHandler lets the owning dm create a new scene for the campaign.
// Only the owner may call this; duplicate scene ids receive 409.
func createSceneHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createSceneRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may create a scene")
		return
	}

	playScenesMu.Lock()
	defer playScenesMu.Unlock()

	if playScenes[campaignID] == nil {
		playScenes[campaignID] = map[string]*playScene{}
	}
	if _, exists := playScenes[campaignID][req.ID]; exists {
		writeError(w, http.StatusConflict, "scene id already exists")
		return
	}

	s := &playScene{
		CampaignID: campaignID,
		ID:         req.ID,
		Name:       req.Name,
		Status:     "open",
	}
	if err := savePlaySceneToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save scene")
		return
	}
	playScenes[campaignID][s.ID] = s

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":     s.ID,
		"name":   s.Name,
		"status": s.Status,
	})
}

// enterSceneHandler lets the owning dm set the campaign's current scene.
// Only the owner may call this; closed scenes may not be entered.
func enterSceneHandler(w http.ResponseWriter, r *http.Request, campaignID, sceneID string) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may enter a scene")
		return
	}

	playScenesMu.Lock()
	defer playScenesMu.Unlock()

	s, exists := playScenes[campaignID][sceneID]
	if !exists {
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}
	if s.Status == "closed" {
		writeError(w, http.StatusConflict, "closed scenes may not be entered")
		return
	}

	c.CurrentSceneID = s.ID
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "scene",
		Actor:      actor.Username,
		Text:       s.ID,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		playNarrationsMu.Unlock()
		writeError(w, http.StatusInternalServerError, "failed to save scene event")
		return
	}
	playNarrations[campaignID] = append(events, n)
	playNarrationsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"current_scene_id": s.ID,
		"name":             s.Name,
	})
}

// closeSceneHandler lets the owning dm mark a scene closed. Only the owner
// may call this.
func closeSceneHandler(w http.ResponseWriter, r *http.Request, campaignID, sceneID string) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may close a scene")
		return
	}

	playScenesMu.Lock()
	defer playScenesMu.Unlock()

	s, exists := playScenes[campaignID][sceneID]
	if !exists {
		writeError(w, http.StatusNotFound, "scene not found")
		return
	}

	s.Status = "closed"
	if err := savePlaySceneToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save scene")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":     s.ID,
		"status": s.Status,
	})
}

// getCurrentSceneHandler returns the open current scene for any campaign
// member (the owner or a joined player). If no scene is currently open, it
// returns 404.
func getCurrentSceneHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	playScenesMu.Lock()
	defer playScenesMu.Unlock()

	if c.CurrentSceneID == "" {
		writeError(w, http.StatusNotFound, "no current scene is set")
		return
	}
	s, exists := playScenes[campaignID][c.CurrentSceneID]
	if !exists || s.Status != "open" {
		writeError(w, http.StatusNotFound, "no current scene is set")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":     s.ID,
		"name":   s.Name,
		"status": s.Status,
	})
}

type createLocationRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createLocationHandler lets the owning dm create a new location for the
// campaign. Only the owner may call this; duplicate location ids receive 409.
func createLocationHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createLocationRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may create a location")
		return
	}

	playLocationsMu.Lock()
	defer playLocationsMu.Unlock()

	if playLocations[campaignID] == nil {
		playLocations[campaignID] = map[string]*playLocation{}
	}
	if _, exists := playLocations[campaignID][req.ID]; exists {
		writeError(w, http.StatusConflict, "location id already exists")
		return
	}

	loc := &playLocation{
		CampaignID: campaignID,
		ID:         req.ID,
		Name:       req.Name,
	}
	if err := savePlayLocationToDB(loc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save location")
		return
	}
	isFirstLocation := len(playLocations[campaignID]) == 0
	playLocations[campaignID][loc.ID] = loc

	if isFirstLocation {
		c.CurrentLocationID = loc.ID
		if err := savePlayCampaignToDB(c); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save play campaign")
			return
		}
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":   loc.ID,
		"name": loc.Name,
	})
}

type createEncounterRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createEncounterHandler lets the owning dm start a campaign-bound encounter
// from the current party state. Only the owner may call this; a duplicate
// encounter id or a campaign already in combat both receive 409. The
// encounter runs independently of the exploration turn queue until the
// campaign returns to exploration.
func createEncounterHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createEncounterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may start an encounter")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	if c.CurrentEncounterID != "" {
		if existing, ok := playEncounters[campaignID][c.CurrentEncounterID]; ok && existing.Status == "active" {
			writeError(w, http.StatusConflict, "campaign is already in combat")
			return
		}
	}
	if playEncounters[campaignID] == nil {
		playEncounters[campaignID] = map[string]*playEncounter{}
	}
	if _, exists := playEncounters[campaignID][req.ID]; exists {
		writeError(w, http.StatusConflict, "encounter id already exists")
		return
	}

	enc := &playEncounter{
		CampaignID: campaignID,
		ID:         req.ID,
		Name:       req.Name,
		Status:     "active",
		Round:      1,
		TurnIndex:  0,
	}
	if err := savePlayEncounterToDB(enc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter")
		return
	}
	playEncounters[campaignID][enc.ID] = enc

	c.PreCombatActor = c.CurrentActor
	c.CurrentEncounterID = enc.ID
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":         enc.ID,
		"name":       enc.Name,
		"status":     enc.Status,
		"combatants": []any{},
	})
}

type addMonsterRequest struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
}

// addMonsterHandler lets the owning dm add a deterministic monster combatant
// to an active encounter. Only the owner may call this; a duplicate monster
// id within the encounter receives 409.
func addMonsterHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req addMonsterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.MonsterID == "" {
		writeError(w, http.StatusBadRequest, "monster_id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may add a monster")
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

	if playMonsters[campaignID] == nil {
		playMonsters[campaignID] = map[string]map[string]*playMonster{}
	}
	if playMonsters[campaignID][encID] == nil {
		playMonsters[campaignID][encID] = map[string]*playMonster{}
	}
	if _, exists := playMonsters[campaignID][encID][req.MonsterID]; exists {
		writeError(w, http.StatusConflict, "monster id already exists")
		return
	}

	m := &playMonster{
		CampaignID:  campaignID,
		EncounterID: encID,
		MonsterID:   req.MonsterID,
		Name:        req.Name,
		HPMax:       req.HPMax,
		HPCurrent:   req.HPMax,
		Initiative:  req.Initiative,
	}
	if err := savePlayMonsterToDB(m); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save monster")
		return
	}
	playMonsters[campaignID][encID][m.MonsterID] = m

	writeJSON(w, http.StatusCreated, map[string]any{
		"monster_id": m.MonsterID,
		"name":       m.Name,
		"hp_max":     m.HPMax,
		"initiative": m.Initiative,
		"hp_current": m.HPCurrent,
	})
}

// removeMonsterHandler lets the owning dm remove a monster combatant from an
// encounter. Only the owner may call this.
func removeMonsterHandler(w http.ResponseWriter, r *http.Request, campaignID, encID, monsterID string) {
	if !requireMethod(w, r, http.MethodDelete) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may remove a monster")
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

	if _, exists := playMonsters[campaignID][encID][monsterID]; !exists {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}

	if err := deletePlayMonsterFromDB(campaignID, encID, monsterID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to remove monster")
		return
	}
	delete(playMonsters[campaignID][encID], monsterID)

	writeJSON(w, http.StatusOK, map[string]any{
		"removed": monsterID,
	})
}

type bindCombatantRequest struct {
	Member     string `json:"member"`
	Initiative int    `json:"initiative"`
}

// bindCombatantHandler lets the owning dm bind a campaign party member to an
// active encounter as a combatant. Only the owner may call this; a member not
// part of the campaign receives 400, and a member already bound receives 409.
func bindCombatantHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req bindCombatantRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Member == "" {
		writeError(w, http.StatusBadRequest, "member is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may bind a combatant")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	if _, exists := playEncounters[campaignID][encID]; !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := playMembers[campaignID][req.Member]
	if !exists {
		writeError(w, http.StatusBadRequest, "member not found in campaign")
		return
	}

	playCombatantsMu.Lock()
	defer playCombatantsMu.Unlock()

	if playCombatants[campaignID] == nil {
		playCombatants[campaignID] = map[string]map[string]*playCombatant{}
	}
	if playCombatants[campaignID][encID] == nil {
		playCombatants[campaignID][encID] = map[string]*playCombatant{}
	}
	if _, exists := playCombatants[campaignID][encID][req.Member]; exists {
		writeError(w, http.StatusConflict, "member already bound to encounter")
		return
	}

	combatant := &playCombatant{
		CampaignID:  campaignID,
		EncounterID: encID,
		Member:      req.Member,
		CharacterID: member.CharacterID,
		Name:        member.Name,
		Initiative:  req.Initiative,
	}
	if err := savePlayCombatantToDB(combatant); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save combatant")
		return
	}
	playCombatants[campaignID][encID][req.Member] = combatant

	writeJSON(w, http.StatusCreated, map[string]any{
		"member":       combatant.Member,
		"character_id": combatant.CharacterID,
		"name":         combatant.Name,
		"initiative":   combatant.Initiative,
	})
}

// unbindCombatantHandler lets the owning dm remove a party member from an
// encounter's combatants. Only the owner may call this.
func unbindCombatantHandler(w http.ResponseWriter, r *http.Request, campaignID, encID, member string) {
	if !requireMethod(w, r, http.MethodDelete) {
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
		writeError(w, http.StatusForbidden, "only the owning dm may unbind a combatant")
		return
	}

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()

	if _, exists := playEncounters[campaignID][encID]; !exists {
		writeError(w, http.StatusNotFound, "encounter not found")
		return
	}

	playCombatantsMu.Lock()
	defer playCombatantsMu.Unlock()

	if _, exists := playCombatants[campaignID][encID][member]; !exists {
		writeError(w, http.StatusNotFound, "combatant not found")
		return
	}

	if err := deletePlayCombatantFromDB(campaignID, encID, member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to remove combatant")
		return
	}
	delete(playCombatants[campaignID][encID], member)

	writeJSON(w, http.StatusOK, map[string]any{
		"removed": member,
	})
}

type encounterCombatant struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`
	Initiative int    `json:"initiative"`
	Member     string `json:"-"`
	TargetID   string `json:"-"`
}

// encounterTurnOrder builds the deterministic initiative order for an
// encounter by merging its monsters and bound party members. Ties break by
// kind (monster before character) then by name. Callers must hold
// playMonstersMu and playCombatantsMu.
func encounterTurnOrder(campaignID, encID string) []encounterCombatant {
	order := make([]encounterCombatant, 0)
	for _, m := range playMonsters[campaignID][encID] {
		order = append(order, encounterCombatant{Name: m.Name, Kind: "monster", Initiative: m.Initiative, TargetID: m.MonsterID})
	}
	for _, cb := range playCombatants[campaignID][encID] {
		order = append(order, encounterCombatant{Name: cb.Name, Kind: "player", Initiative: cb.Initiative, Member: cb.Member, TargetID: cb.Member})
	}
	sort.Slice(order, func(i, j int) bool {
		if order[i].Initiative != order[j].Initiative {
			return order[i].Initiative > order[j].Initiative
		}
		if order[i].Kind != order[j].Kind {
			return order[i].Kind < order[j].Kind
		}
		return order[i].Name < order[j].Name
	})
	return order
}

// effectiveTurnOrder returns encID's turn order, honoring any reordering
// recorded by a prior delay. Combatants named in enc.OrderOverride are placed
// in that order; any combatant not named there (e.g. added after the delay)
// is appended afterward in initiative order. Callers must hold
// playMonstersMu and playCombatantsMu.
func effectiveTurnOrder(enc *playEncounter, campaignID, encID string) []encounterCombatant {
	base := encounterTurnOrder(campaignID, encID)
	if len(enc.OrderOverride) == 0 {
		return base
	}

	byTarget := make(map[string]encounterCombatant, len(base))
	for _, cb := range base {
		byTarget[cb.TargetID] = cb
	}

	ordered := make([]encounterCombatant, 0, len(base))
	seen := make(map[string]bool, len(base))
	for _, id := range enc.OrderOverride {
		if cb, exists := byTarget[id]; exists && !seen[id] {
			ordered = append(ordered, cb)
			seen[id] = true
		}
	}
	for _, cb := range base {
		if !seen[cb.TargetID] {
			ordered = append(ordered, cb)
			seen[cb.TargetID] = true
		}
	}
	return ordered
}

// getEncounterTurnHandler returns the current combatant in an encounter's
// initiative order. Any owner or member of the campaign may call it.
func getEncounterTurnHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
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
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	active := order[enc.TurnIndex%len(order)]

	writeJSON(w, http.StatusOK, map[string]any{
		"round":      enc.Round,
		"turn_index": enc.TurnIndex,
		"active": map[string]any{
			"name":       active.Name,
			"kind":       active.Kind,
			"initiative": active.Initiative,
		},
	})
}

// advanceEncounterTurnHandler advances an encounter to the next combatant in
// deterministic initiative order. Only the owner or the current combatant may
// call it; acting out of turn returns 409.
func advanceEncounterTurnHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
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
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	active := order[enc.TurnIndex%len(order)]

	isCurrentCombatant := active.Kind == "player" && active.Member == actor.Username
	if actor.Username != c.Owner && !isCurrentCombatant {
		writeError(w, http.StatusConflict, "only the owner or the current combatant may advance the turn")
		return
	}

	enc.TurnIndex++
	if enc.TurnIndex >= len(order) {
		enc.TurnIndex = 0
		enc.Round++
	}
	if err := savePlayEncounterToDB(enc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter")
		return
	}

	newActive := order[enc.TurnIndex]

	playConditionsMu.Lock()
	defer playConditionsMu.Unlock()
	if err := decrementConditionsOnTurnStart(campaignID, encID, newActive.TargetID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to update conditions")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"round":      enc.Round,
		"turn_index": enc.TurnIndex,
		"active": map[string]any{
			"name":       newActive.Name,
			"kind":       newActive.Kind,
			"initiative": newActive.Initiative,
		},
	})
}

type turnDelayRequest struct {
	NewIndex *int `json:"new_index"`
}

// delayEncounterTurnHandler moves the current combatant to a later position
// in the encounter's initiative order without duplicating its turn: the
// combatant that ends up occupying the current combatant's old slot becomes
// active next. Only the owner or the current combatant may call it;
// reordering to anything other than a later, in-bounds index returns 400.
func delayEncounterTurnHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req turnDelayRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
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
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	currentIndex := enc.TurnIndex % len(order)
	active := order[currentIndex]

	isCurrentCombatant := active.Kind == "player" && active.Member == actor.Username
	if actor.Username != c.Owner && !isCurrentCombatant {
		writeError(w, http.StatusConflict, "only the owner or the current combatant may delay the turn")
		return
	}

	if req.NewIndex == nil || *req.NewIndex <= currentIndex || *req.NewIndex >= len(order) {
		writeError(w, http.StatusBadRequest, "new_index must name a later position within the initiative order")
		return
	}
	newIndex := *req.NewIndex

	reordered := make([]encounterCombatant, 0, len(order))
	reordered = append(reordered, order[:currentIndex]...)
	reordered = append(reordered, order[currentIndex+1:]...)
	withActive := make([]encounterCombatant, 0, len(order))
	withActive = append(withActive, reordered[:newIndex]...)
	withActive = append(withActive, active)
	withActive = append(withActive, reordered[newIndex:]...)

	overrideIDs := make([]string, 0, len(withActive))
	for _, cb := range withActive {
		overrideIDs = append(overrideIDs, cb.TargetID)
	}
	enc.OrderOverride = overrideIDs
	// The delaying combatant remains current (it has not yet acted) but now
	// occupies a later slot; turn_index follows it there so a subsequent
	// turn/advance moves on from its new position rather than duplicating
	// its turn.
	enc.TurnIndex = newIndex
	if err := savePlayEncounterToDB(enc); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save encounter")
		return
	}

	orderOut := make([]map[string]any, 0, len(withActive))
	for _, cb := range withActive {
		orderOut = append(orderOut, map[string]any{
			"name":       cb.Name,
			"kind":       cb.Kind,
			"initiative": cb.Initiative,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"round":      enc.Round,
		"turn_index": enc.TurnIndex,
		"order":      orderOut,
	})
}

type turnReadyRequest struct {
	Trigger string `json:"trigger"`
}

// readyEncounterTurnHandler lets the current combatant record a readied
// action against a trigger condition. It does not change the turn order or
// advance the turn. Only the current combatant may call it.
func readyEncounterTurnHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req turnReadyRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Trigger == "" {
		writeError(w, http.StatusBadRequest, "trigger is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	_, ok = requirePlayCampaign(w, campaignID)
	if !ok {
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
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	active := order[enc.TurnIndex%len(order)]
	if active.Kind != "player" || active.Member != actor.Username {
		writeError(w, http.StatusConflict, "it is not this combatant's turn")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"actor":   actor.Username,
		"trigger": req.Trigger,
	})
}

type createCombatActionRequest struct {
	Type   string `json:"type"`
	Target string `json:"target"`
	Text   string `json:"text"`
}

// validCombatActionTypes are the combat action types accepted by
// createCombatActionHandler.
var validCombatActionTypes = map[string]bool{
	"attack": true,
	"help":   true,
	"dodge":  true,
	"ready":  true,
}

// createCombatActionHandler lets the current combatant in an encounter submit
// a typed combat action event. The action is recorded but does not itself
// advance the encounter turn. Only the current combatant may call this; an
// invalid type receives 400 and acting out of turn receives 409.
func createCombatActionHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createCombatActionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !validCombatActionTypes[req.Type] {
		writeError(w, http.StatusBadRequest, "type must be one of attack, help, dodge, ready")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	_, ok = requirePlayCampaign(w, campaignID)
	if !ok {
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
	if len(order) == 0 {
		writeError(w, http.StatusConflict, "encounter has no combatants")
		return
	}
	active := order[enc.TurnIndex%len(order)]

	if active.Kind != "player" || active.Member != actor.Username {
		writeError(w, http.StatusConflict, "it is not this combatant's turn")
		return
	}

	playNarrationsMu.Lock()
	defer playNarrationsMu.Unlock()

	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "combat_action",
		Actor:      actor.Username,
		Type:       req.Type,
		Target:     req.Target,
		Text:       req.Text,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save combat action")
		return
	}
	playNarrations[campaignID] = append(events, n)

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence": n.Sequence,
		"kind":     n.Kind,
		"actor":    n.Actor,
		"type":     n.Type,
		"target":   n.Target,
		"text":     n.Text,
	})
}

type damageRequest struct {
	Target string `json:"target"`
	Amount int    `json:"amount"`
}

// resolveEncounterHPTarget finds a monster or bound player combatant by
// target id within an encounter and returns pointers to its current and max
// hp fields, plus a save function to persist the change. Callers must already
// hold playMonstersMu, playCombatantsMu, and playMembersMu.
func resolveEncounterHPTarget(campaignID, encID, target string) (hpCurrent *int, hpMax int, save func() error, ok bool) {
	if m, exists := playMonsters[campaignID][encID][target]; exists {
		return &m.HPCurrent, m.HPMax, func() error { return savePlayMonsterToDB(m) }, true
	}
	if _, exists := playCombatants[campaignID][encID][target]; exists {
		if member, exists := playMembers[campaignID][target]; exists {
			return &member.HPCurrent, member.HPMax, func() error { return savePlayMemberToDB(member) }, true
		}
	}
	return nil, 0, nil, false
}

// damageHandler lets the owning dm apply deterministic damage to an
// encounter combatant. Only the owner may call this; hp floors at 0.
func damageHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req damageRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "target is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may apply damage")
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
	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	hpCurrent, _, save, found := resolveEncounterHPTarget(campaignID, encID, req.Target)
	if !found {
		writeError(w, http.StatusNotFound, "target not found in encounter")
		return
	}

	hpBefore := *hpCurrent
	hpAfter := hpBefore - req.Amount
	if hpAfter < 0 {
		hpAfter = 0
	}
	*hpCurrent = hpAfter

	if err := save(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save target state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"target":    req.Target,
		"hp_before": hpBefore,
		"hp_after":  hpAfter,
		"damage":    req.Amount,
	})
}

type healRequest struct {
	Target string `json:"target"`
	Amount int    `json:"amount"`
}

// healHandler lets the owning dm apply deterministic healing to an
// encounter combatant. Only the owner may call this; hp caps at hp_max.
func healHandler(w http.ResponseWriter, r *http.Request, campaignID, encID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req healRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "target is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may apply healing")
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
	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	hpCurrent, hpMax, save, found := resolveEncounterHPTarget(campaignID, encID, req.Target)
	if !found {
		writeError(w, http.StatusNotFound, "target not found in encounter")
		return
	}

	hpBefore := *hpCurrent
	hpAfter := hpBefore + req.Amount
	if hpAfter > hpMax {
		hpAfter = hpMax
	}
	*hpCurrent = hpAfter

	if err := save(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save target state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"target":    req.Target,
		"hp_before": hpBefore,
		"hp_after":  hpAfter,
		"healing":   req.Amount,
	})
}

// findMemberByCharacterID looks up the play member owning charID within
// campaignID. Callers must already hold playMembersMu.
func findMemberByCharacterID(campaignID, charID string) (*playMember, bool) {
	for _, m := range playMembers[campaignID] {
		if m.CharacterID == charID {
			return m, true
		}
	}
	return nil, false
}

type characterDamageRequest struct {
	Amount int `json:"amount"`
}

// characterDamageHandler lets the campaign's owning dm apply deterministic
// damage to a member's character; hp floors at 0 and drops the character to
// unconscious with cleared death save counters.
func characterDamageHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req characterDamageRequest
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
		writeError(w, http.StatusForbidden, "only the owning dm may apply damage")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	hpBefore := member.HPCurrent
	hpAfter := hpBefore - req.Amount
	if hpAfter < 0 {
		hpAfter = 0
	}
	member.HPCurrent = hpAfter
	if hpAfter == 0 && member.Status == memberConscious {
		member.Status = "unconscious"
		member.DeathSaveSuccesses = 0
		member.DeathSaveFailures = 0
	}

	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": member.CharacterID,
		"target":       member.CharacterID,
		"hp_before":    hpBefore,
		"hp_after":     hpAfter,
		"damage":       req.Amount,
		"status":       member.Status,
	})
}

// validCharacterRaces lists the playable races accepted by buildCharacterHandler.
var validCharacterRaces = map[string]bool{
	"human": true, "elf": true, "dwarf": true, "halfling": true,
	"half-elf": true, "half-orc": true, "gnome": true, "dragonborn": true, "tiefling": true,
}

// validCharacterBackgrounds lists the backgrounds accepted by buildCharacterHandler.
var validCharacterBackgrounds = map[string]bool{
	"acolyte": true, "charlatan": true, "criminal": true, "entertainer": true,
	"folk-hero": true, "guild-artisan": true, "hermit": true, "noble": true,
	"outlander": true, "sage": true, "sailor": true, "soldier": true, "urchin": true,
}

// classHitDice maps each playable class to its level-1 hit die size, used to
// derive hp_max = hit_die + con_modifier.
var classHitDice = map[string]int{
	"barbarian": 12,
	"fighter":   10, "paladin": 10, "ranger": 10,
	"bard": 8, "cleric": 8, "druid": 8, "monk": 8, "rogue": 8, "warlock": 8,
	"sorcerer": 6, "wizard": 6,
}

type buildCharacterRequest struct {
	Race       string        `json:"race"`
	Class      string        `json:"class"`
	Background string        `json:"background"`
	Abilities  abilityScores `json:"abilities"`
}

// buildCharacterHandler validates a character's race/class/background and
// ability scores, then returns level-1 derived defaults. Only the
// character's owner may build it.
func buildCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req buildCharacterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !validCharacterRaces[req.Race] {
		writeError(w, http.StatusBadRequest, "unknown race")
		return
	}
	hitDie, validClass := classHitDice[req.Class]
	if !validClass {
		writeError(w, http.StatusBadRequest, "unknown class")
		return
	}
	if !validCharacterBackgrounds[req.Background] {
		writeError(w, http.StatusBadRequest, "unknown background")
		return
	}
	scores := map[string]*int{
		"str": req.Abilities.Str,
		"dex": req.Abilities.Dex,
		"con": req.Abilities.Con,
		"int": req.Abilities.Int,
		"wis": req.Abilities.Wis,
		"cha": req.Abilities.Cha,
	}
	for _, v := range scores {
		if v == nil || *v < 1 || *v > 30 {
			writeError(w, http.StatusBadRequest, "abilities must be integers from 1 through 30")
			return
		}
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may build this character")
		return
	}

	conModifier := floorDiv(*req.Abilities.Con - 10)
	hpMax := hitDie + conModifier
	proficiencyBonus := proficiencyBonusForLevel(1)

	member.Race = req.Race
	member.Class = req.Class
	member.Background = req.Background
	member.ConScore = *req.Abilities.Con
	member.StrScore = *req.Abilities.Str
	member.DexScore = *req.Abilities.Dex
	member.IntScore = *req.Abilities.Int
	member.WisScore = *req.Abilities.Wis
	member.ChaScore = *req.Abilities.Cha
	member.HPMax = hpMax
	member.HPCurrent = hpMax
	if member.Level == 0 {
		member.Level = 1
	}
	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":      member.CharacterID,
		"race":              member.Race,
		"class":             member.Class,
		"background":        member.Background,
		"level":             1,
		"hp_max":            hpMax,
		"proficiency_bonus": proficiencyBonus,
	})
}

type levelUpRequest struct {
	Level *int `json:"level"`
}

// levelUpHandler advances a character exactly one level, applying the
// deterministic 5e hp-gain-by-average rule (floor(hit die / 2) + 1 +
// con modifier) and recomputing proficiency bonus. Only the owner may call
// this, and the requested level must be exactly one higher than the
// character's current level.
func levelUpHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req levelUpRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may level up this character")
		return
	}

	currentLevel := member.Level
	if currentLevel == 0 {
		currentLevel = 1
	}
	if *req.Level != currentLevel+1 {
		writeError(w, http.StatusBadRequest, "level must be exactly one higher than the current level")
		return
	}

	hitDie, validClass := classHitDice[member.Class]
	if !validClass {
		writeError(w, http.StatusBadRequest, "character must be built before leveling up")
		return
	}

	conModifier := floorDiv(member.ConScore - 10)
	hpGain := floorDiv(hitDie) + 1 + conModifier

	member.Level = *req.Level
	member.HPMax += hpGain
	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":      member.CharacterID,
		"level":             member.Level,
		"hp_max":            member.HPMax,
		"hit_dice":          fmt.Sprintf("1d%d", hitDie),
		"proficiency_bonus": proficiencyBonusForLevel(member.Level),
	})
}

type skillCheckRequest struct {
	Skill      string `json:"skill"`
	Ability    string `json:"ability"`
	Proficient bool   `json:"proficient"`
	Roll       int    `json:"roll"`
}

// skillCheckHandler resolves a skill-check modifier from a character's
// ability score and proficiency, restricted to the character's owner.
func skillCheckHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req skillCheckRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !validSkills[req.Skill] {
		writeError(w, http.StatusBadRequest, "unsupported skill")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may make this skill check")
		return
	}

	score, validAbility := abilityScoreByName(member, req.Ability)
	if !validAbility {
		writeError(w, http.StatusBadRequest, "unsupported ability")
		return
	}

	modifier := floorDiv(score - 10)
	if req.Proficient {
		level := member.Level
		if level == 0 {
			level = 1
		}
		modifier += proficiencyBonusForLevel(level)
	}
	total := req.Roll + modifier

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": member.CharacterID,
		"skill":        req.Skill,
		"ability":      req.Ability,
		"modifier":     modifier,
		"total":        total,
	})
}

type deathSaveRequest struct {
	Outcome string `json:"outcome"`
}

// deathSaveHandler lets a character's owning player record a death save
// outcome while the character is unconscious. Three successes stabilize the
// character; three failures kill it. Non-owners and rolls on a character that
// isn't unconscious are rejected.
func deathSaveHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req deathSaveRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Outcome != "success" && req.Outcome != "failure" {
		writeError(w, http.StatusBadRequest, "outcome must be \"success\" or \"failure\"")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != member.Username {
		writeError(w, http.StatusForbidden, "only the character's owner may record a death save")
		return
	}
	if member.Status != "unconscious" {
		writeError(w, http.StatusConflict, "death saves are only accepted while unconscious")
		return
	}

	if req.Outcome == "success" {
		member.DeathSaveSuccesses++
		if member.DeathSaveSuccesses >= 3 {
			member.Status = "stable"
		}
	} else {
		member.DeathSaveFailures++
		if member.DeathSaveFailures >= 3 {
			member.Status = "dead"
		}
	}

	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"character_id": member.CharacterID,
		"successes":    member.DeathSaveSuccesses,
		"failures":     member.DeathSaveFailures,
		"status":       member.Status,
	})
}

// characterStatusHandler returns a character's hp and status for any member
// of the campaign, owner or player.
func characterStatusHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": member.CharacterID,
		"hp_current":   member.HPCurrent,
		"hp_max":       member.HPMax,
		"status":       member.Status,
	})
}

// characterOwnerHandler returns a character's current owner. Any campaign
// member (owner or player) may call this.
func characterOwnerHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": member.CharacterID,
		"owner":        playMemberOwner(member),
	})
}

// claimCharacterHandler lets the requesting player claim a character that
// has no explicit owner yet. A character already owned by another player
// returns 409.
func claimCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if actor.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may claim a character")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	owner := playMemberOwner(member)
	if owner != "" && owner != actor.Username {
		writeError(w, http.StatusConflict, "character is already owned by another player")
		return
	}
	member.Owner = actor.Username

	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"character_id": member.CharacterID,
		"owner":        member.Owner,
	})
}

type transferCharacterRequest struct {
	NewOwner string `json:"new_owner"`
}

// transferCharacterHandler lets a character's owner hand ownership to
// another campaign member. Only the owner may transfer, and the new owner
// must already be a member of the campaign.
func transferCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req transferCharacterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.NewOwner == "" {
		writeError(w, http.StatusBadRequest, "new_owner is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != actor.Username {
		writeError(w, http.StatusForbidden, "only the character's owner may transfer ownership")
		return
	}
	if _, ok := playMembers[campaignID][req.NewOwner]; !ok {
		writeError(w, http.StatusBadRequest, "new_owner must be a campaign member")
		return
	}
	member.Owner = req.NewOwner

	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": member.CharacterID,
		"owner":        member.Owner,
	})
}

type createConnectionRequest struct {
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// createConnectionHandler lets the owning dm connect fromID to another
// location. Only the owner may call this; connections to a missing location
// or to an already-connected destination receive 400.
func createConnectionHandler(w http.ResponseWriter, r *http.Request, campaignID, fromID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createConnectionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ToID == "" {
		writeError(w, http.StatusBadRequest, "to_id is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may create a connection")
		return
	}

	playLocationsMu.Lock()
	_, fromExists := playLocations[campaignID][fromID]
	_, toExists := playLocations[campaignID][req.ToID]
	playLocationsMu.Unlock()
	if !fromExists || !toExists {
		writeError(w, http.StatusBadRequest, "connection references a missing location")
		return
	}

	playConnectionsMu.Lock()
	defer playConnectionsMu.Unlock()

	for _, conn := range playConnections[campaignID] {
		if conn.FromID == fromID && conn.ToID == req.ToID {
			writeError(w, http.StatusBadRequest, "destination is already connected")
			return
		}
	}

	conn := &playConnection{
		CampaignID:  campaignID,
		FromID:      fromID,
		ToID:        req.ToID,
		TravelTurns: req.TravelTurns,
	}
	if err := savePlayConnectionToDB(conn); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save connection")
		return
	}
	playConnections[campaignID] = append(playConnections[campaignID], conn)

	writeJSON(w, http.StatusCreated, map[string]any{
		"from_id":      conn.FromID,
		"to_id":        conn.ToID,
		"travel_turns": conn.TravelTurns,
	})
}

// getTravelHandler returns the valid outbound connections from locID for any
// campaign member (the owner or a joined player).
func getTravelHandler(w http.ResponseWriter, r *http.Request, campaignID, locID string) {
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

	playLocationsMu.Lock()
	defer playLocationsMu.Unlock()

	playConnectionsMu.Lock()
	defer playConnectionsMu.Unlock()

	destinations := make([]map[string]any, 0)
	for _, conn := range playConnections[campaignID] {
		if conn.FromID != locID {
			continue
		}
		dest, exists := playLocations[campaignID][conn.ToID]
		if !exists {
			continue
		}
		destinations = append(destinations, map[string]any{
			"id":           dest.ID,
			"name":         dest.Name,
			"travel_turns": conn.TravelTurns,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"destinations": destinations,
	})
}

type travelTurnRequest struct {
	DestinationID string `json:"destination_id"`
}

// travelTurnHandler lets the active player consume an exploration turn to
// travel along a valid outbound connection from the party's current
// location. Only the current actor may call this, and only when the
// destination is a valid outbound edge; both violations receive 409. On
// success a travel event is appended, the party's current location updates
// to the destination, and the turn passes to the dm.
func travelTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req travelTurnRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.DestinationID == "" {
		writeError(w, http.StatusBadRequest, "destination_id is required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.CurrentActor {
		writeError(w, http.StatusConflict, "it is not this actor's turn")
		return
	}

	playConnectionsMu.Lock()
	var travelTurns int
	found := false
	for _, conn := range playConnections[campaignID] {
		if conn.FromID == c.CurrentLocationID && conn.ToID == req.DestinationID {
			travelTurns = conn.TravelTurns
			found = true
			break
		}
	}
	playConnectionsMu.Unlock()
	if !found {
		writeError(w, http.StatusConflict, "destination is not a valid outbound connection")
		return
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "travel",
		Actor:      actor.Username,
		Type:       req.DestinationID,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		playNarrationsMu.Unlock()
		writeError(w, http.StatusInternalServerError, "failed to save travel event")
		return
	}
	playNarrations[campaignID] = append(events, n)
	playNarrationsMu.Unlock()

	c.CurrentLocationID = req.DestinationID
	c.CurrentActor = c.Owner
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence":       n.Sequence,
		"kind":           n.Kind,
		"actor":          n.Actor,
		"destination_id": req.DestinationID,
		"travel_turns":   travelTurns,
		"next_actor":     "dm",
	})
}

type restTurnRequest struct {
	Type string `json:"type"`
}

// restTurnHandler lets the active player consume an exploration turn to take
// a short or long rest. Only the current actor may call this, and only a
// party member (not the dm) has a character to rest; both violations receive
// 409. An invalid rest type receives 400. A long rest restores the acting
// character's hp_current to hp_max; a short rest leaves hp unchanged. On
// success a rest event is appended and the turn passes to the dm.
func restTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req restTurnRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Type != "long" && req.Type != "short" {
		writeError(w, http.StatusBadRequest, "type must be \"long\" or \"short\"")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	if actor.Username != c.CurrentActor {
		writeError(w, http.StatusConflict, "it is not this actor's turn")
		return
	}

	playMembersMu.Lock()
	member, isMember := playMembers[campaignID][actor.Username]
	playMembersMu.Unlock()
	if !isMember {
		writeError(w, http.StatusConflict, "only a player may take a rest turn")
		return
	}

	if req.Type == "long" {
		member.HPCurrent = member.HPMax
	}
	if err := savePlayMemberToDB(member); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character state")
		return
	}

	playNarrationsMu.Lock()
	events := playNarrations[campaignID]
	n := &playNarration{
		CampaignID: campaignID,
		Sequence:   len(events) + 1,
		Kind:       "rest",
		Actor:      actor.Username,
		Type:       req.Type,
	}
	if err := savePlayNarrationToDB(n); err != nil {
		playNarrationsMu.Unlock()
		writeError(w, http.StatusInternalServerError, "failed to save rest event")
		return
	}
	playNarrations[campaignID] = append(events, n)
	playNarrationsMu.Unlock()

	c.CurrentActor = c.Owner
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"sequence":   n.Sequence,
		"kind":       n.Kind,
		"actor":      n.Actor,
		"type":       n.Type,
		"hp_current": member.HPCurrent,
		"hp_max":     member.HPMax,
		"next_actor": "dm",
	})
}

// playRouter dispatches /v1/play/... routes.
func playRouter(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	if path == "/v1/play/campaigns" {
		createPlayCampaignHandler(w, r)
		return
	}

	if rest, ok := strings.CutPrefix(path, "/v1/play/campaigns/"); ok {
		if campaignID, suffix, found := strings.Cut(rest, "/"); found && campaignID != "" {
			switch suffix {
			case "members":
				joinPlayCampaignHandler(w, r, campaignID)
				return
			case "start":
				startPlayCampaignHandler(w, r, campaignID)
				return
			case "narrations":
				createNarrationHandler(w, r, campaignID)
				return
			case "actions":
				createActionHandler(w, r, campaignID)
				return
			case "resolutions":
				createResolutionHandler(w, r, campaignID)
				return
			case "turn":
				getTurnHandler(w, r, campaignID)
				return
			case "turn/nudge":
				nudgeTurnHandler(w, r, campaignID)
				return
			case "turn/travel":
				travelTurnHandler(w, r, campaignID)
				return
			case "turn/rest":
				restTurnHandler(w, r, campaignID)
				return
			case "my-turn":
				getMyTurnHandler(w, r, campaignID)
				return
			case "gm/status":
				getGMStatusHandler(w, r, campaignID)
				return
			case "onboarding":
				getOnboardingHandler(w, r, campaignID)
				return
			case "document":
				if r.Method == http.MethodGet {
					getDocumentHandler(w, r, campaignID)
				} else {
					updateDocumentHandler(w, r, campaignID)
				}
				return
			case "scenes":
				createSceneHandler(w, r, campaignID)
				return
			case "scenes/current":
				getCurrentSceneHandler(w, r, campaignID)
				return
			case "locations":
				createLocationHandler(w, r, campaignID)
				return
			case "encounters":
				createEncounterHandler(w, r, campaignID)
				return
			case "loot":
				createLootHandler(w, r, campaignID)
				return
			case "npcs":
				createPlayNPCHandler(w, r, campaignID)
				return
			case "factions":
				createPlayFactionHandler(w, r, campaignID)
				return
			case "relationships":
				if r.Method == http.MethodGet {
					listRelationshipsHandler(w, r, campaignID)
				} else {
					createRelationshipHandler(w, r, campaignID)
				}
				return
			case "clues":
				if r.Method == http.MethodGet {
					listCluesHandler(w, r, campaignID)
				} else {
					createClueHandler(w, r, campaignID)
				}
				return
			case "quests":
				if r.Method == http.MethodGet {
					listPlayQuestsHandler(w, r, campaignID)
				} else {
					createPlayQuestHandler(w, r, campaignID)
				}
				return
			case "world-events":
				if r.Method == http.MethodGet {
					listWorldEventsHandler(w, r, campaignID)
				} else {
					createWorldEventHandler(w, r, campaignID)
				}
				return
			case "calendar":
				if r.Method == http.MethodGet {
					getCalendarHandler(w, r, campaignID)
				} else {
					initCalendarHandler(w, r, campaignID)
				}
				return
			case "calendar/advance":
				advanceCalendarHandler(w, r, campaignID)
				return
			case "settlements":
				if r.Method == http.MethodGet {
					listSettlementsHandler(w, r, campaignID)
				} else {
					createSettlementHandler(w, r, campaignID)
				}
				return
			case "recipes":
				if r.Method == http.MethodGet {
					listRecipesHandler(w, r, campaignID)
				} else {
					createRecipeHandler(w, r, campaignID)
				}
				return
			case "downtime/activities":
				createDowntimeActivityHandler(w, r, campaignID)
				return
			case "session-zero":
				if r.Method == http.MethodGet {
					getSessionZeroHandler(w, r, campaignID)
				} else {
					updateSessionZeroHandler(w, r, campaignID)
				}
				return
			case "content":
				if r.Method == http.MethodGet {
					listContentHandler(w, r, campaignID)
				} else {
					createContentHandler(w, r, campaignID)
				}
				return
			case "notes":
				if r.Method == http.MethodGet {
					listNotesHandler(w, r, campaignID)
				} else {
					createNoteHandler(w, r, campaignID)
				}
				return
			case "whispers":
				if r.Method == http.MethodGet {
					listWhispersHandler(w, r, campaignID)
				} else {
					createWhisperHandler(w, r, campaignID)
				}
				return
			case "invitations":
				if r.Method == http.MethodGet {
					listInvitationsHandler(w, r, campaignID)
				} else {
					createInvitationHandler(w, r, campaignID)
				}
				return
			case "delegations":
				grantDelegationHandler(w, r, campaignID)
				return
			case "audit-events":
				if r.Method == http.MethodGet {
					listAuditEventsHandler(w, r, campaignID)
				} else {
					createAuditEventHandler(w, r, campaignID)
				}
				return
			case "projection-events":
				createProjectionEventHandler(w, r, campaignID)
				return
			case "projection":
				getProjectionHandler(w, r, campaignID)
				return
			case "projection/rebuild":
				getProjectionHandler(w, r, campaignID)
				return
			case "idempotent-events":
				if r.Method == http.MethodGet {
					listIdempotentEventsHandler(w, r, campaignID)
				} else {
					createIdempotentEventHandler(w, r, campaignID)
				}
				return
			case "safe-turns":
				if r.Method == http.MethodGet {
					listSafeTurnsHandler(w, r, campaignID)
				} else {
					submitSafeTurnHandler(w, r, campaignID)
				}
				return
			case "transactional-transfers":
				if r.Method == http.MethodGet {
					listTransactionalTransfersHandler(w, r, campaignID)
				} else {
					createTransactionalTransferHandler(w, r, campaignID)
				}
				return
			case "exports":
				if r.Method == http.MethodGet {
					listExportsHandler(w, r, campaignID)
				} else {
					createExportHandler(w, r, campaignID)
				}
				return
			case "imports":
				createImportHandler(w, r, campaignID)
				return
			case "import-state":
				getImportStateHandler(w, r, campaignID)
				return
			case "migrations":
				createMigrationHandler(w, r, campaignID)
				return
			case "migration-state":
				getMigrationStateHandler(w, r, campaignID)
				return
			case "search-records":
				if r.Method == http.MethodGet {
					listSearchRecordsHandler(w, r, campaignID)
				} else {
					createSearchRecordHandler(w, r, campaignID)
				}
				return
			case "rate-events":
				if r.Method == http.MethodGet {
					listRateEventsHandler(w, r, campaignID)
				} else {
					createRateEventHandler(w, r, campaignID)
				}
				return
			case "metrics":
				getMetricsHandler(w, r, campaignID)
				return
			case "service-mode":
				serviceModeHandler(w, r, campaignID)
				return
			case "backups":
				if r.Method == http.MethodGet {
					listBackupsHandler(w, r, campaignID)
				} else {
					createBackupHandler(w, r, campaignID)
				}
				return
			case "replay-events":
				createReplayEventHandler(w, r, campaignID)
				return
			case "replay":
				getReplayHandler(w, r, campaignID)
				return
			case "replay/check":
				getReplayHandler(w, r, campaignID)
				return
			case "rng-seed":
				configureRngSeedHandler(w, r, campaignID)
				return
			case "rng-rolls":
				appendRngRollHandler(w, r, campaignID)
				return
			case "rng-ledger":
				getRngLedgerHandler(w, r, campaignID)
				return
			case "moderation/reports":
				if r.Method == http.MethodGet {
					listModerationReportsHandler(w, r, campaignID)
				} else {
					createModerationReportHandler(w, r, campaignID)
				}
				return
			case "safety-boundaries":
				if r.Method == http.MethodGet {
					getSafetyBoundariesHandler(w, r, campaignID)
				} else {
					replaceSafetyBoundariesHandler(w, r, campaignID)
				}
				return
			case "safety-checks":
				createSafetyCheckHandler(w, r, campaignID)
				return
			case "safety-events":
				listSafetyEventsHandler(w, r, campaignID)
				return
			case "fixture-seeds":
				createFixtureSeedHandler(w, r, campaignID)
				return
			case "fixture-state":
				getFixtureStateHandler(w, r, campaignID)
				return
			case "spectators":
				createSpectatorHandler(w, r, campaignID)
				return
			case "spectator-view":
				spectatorViewHandler(w, r, campaignID)
				return
			case "messages":
				createMessageHandler(w, r, campaignID)
				return
			case "feed-events":
				createFeedEventHandler(w, r, campaignID)
				return
			case "event-feed":
				listFeedEventsHandler(w, r, campaignID)
				return
			}

			if backupRest, ok := strings.CutPrefix(suffix, "backups/"); ok && backupRest != "" {
				if backupID, action, found := strings.Cut(backupRest, "/"); found && backupID != "" && action == "restore" {
					restoreBackupHandler(w, r, campaignID, backupID)
					return
				}
			}

			if exportRest, ok := strings.CutPrefix(suffix, "exports/"); ok && exportRest != "" {
				getExportHandler(w, r, campaignID, exportRest)
				return
			}

			if invRest, ok := strings.CutPrefix(suffix, "invitations/"); ok && invRest != "" {
				if invitationID, action, found := strings.Cut(invRest, "/"); found && invitationID != "" && action == "accept" {
					acceptInvitationHandler(w, r, campaignID, invitationID)
					return
				}
			}

			if delRest, ok := strings.CutPrefix(suffix, "delegations/"); ok && delRest != "" {
				if delRest == "audit" {
					delegationAuditHandler(w, r, campaignID)
					return
				}
				revokeDelegationHandler(w, r, campaignID, delRest)
				return
			}

			if noteRest, ok := strings.CutPrefix(suffix, "notes/"); ok && noteRest != "" {
				if r.Method == http.MethodPut {
					updateNoteHandler(w, r, campaignID, noteRest)
				} else {
					getNoteHandler(w, r, campaignID, noteRest)
				}
				return
			}

			if contentRest, ok := strings.CutPrefix(suffix, "content/"); ok && contentRest != "" {
				if contentID, action, found := strings.Cut(contentRest, "/"); found && contentID != "" && action == "tags" {
					updateContentTagsHandler(w, r, campaignID, contentID)
					return
				}
			}

			if recipeRest, ok := strings.CutPrefix(suffix, "recipes/"); ok && recipeRest != "" {
				if recipeID, action, found := strings.Cut(recipeRest, "/"); found && recipeID != "" && action == "craft" {
					craftRecipeHandler(w, r, campaignID, recipeID)
					return
				}
			}

			if settlementRest, ok := strings.CutPrefix(suffix, "settlements/"); ok && settlementRest != "" {
				if settlementID, action, found := strings.Cut(settlementRest, "/"); found && settlementID != "" {
					if action == "discover" {
						discoverSettlementHandler(w, r, campaignID, settlementID)
						return
					}
					if shopsRest, ok := strings.CutPrefix(action, "shops"); ok {
						if shopsRest == "" {
							createShopHandler(w, r, campaignID, settlementID)
							return
						}
						if shopPath, ok := strings.CutPrefix(shopsRest, "/"); ok && shopPath != "" {
							if shopID, shopAction, found2 := strings.Cut(shopPath, "/"); found2 && shopID != "" {
								switch shopAction {
								case "buy":
									buyShopHandler(w, r, campaignID, settlementID, shopID)
									return
								case "sell":
									sellShopHandler(w, r, campaignID, settlementID, shopID)
									return
								}
							} else if !found2 {
								getShopHandler(w, r, campaignID, settlementID, shopPath)
								return
							}
						}
					}
				} else {
					updateSettlementHandler(w, r, campaignID, settlementRest)
					return
				}
			}

			if modRest, ok := strings.CutPrefix(suffix, "moderation/reports/"); ok && modRest != "" {
				if reportID, action, found := strings.Cut(modRest, "/"); found && reportID != "" && action == "resolution" {
					resolveModerationReportHandler(w, r, campaignID, reportID)
					return
				}
			}

			if weRest, ok := strings.CutPrefix(suffix, "world-events/"); ok && weRest != "" {
				if eventID, action, found := strings.Cut(weRest, "/"); found && eventID != "" && action == "resolve" {
					resolveWorldEventHandler(w, r, campaignID, eventID)
					return
				}
			}

			if questRest, ok := strings.CutPrefix(suffix, "quests/"); ok && questRest != "" {
				if questID, action, found := strings.Cut(questRest, "/"); found && questID != "" {
					switch action {
					case "state":
						updateQuestStateHandler(w, r, campaignID, questID)
						return
					case "rewards":
						configureQuestRewardsHandler(w, r, campaignID, questID)
						return
					case "rewards/award":
						awardQuestRewardsHandler(w, r, campaignID, questID)
						return
					}
				}
			}

			if relRest, ok := strings.CutPrefix(suffix, "relationships/"); ok && relRest != "" {
				parts := strings.Split(relRest, "/")
				if len(parts) == 3 && parts[0] != "" && parts[1] != "" && parts[2] != "" {
					updateRelationshipHandler(w, r, campaignID, parts[0], parts[1], parts[2])
					return
				}
			}

			if lootRest, ok := strings.CutPrefix(suffix, "loot/"); ok && lootRest != "" {
				if lootID, action, found := strings.Cut(lootRest, "/"); found && lootID != "" {
					switch action {
					case "votes":
						voteLootHandler(w, r, campaignID, lootID)
						return
					case "assign":
						assignLootHandler(w, r, campaignID, lootID)
						return
					}
				} else {
					getLootHandler(w, r, campaignID, lootRest)
					return
				}
			}

			if npcRest, ok := strings.CutPrefix(suffix, "npcs/"); ok && npcRest != "" {
				if npcID, action, found := strings.Cut(npcRest, "/"); found && npcID != "" {
					switch action {
					case "agenda":
						updateNPCAgendaHandler(w, r, campaignID, npcID)
						return
					case "dialogue":
						if r.Method == http.MethodGet {
							getNPCDialogueHandler(w, r, campaignID, npcID)
						} else {
							createNPCDialogueHandler(w, r, campaignID, npcID)
						}
						return
					}
				} else {
					getNPCHandler(w, r, campaignID, npcRest)
					return
				}
			}

			if factionRest, ok := strings.CutPrefix(suffix, "factions/"); ok && factionRest != "" {
				if factionID, action, found := strings.Cut(factionRest, "/"); found && factionID != "" {
					if action == "reputation" {
						if r.Method == http.MethodGet {
							getReputationHandler(w, r, campaignID, factionID)
						} else {
							createReputationHandler(w, r, campaignID, factionID)
						}
						return
					}
				}
			}

			if sceneRest, ok := strings.CutPrefix(suffix, "scenes/"); ok {
				if sceneID, action, found := strings.Cut(sceneRest, "/"); found && sceneID != "" {
					switch action {
					case "enter":
						enterSceneHandler(w, r, campaignID, sceneID)
						return
					case "close":
						closeSceneHandler(w, r, campaignID, sceneID)
						return
					}
				}
			}

			if locRest, ok := strings.CutPrefix(suffix, "locations/"); ok {
				if locID, action, found := strings.Cut(locRest, "/"); found && locID != "" {
					switch action {
					case "connections":
						createConnectionHandler(w, r, campaignID, locID)
						return
					case "travel":
						getTravelHandler(w, r, campaignID, locID)
						return
					}
				}
			}

			if charRest, ok := strings.CutPrefix(suffix, "characters/"); ok {
				if charID, action, found := strings.Cut(charRest, "/"); found && charID != "" {
					switch action {
					case "damage":
						characterDamageHandler(w, r, campaignID, charID)
						return
					case "death-saves":
						deathSaveHandler(w, r, campaignID, charID)
						return
					case "status":
						characterStatusHandler(w, r, campaignID, charID)
						return
					case "sheet":
						characterSheetHandler(w, r, campaignID, charID)
						return
					case "owner":
						characterOwnerHandler(w, r, campaignID, charID)
						return
					case "claim":
						claimCharacterHandler(w, r, campaignID, charID)
						return
					case "transfer":
						transferCharacterHandler(w, r, campaignID, charID)
						return
					case "build":
						buildCharacterHandler(w, r, campaignID, charID)
						return
					case "level-up":
						levelUpHandler(w, r, campaignID, charID)
						return
					case "skill-check":
						skillCheckHandler(w, r, campaignID, charID)
						return
					case "spells":
						if r.Method == http.MethodGet {
							listSpellsHandler(w, r, campaignID, charID)
						} else {
							addSpellHandler(w, r, campaignID, charID)
						}
						return
					case "prepared-spells":
						if r.Method == http.MethodGet {
							getPreparedSpellsHandler(w, r, campaignID, charID)
						} else {
							setPreparedSpellsHandler(w, r, campaignID, charID)
						}
						return
					case "casts":
						if r.Method == http.MethodGet {
							listCastsHandler(w, r, campaignID, charID)
						} else {
							castSpellHandler(w, r, campaignID, charID)
						}
						return
					case "concentration":
						switch r.Method {
						case http.MethodGet:
							getConcentrationHandler(w, r, campaignID, charID)
						case http.MethodDelete:
							clearConcentrationHandler(w, r, campaignID, charID)
						default:
							setConcentrationHandler(w, r, campaignID, charID)
						}
						return
					case "concentration/advance-turn":
						advanceConcentrationTurnHandler(w, r, campaignID, charID)
						return
					case "inventory/items":
						if r.Method == http.MethodGet {
							listInventoryItemsHandler(w, r, campaignID, charID)
						} else {
							addInventoryItemHandler(w, r, campaignID, charID)
						}
						return
					case "currency":
						getCurrencyHandler(w, r, campaignID, charID)
						return
					case "currency/transfers":
						createTransferHandler(w, r, campaignID, charID)
						return
					case "rewards":
						getCharacterRewardsHandler(w, r, campaignID, charID)
						return
					case "downtime/allocations":
						allocateDowntimeHandler(w, r, campaignID, charID)
						return
					}

					if daRest, ok := strings.CutPrefix(action, "downtime/allocations/"); ok && daRest != "" {
						if activityID, sub, found := strings.Cut(daRest, "/"); found && sub == "progress" {
							progressDowntimeHandler(w, r, campaignID, charID, activityID)
							return
						} else if !found {
							getDowntimeAllocationHandler(w, r, campaignID, charID, daRest)
							return
						}
					}

					if itemID, ok := strings.CutPrefix(action, "inventory/items/"); ok && itemID != "" {
						if consumeItemID, ok := strings.CutSuffix(itemID, "/consume"); ok && consumeItemID != "" {
							consumeInventoryItemHandler(w, r, campaignID, charID, consumeItemID)
							return
						}
						removeInventoryItemHandler(w, r, campaignID, charID, itemID)
						return
					}

					if eqRest, ok := strings.CutPrefix(action, "equipment/"); ok && eqRest != "" {
						if slot, sub, found := strings.Cut(eqRest, "/"); found {
							if sub == "attune" {
								attuneEquipmentHandler(w, r, campaignID, charID, slot)
								return
							}
						} else {
							switch r.Method {
							case http.MethodGet:
								getEquipmentHandler(w, r, campaignID, charID, slot)
							default:
								equipItemHandler(w, r, campaignID, charID, slot)
							}
							return
						}
					}
				}
			}

			if encRest, ok := strings.CutPrefix(suffix, "encounters/"); ok {
				if encID, action, found := strings.Cut(encRest, "/"); found && encID != "" {
					if action == "monsters" {
						addMonsterHandler(w, r, campaignID, encID)
						return
					}
					if monsterID, ok := strings.CutPrefix(action, "monsters/"); ok && monsterID != "" {
						removeMonsterHandler(w, r, campaignID, encID, monsterID)
						return
					}
					if action == "combatants" {
						bindCombatantHandler(w, r, campaignID, encID)
						return
					}
					if member, ok := strings.CutPrefix(action, "combatants/"); ok && member != "" {
						unbindCombatantHandler(w, r, campaignID, encID, member)
						return
					}
					if action == "turn" {
						getEncounterTurnHandler(w, r, campaignID, encID)
						return
					}
					if action == "turn/advance" {
						advanceEncounterTurnHandler(w, r, campaignID, encID)
						return
					}
					if action == "turn/delay" {
						delayEncounterTurnHandler(w, r, campaignID, encID)
						return
					}
					if action == "turn/ready" {
						readyEncounterTurnHandler(w, r, campaignID, encID)
						return
					}
					if action == "actions" {
						createCombatActionHandler(w, r, campaignID, encID)
						return
					}
					if action == "damage" {
						damageHandler(w, r, campaignID, encID)
						return
					}
					if action == "heal" {
						healHandler(w, r, campaignID, encID)
						return
					}
					if action == "conditions" {
						addPlayConditionHandler(w, r, campaignID, encID)
						return
					}
					if action == "status" {
						getEncounterStatusHandler(w, r, campaignID, encID)
						return
					}
					if action == "rewards" {
						awardEncounterRewardsHandler(w, r, campaignID, encID)
						return
					}
					if action == "close" {
						closeEncounterHandler(w, r, campaignID, encID)
						return
					}
					if action == "end" {
						endEncounterHandler(w, r, campaignID, encID)
						return
					}
				}
			}
		}
	}

	writeError(w, http.StatusNotFound, "unknown route")
}
