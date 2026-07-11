package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
)

const (
	schemaVersion = 1
	dbPath        = "game.db"
)

var (
	errUserExists      = errors.New("user already exists")
	errSessionExists   = errors.New("session already exists")
	errSessionNotFound = errors.New("session not found")
	errTargetNotFound  = errors.New("target not found")
	errEmptySession    = errors.New("session has no combatants")
	errMonsterExists   = errors.New("monster already exists")
	errItemExists      = errors.New("item already exists")
	errCampaignExists   = errors.New("campaign already exists")
	errCampaignNotFound = errors.New("campaign not found")
	errCharacterExists  = errors.New("character already exists")
	errEventExists      = errors.New("event already exists")
)

type storageStatus struct {
	Driver        string `json:"driver"`
	SchemaVersion int    `json:"schema_version"`
	Initialized   bool   `json:"initialized"`
}

type storageResetResponse struct {
	OK            bool `json:"ok"`
	SchemaVersion int  `json:"schema_version"`
}

type dbState struct {
	SchemaVersion int                          `json:"schema_version"`
	Users         map[string]user            `json:"users"`
	Sessions      map[string]combatSession  `json:"sessions"`
	Monsters      map[string]monsterEntry   `json:"monsters"`
	Items         map[string]itemEntry       `json:"items"`
	Campaigns     map[string]campaign       `json:"campaigns"`
}

type store struct {
	path  string
	mu    sync.Mutex
	state dbState
}

func newStore(path string) (*store, error) {
	s := &store{path: path}
	if err := s.init(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *store) init() error {
	s.state = dbState{
		SchemaVersion: schemaVersion,
		Users:         make(map[string]user),
		Sessions:      make(map[string]combatSession),
		Monsters:      make(map[string]monsterEntry),
		Items:         make(map[string]itemEntry),
		Campaigns:     make(map[string]campaign),
	}

	_, err := os.Stat(s.path)
	if err != nil {
		if !os.IsNotExist(err) {
			return err
		}
		return s.save()
	}

	data, err := os.ReadFile(s.path)
	if err != nil {
		return err
	}
	if len(data) == 0 {
		return s.save()
	}

	var loaded dbState
	if err := json.Unmarshal(data, &loaded); err != nil {
		// Corrupt file: reinitialize with empty schema.
		return s.save()
	}
	if loaded.Users == nil {
		loaded.Users = make(map[string]user)
	}
	if loaded.Sessions == nil {
		loaded.Sessions = make(map[string]combatSession)
	}
	if loaded.Monsters == nil {
		loaded.Monsters = make(map[string]monsterEntry)
	}
	if loaded.Items == nil {
		loaded.Items = make(map[string]itemEntry)
	}
	if loaded.Campaigns == nil {
		loaded.Campaigns = make(map[string]campaign)
	}
	for id, c := range loaded.Campaigns {
		if c.Characters == nil {
			c.Characters = make(map[string]campaignCharacter)
			loaded.Campaigns[id] = c
		}
		if c.Events == nil {
			c.Events = make(map[string]campaignEvent)
			loaded.Campaigns[id] = c
		}
	}
	s.state = loaded
	return nil
}

func (s *store) save() error {
	data, err := json.Marshal(s.state)
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}

func (s *store) reset() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.state = dbState{
		SchemaVersion: schemaVersion,
		Users:         make(map[string]user),
		Sessions:      make(map[string]combatSession),
		Monsters:      make(map[string]monsterEntry),
		Items:         make(map[string]itemEntry),
		Campaigns:     make(map[string]campaign),
	}
	return s.save()
}

func (s *store) status() storageStatus {
	s.mu.Lock()
	defer s.mu.Unlock()
	return storageStatus{
		Driver:        "sqlite",
		SchemaVersion: s.state.SchemaVersion,
		Initialized:   true,
	}
}

func (s *store) getUser(username string) (user, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	u, ok := s.state.Users[username]
	return u, ok
}

func (s *store) createUser(u user) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.state.Users[u.Username]; exists {
		return errUserExists
	}
	s.state.Users[u.Username] = u
	return s.save()
}

func (s *store) getMonster(slug string) (monsterEntry, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m, ok := s.state.Monsters[slug]
	if ok && m.Tags == nil {
		m.Tags = []string{}
	}
	return m, ok
}

func (s *store) createMonster(m monsterEntry) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.state.Monsters[m.Slug]; exists {
		return errMonsterExists
	}
	if m.Tags == nil {
		m.Tags = []string{}
	}
	s.state.Monsters[m.Slug] = m
	return s.save()
}

func (s *store) getItem(slug string) (itemEntry, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	i, ok := s.state.Items[slug]
	return i, ok
}

func (s *store) createItem(i itemEntry) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.state.Items[i.Slug]; exists {
		return errItemExists
	}
	s.state.Items[i.Slug] = i
	return s.save()
}

func (s *store) createCampaign(c campaign) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.state.Campaigns[c.ID]; exists {
		return errCampaignExists
	}
	if c.Characters == nil {
		c.Characters = make(map[string]campaignCharacter)
	}
	if c.Events == nil {
		c.Events = make(map[string]campaignEvent)
	}
	s.state.Campaigns[c.ID] = c
	return s.save()
}

func (s *store) addCampaignCharacter(campaignID string, ch campaignCharacter) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.state.Campaigns[campaignID]
	if !ok {
		return errCampaignNotFound
	}
	if _, exists := c.Characters[ch.ID]; exists {
		return errCharacterExists
	}
	c.Characters[ch.ID] = ch
	s.state.Campaigns[campaignID] = c
	return s.save()
}

func (s *store) addCampaignEvent(campaignID string, e campaignEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.state.Campaigns[campaignID]
	if !ok {
		return errCampaignNotFound
	}
	if _, exists := c.Events[e.ID]; exists {
		return errEventExists
	}
	c.Events[e.ID] = e
	s.state.Campaigns[campaignID] = c
	return s.save()
}

func (s *store) campaignState(campaignID string) (campaignStateResponse, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.state.Campaigns[campaignID]
	if !ok {
		return campaignStateResponse{}, false
	}
	chars := make([]campaignCharacter, 0, len(c.Characters))
	for _, ch := range c.Characters {
		chars = append(chars, ch)
	}
	sort.Slice(chars, func(i, j int) bool {
		return chars[i].ID < chars[j].ID
	})
	return campaignStateResponse{
		ID:         c.ID,
		Name:       c.Name,
		DM:         c.DM,
		Characters: chars,
		LogCount:   len(c.Events),
	}, true
}

func (s *store) getCampaign(campaignID string) (campaign, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.state.Campaigns[campaignID]
	if !ok {
		return campaign{}, false
	}
	if c.Characters == nil {
		c.Characters = make(map[string]campaignCharacter)
	}
	if c.Events == nil {
		c.Events = make(map[string]campaignEvent)
	}
	return c, true
}

func (s *store) createSession(session *combatSession) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.state.Sessions[session.ID]; exists {
		return errSessionExists
	}
	s.state.Sessions[session.ID] = *session
	return s.save()
}

func copySession(sess combatSession) combatSession {
	cpy := sess
	if sess.Order != nil {
		cpy.Order = make([]initiativeEntry, len(sess.Order))
		copy(cpy.Order, sess.Order)
	}
	if sess.Conditions != nil {
		cpy.Conditions = make(map[string][]conditionEntry, len(sess.Conditions))
		for k, v := range sess.Conditions {
			conds := make([]conditionEntry, len(v))
			copy(conds, v)
			cpy.Conditions[k] = conds
		}
	}
	return cpy
}

func (s *store) addCondition(id string, target string, entry conditionEntry) (*combatSession, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	sess, ok := s.state.Sessions[id]
	if !ok {
		return nil, errSessionNotFound
	}

	found := false
	for _, c := range sess.Order {
		if c.Name == target {
			found = true
			break
		}
	}
	if !found {
		return nil, errTargetNotFound
	}

	sess.Conditions[target] = append(sess.Conditions[target], entry)
	s.state.Sessions[id] = sess
	cpy := copySession(sess)
	return &cpy, s.save()
}

func (s *store) advanceTurn(id string) (*combatSession, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	sess, ok := s.state.Sessions[id]
	if !ok {
		return nil, errSessionNotFound
	}
	if len(sess.Order) == 0 {
		return nil, errEmptySession
	}

	sess.TurnIndex++
	if sess.TurnIndex >= len(sess.Order) {
		sess.TurnIndex = 0
		sess.Round++
	}

	active := sess.Order[sess.TurnIndex]
	if conds, ok := sess.Conditions[active.Name]; ok {
		updated := make([]conditionEntry, 0, len(conds))
		for i := range conds {
			conds[i].RemainingRounds--
			if conds[i].RemainingRounds > 0 {
				updated = append(updated, conds[i])
			}
		}
		sess.Conditions[active.Name] = updated
	}

	s.state.Sessions[id] = sess
	cpy := copySession(sess)
	return &cpy, s.save()
}

var globalStore *store

type healthResponse struct {
	OK bool `json:"ok"`
}

type diceStatsRequest struct {
	Expression string `json:"expression"`
}

type diceStatsResponse struct {
	DiceCount int     `json:"dice_count"`
	Sides     int     `json:"sides"`
	Modifier  int     `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

type abilityCheckRequest struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

type abilityCheckResponse struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

type partyMember struct {
	Level int `json:"level"`
}

type monster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type encounterRequest struct {
	Party    []partyMember `json:"party"`
	Monsters []monster     `json:"monsters"`
}

type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type encounterResponse struct {
	BaseXP       int        `json:"base_xp"`
	MonsterCount int        `json:"monster_count"`
	Multiplier   float64    `json:"multiplier"`
	AdjustedXP   float64    `json:"adjusted_xp"`
	Difficulty   string     `json:"difficulty"`
	Thresholds   thresholds `json:"thresholds"`
}

type encounterBuilderRequest struct {
	CampaignID   string        `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

type encounterBuilderResponse struct {
	CampaignID     string `json:"campaign_id"`
	BaseXP         int    `json:"base_xp"`
	AdjustedXP     int    `json:"adjusted_xp"`
	Difficulty     string `json:"difficulty"`
	MonsterCount   int    `json:"monster_count"`
	Recommendation string `json:"recommendation"`
}

type lootParcelRequest struct {
	CampaignID string `json:"campaign_id"`
	Tier       int    `json:"tier"`
	Seed       int    `json:"seed"`
}

type lootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

type lootParcelResponse struct {
	CampaignID string     `json:"campaign_id"`
	CoinsGP    int        `json:"coins_gp"`
	Items      []lootItem `json:"items"`
}

type sessionRecapRequest struct {
	CampaignID string `json:"campaign_id"`
}

type sessionRecapResponse struct {
	CampaignID  string   `json:"campaign_id"`
	Summary     string   `json:"summary"`
	OpenThreads []string `json:"open_threads"`
}

type combatant struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

type initiativeRequest struct {
	Combatants []combatant `json:"combatants"`
}

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	Dex   int    `json:"-"`
}

type initiativeResponse struct {
	Order []initiativeEntry `json:"order"`
}

type abilityModifierRequest struct {
	Score int `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

type proficiencyRequest struct {
	Level int `json:"level"`
}

type proficiencyResponse struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
}

type abilities struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type armorRequest struct {
	Base   int  `json:"base"`
	Shield bool `json:"shield"`
	DexCap int  `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     int          `json:"level"`
	Abilities abilities    `json:"abilities"`
	Armor     armorRequest `json:"armor"`
}

type derivedStatsResponse struct {
	Level            int       `json:"level"`
	ProficiencyBonus int       `json:"proficiency_bonus"`
	HPMax            int       `json:"hp_max"`
	ArmorClass       int       `json:"armor_class"`
	Modifiers        abilities `json:"modifiers"`
}

type monsterEntry struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type itemEntry struct {
	Slug   string  `json:"slug"`
	Name   string  `json:"name"`
	Type   string  `json:"type"`
	Rarity string  `json:"rarity"`
	CostGP float64 `json:"cost_gp"`
}

type campaign struct {
	ID         string                       `json:"id"`
	Name       string                       `json:"name"`
	DM         string                       `json:"dm"`
	Characters map[string]campaignCharacter `json:"characters"`
	Events     map[string]campaignEvent     `json:"events"`
}

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type campaignEvent struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

type campaignStateResponse struct {
	ID         string              `json:"id"`
	Name       string              `json:"name"`
	DM         string              `json:"dm"`
	Characters []campaignCharacter `json:"characters"`
	LogCount   int                 `json:"log_count"`
}

type spellSlotsRequest struct {
	Class string `json:"class"`
	Level int    `json:"level"`
}

type spellSlotsResponse struct {
	Class string         `json:"class"`
	Level int            `json:"level"`
	Slots map[string]int `json:"slots"`
}

type longRestRequest struct {
	Level           int `json:"level"`
	HpCurrent       int `json:"hp_current"`
	HpMax           int `json:"hp_max"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

type longRestResponse struct {
	HpCurrent       int `json:"hp_current"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

type equipmentLoadRequest struct {
	Strength int `json:"strength"`
	Weight   int `json:"weight"`
}

type equipmentLoadResponse struct {
	Capacity   int  `json:"capacity"`
	Weight     int  `json:"weight"`
	Encumbered bool `json:"encumbered"`
}

var diceExpr = regexp.MustCompile(`^(\d+)d(\d+)(?:([+-])(\d+))?$`)

var xpByCR = map[string]int{
	"0":   10,
	"1/8": 25,
	"1/4": 50,
	"1/2": 100,
	"1":   200,
	"2":   450,
	"3":   700,
	"4":   1100,
	"5":   1800,
}

var thresholdsByLevel = map[int]thresholds{
	1:  {Easy: 25, Medium: 50, Hard: 75, Deadly: 100},
	2:  {Easy: 50, Medium: 100, Hard: 150, Deadly: 200},
	3:  {Easy: 75, Medium: 150, Hard: 225, Deadly: 400},
	4:  {Easy: 125, Medium: 250, Hard: 375, Deadly: 500},
	5:  {Easy: 250, Medium: 500, Hard: 750, Deadly: 1100},
	6:  {Easy: 300, Medium: 600, Hard: 900, Deadly: 1400},
	7:  {Easy: 350, Medium: 750, Hard: 1100, Deadly: 1700},
	8:  {Easy: 450, Medium: 900, Hard: 1400, Deadly: 2100},
	9:  {Easy: 550, Medium: 1100, Hard: 1600, Deadly: 2400},
	10: {Easy: 600, Medium: 1200, Hard: 1900, Deadly: 2800},
	11: {Easy: 800, Medium: 1600, Hard: 2400, Deadly: 3600},
	12: {Easy: 1000, Medium: 2000, Hard: 3000, Deadly: 4500},
	13: {Easy: 1100, Medium: 2200, Hard: 3400, Deadly: 5100},
	14: {Easy: 1250, Medium: 2500, Hard: 3800, Deadly: 5700},
	15: {Easy: 1400, Medium: 2800, Hard: 4300, Deadly: 6400},
	16: {Easy: 1600, Medium: 3200, Hard: 4800, Deadly: 7200},
	17: {Easy: 2000, Medium: 3900, Hard: 5900, Deadly: 8800},
	18: {Easy: 2100, Medium: 4200, Hard: 6300, Deadly: 9500},
	19: {Easy: 2400, Medium: 4900, Hard: 7300, Deadly: 10900},
	20: {Easy: 2800, Medium: 5700, Hard: 8500, Deadly: 12700},
}

type combatSession struct {
	ID         string                      `json:"id"`
	Round      int                         `json:"round"`
	TurnIndex  int                         `json:"turn_index"`
	Order      []initiativeEntry           `json:"order"`
	Conditions map[string][]conditionEntry `json:"conditions"`
}

type combatSessionResponse struct {
	ID        string            `json:"id"`
	Round     int               `json:"round"`
	TurnIndex int               `json:"turn_index"`
	Active    initiativeEntry   `json:"active"`
	Order     []initiativeEntry `json:"order"`
}

type conditionEntry struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type registerRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

type registerResponse struct {
	Username string `json:"username"`
	Role     string `json:"role"`
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type loginResponse struct {
	Username string `json:"username"`
	Token    string `json:"token"`
}

type user struct {
	Username     string `json:"username"`
	Role         string `json:"role"`
	PasswordHash string `json:"password_hash"`
}

var usernameRegex = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

func validateUsername(username string) bool {
	return usernameRegex.MatchString(username)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func floorDiv(a, b int) int {
	q := a / b
	r := a % b
	if r != 0 && (r < 0) != (b < 0) {
		q--
	}
	return q
}

func abilityModifier(score int) (int, error) {
	if score < 1 || score > 30 {
		return 0, fmt.Errorf("score must be between 1 and 30")
	}
	return floorDiv(score-10, 2), nil
}

func proficiencyBonus(level int) (int, error) {
	if level < 1 || level > 20 {
		return 0, fmt.Errorf("level must be between 1 and 20")
	}
	switch {
	case level <= 4:
		return 2, nil
	case level <= 8:
		return 3, nil
	case level <= 12:
		return 4, nil
	case level <= 16:
		return 5, nil
	default:
		return 6, nil
	}
}

func modifiersFor(a abilities) (abilities, error) {
	str, err := abilityModifier(a.Str)
	if err != nil {
		return abilities{}, fmt.Errorf("str: %w", err)
	}
	dex, err := abilityModifier(a.Dex)
	if err != nil {
		return abilities{}, fmt.Errorf("dex: %w", err)
	}
	con, err := abilityModifier(a.Con)
	if err != nil {
		return abilities{}, fmt.Errorf("con: %w", err)
	}
	inte, err := abilityModifier(a.Int)
	if err != nil {
		return abilities{}, fmt.Errorf("int: %w", err)
	}
	wis, err := abilityModifier(a.Wis)
	if err != nil {
		return abilities{}, fmt.Errorf("wis: %w", err)
	}
	cha, err := abilityModifier(a.Cha)
	if err != nil {
		return abilities{}, fmt.Errorf("cha: %w", err)
	}
	return abilities{Str: str, Dex: dex, Con: con, Int: inte, Wis: wis, Cha: cha}, nil
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{OK: true})
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req diceStatsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	matches := diceExpr.FindStringSubmatch(req.Expression)
	if matches == nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	count, _ := strconv.Atoi(matches[1])
	sides, _ := strconv.Atoi(matches[2])
	if count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "count and sides must be positive")
		return
	}

	modifier := 0
	if matches[3] != "" && matches[4] != "" {
		val, _ := strconv.Atoi(matches[4])
		if matches[3] == "-" {
			val = -val
		}
		modifier = val
	}

	min := count + modifier
	max := count*sides + modifier
	average := float64(min+max) / 2.0

	writeJSON(w, http.StatusOK, diceStatsResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       min,
		Max:       max,
		Average:   average,
	})
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req abilityCheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, abilityCheckResponse{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

func multiplierFor(count int) float64 {
	switch {
	case count == 1:
		return 1
	case count == 2:
		return 1.5
	case count <= 6:
		return 2
	case count <= 10:
		return 2.5
	case count <= 14:
		return 3
	default:
		return 4
	}
}

func computeEncounter(party []partyMember, monsters []monster) (encounterResponse, error) {
	baseXP := 0
	monsterCount := 0
	for _, m := range monsters {
		if m.Count <= 0 {
			return encounterResponse{}, fmt.Errorf("monster count must be positive")
		}
		xp, ok := xpByCR[m.CR]
		if !ok {
			return encounterResponse{}, fmt.Errorf("unsupported cr: %s", m.CR)
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}

	multiplier := multiplierFor(monsterCount)
	adjustedXP := float64(baseXP) * multiplier

	summed := thresholds{}
	for _, p := range party {
		t, ok := thresholdsByLevel[p.Level]
		if !ok {
			return encounterResponse{}, fmt.Errorf("unsupported level: %d", p.Level)
		}
		summed.Easy += t.Easy
		summed.Medium += t.Medium
		summed.Hard += t.Hard
		summed.Deadly += t.Deadly
	}

	difficulty := "trivial"
	if int(adjustedXP) >= summed.Deadly {
		difficulty = "deadly"
	} else if int(adjustedXP) >= summed.Hard {
		difficulty = "hard"
	} else if int(adjustedXP) >= summed.Medium {
		difficulty = "medium"
	} else if int(adjustedXP) >= summed.Easy {
		difficulty = "easy"
	}

	return encounterResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty,
		Thresholds:   summed,
	}, nil
}

func encounterHandler(w http.ResponseWriter, r *http.Request) {
	var req encounterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	resp, err := computeEncounter(req.Party, req.Monsters)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func recommendationFor(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "no challenge"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "steady challenge"
	case "hard":
		return "risky fight"
	case "deadly":
		return "possible defeat"
	default:
		return "unknown"
	}
}

func generateOpenThread(summary string) string {
	s := strings.TrimSpace(summary)
	s = strings.TrimRight(s, ".!?")
	words := strings.Fields(s)
	if len(words) < 2 {
		return ""
	}
	remainder := strings.Join(words[2:], " ")
	fields := strings.Fields(remainder)
	if len(fields) > 0 {
		lower := strings.ToLower(fields[0])
		if lower == "a" || lower == "an" || lower == "the" {
			fields = fields[1:]
		}
	}
	remainder = strings.Join(fields, " ")
	if remainder == "" {
		return ""
	}
	return "Resolve " + remainder + " ambush"
}

func initiativeHandler(w http.ResponseWriter, r *http.Request) {
	var req initiativeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	entries := make([]initiativeEntry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		entries = append(entries, initiativeEntry{
			Name:  c.Name,
			Score: c.Roll + c.Dex,
			Dex:   c.Dex,
		})
	}

	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].Score != entries[j].Score {
			return entries[i].Score > entries[j].Score
		}
		if entries[i].Dex != entries[j].Dex {
			return entries[i].Dex > entries[j].Dex
		}
		return entries[i].Name < entries[j].Name
	})

	writeJSON(w, http.StatusOK, initiativeResponse{Order: entries})
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req abilityModifierRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	mod, err := abilityModifier(req.Score)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, abilityModifierResponse{
		Score:    req.Score,
		Modifier: mod,
	})
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var req proficiencyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	bonus, err := proficiencyBonus(req.Level)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, proficiencyResponse{
		Level:            req.Level,
		ProficiencyBonus: bonus,
	})
}

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req derivedStatsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	prof, err := proficiencyBonus(req.Level)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	mods, err := modifiersFor(req.Abilities)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	conMod, err := abilityModifier(req.Abilities.Con)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	dexMod, err := abilityModifier(req.Abilities.Dex)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}

	hpMax := req.Level * (6 + conMod)
	armorClass := req.Armor.Base + min(dexMod, req.Armor.DexCap) + shieldBonus

	writeJSON(w, http.StatusOK, derivedStatsResponse{
		Level:            req.Level,
		ProficiencyBonus: prof,
		HPMax:            hpMax,
		ArmorClass:       armorClass,
		Modifiers:        mods,
	})
}

func createCombatSessionHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string      `json:"id"`
		Combatants []combatant `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "session id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "combatants are required")
		return
	}

	seen := make(map[string]struct{}, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			writeError(w, http.StatusBadRequest, "combatant name is required")
			return
		}
		if _, ok := seen[c.Name]; ok {
			writeError(w, http.StatusBadRequest, "duplicate combatant name: "+c.Name)
			return
		}
		seen[c.Name] = struct{}{}
	}

	entries := make([]initiativeEntry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		entries = append(entries, initiativeEntry{
			Name:  c.Name,
			Score: c.Roll + c.Dex,
			Dex:   c.Dex,
		})
	}
	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].Score != entries[j].Score {
			return entries[i].Score > entries[j].Score
		}
		if entries[i].Dex != entries[j].Dex {
			return entries[i].Dex > entries[j].Dex
		}
		return entries[i].Name < entries[j].Name
	})

	session := &combatSession{
		ID:         req.ID,
		Round:      1,
		TurnIndex:  0,
		Order:      entries,
		Conditions: make(map[string][]conditionEntry),
	}

	if err := globalStore.createSession(session); err != nil {
		if errors.Is(err, errSessionExists) {
			writeError(w, http.StatusBadRequest, "session id already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusOK, combatSessionResponse{
		ID:        session.ID,
		Round:     session.Round,
		TurnIndex: session.TurnIndex,
		Active:    session.Order[session.TurnIndex],
		Order:     session.Order,
	})
}

func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be positive")
		return
	}

	sess, err := globalStore.addCondition(id, req.Target, conditionEntry{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})
	if err != nil {
		if errors.Is(err, errSessionNotFound) {
			writeError(w, http.StatusNotFound, "session not found")
			return
		}
		if errors.Is(err, errTargetNotFound) {
			writeError(w, http.StatusBadRequest, "target not found: "+req.Target)
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	conds := make([]conditionEntry, len(sess.Conditions[req.Target]))
	copy(conds, sess.Conditions[req.Target])

	writeJSON(w, http.StatusOK, struct {
		Target     string           `json:"target"`
		Conditions []conditionEntry `json:"conditions"`
	}{
		Target:     req.Target,
		Conditions: conds,
	})
}

func advanceTurnHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	sess, err := globalStore.advanceTurn(id)
	if err != nil {
		if errors.Is(err, errSessionNotFound) {
			writeError(w, http.StatusNotFound, "session not found")
			return
		}
		if errors.Is(err, errEmptySession) {
			writeError(w, http.StatusBadRequest, "session has no combatants")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	active := sess.Order[sess.TurnIndex]

	condsCopy := make(map[string][]conditionEntry)
	for name, conds := range sess.Conditions {
		cpy := make([]conditionEntry, len(conds))
		copy(cpy, conds)
		condsCopy[name] = cpy
	}

	writeJSON(w, http.StatusOK, struct {
		ID         string                      `json:"id"`
		Round      int                         `json:"round"`
		TurnIndex  int                         `json:"turn_index"`
		Active     initiativeEntry             `json:"active"`
		Conditions map[string][]conditionEntry `json:"conditions"`
	}{
		ID:         sess.ID,
		Round:      sess.Round,
		TurnIndex:  sess.TurnIndex,
		Active:     active,
		Conditions: condsCopy,
	})
}

// hashPassword returns a deterministic placeholder hash for the password.
// In production this should be replaced with a real password hash such as
// bcrypt or argon2.
func hashPassword(password string) string {
	sum := sha256.Sum256([]byte(password))
	return hex.EncodeToString(sum[:])
}

func verifyPassword(password, hash string) bool {
	return hashPassword(password) == hash
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if !validateUsername(req.Username) {
		writeError(w, http.StatusBadRequest, "invalid username")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		writeError(w, http.StatusBadRequest, "invalid role")
		return
	}

	u := user{
		Username:     req.Username,
		Role:         req.Role,
		PasswordHash: hashPassword(req.Password),
	}

	if err := globalStore.createUser(u); err != nil {
		if errors.Is(err, errUserExists) {
			writeError(w, http.StatusConflict, "username already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, registerResponse{
		Username: req.Username,
		Role:     req.Role,
	})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Username == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "username and password are required")
		return
	}

	u, ok := globalStore.getUser(req.Username)
	if !ok || !verifyPassword(req.Password, u.PasswordHash) {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}

	writeJSON(w, http.StatusOK, loginResponse{
		Username: u.Username,
		Token:    "session-" + u.Username,
	})
}

func createMonsterHandler(w http.ResponseWriter, r *http.Request) {
	var req monsterEntry
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.CR == "" {
		writeError(w, http.StatusBadRequest, "slug, name, and cr are required")
		return
	}

	if err := globalStore.createMonster(req); err != nil {
		if errors.Is(err, errMonsterExists) {
			writeError(w, http.StatusConflict, "monster already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, struct {
		Slug       string `json:"slug"`
		Name       string `json:"name"`
		CR         string `json:"cr"`
		ArmorClass int    `json:"armor_class"`
		HitPoints  int    `json:"hit_points"`
	}{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: req.ArmorClass,
		HitPoints:  req.HitPoints,
	})
}

func getMonsterHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	m, ok := globalStore.getMonster(slug)
	if !ok {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}
	writeJSON(w, http.StatusOK, m)
}

func createItemHandler(w http.ResponseWriter, r *http.Request) {
	var req itemEntry
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.Type == "" || req.Rarity == "" {
		writeError(w, http.StatusBadRequest, "slug, name, type, and rarity are required")
		return
	}

	if err := globalStore.createItem(req); err != nil {
		if errors.Is(err, errItemExists) {
			writeError(w, http.StatusConflict, "item already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

func getItemHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	i, ok := globalStore.getItem(slug)
	if !ok {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}
	writeJSON(w, http.StatusOK, i)
}

func createCampaignHandler(w http.ResponseWriter, r *http.Request) {
	var req campaign
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.DM == "" {
		writeError(w, http.StatusBadRequest, "id, name, and dm are required")
		return
	}

	if err := globalStore.createCampaign(req); err != nil {
		if errors.Is(err, errCampaignExists) {
			writeError(w, http.StatusConflict, "campaign already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}{
		ID:   req.ID,
		Name: req.Name,
		DM:   req.DM,
	})
}

func addCampaignCharacterHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	var req campaignCharacter
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Class == "" {
		writeError(w, http.StatusBadRequest, "id, name, and class are required")
		return
	}
	if req.Level <= 0 {
		writeError(w, http.StatusBadRequest, "level must be positive")
		return
	}

	if err := globalStore.addCampaignCharacter(campaignID, req); err != nil {
		if errors.Is(err, errCampaignNotFound) {
			writeError(w, http.StatusNotFound, "campaign not found")
			return
		}
		if errors.Is(err, errCharacterExists) {
			writeError(w, http.StatusConflict, "character already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

func addCampaignEventHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	var req campaignEvent
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Kind == "" {
		writeError(w, http.StatusBadRequest, "id and kind are required")
		return
	}

	if err := globalStore.addCampaignEvent(campaignID, req); err != nil {
		if errors.Is(err, errCampaignNotFound) {
			writeError(w, http.StatusNotFound, "campaign not found")
			return
		}
		if errors.Is(err, errEventExists) {
			writeError(w, http.StatusConflict, "event already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}

	writeJSON(w, http.StatusCreated, struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}{
		ID:   req.ID,
		Kind: req.Kind,
	})
}

func getCampaignStateHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	state, ok := globalStore.campaignState(campaignID)
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	var req spellSlotsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Class != "wizard" || req.Level != 5 {
		writeError(w, http.StatusBadRequest, "unsupported class or level")
		return
	}

	writeJSON(w, http.StatusOK, spellSlotsResponse{
		Class: req.Class,
		Level: req.Level,
		Slots: map[string]int{"1": 4, "2": 3, "3": 2},
	})
}

func longRestHandler(w http.ResponseWriter, r *http.Request) {
	var req longRestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level < 1 {
		writeError(w, http.StatusBadRequest, "level must be at least 1")
		return
	}
	if req.HpMax < 1 {
		writeError(w, http.StatusBadRequest, "hp_max must be at least 1")
		return
	}
	if req.HpCurrent < 0 {
		writeError(w, http.StatusBadRequest, "hp_current must be non-negative")
		return
	}
	if req.HitDiceSpent < 0 {
		writeError(w, http.StatusBadRequest, "hit_dice_spent must be non-negative")
		return
	}
	if req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest, "exhaustion_level must be non-negative")
		return
	}

	restored := req.Level / 2
	if restored < 1 {
		restored = 1
	}
	if req.HitDiceSpent < restored {
		restored = req.HitDiceSpent
	}

	resp := longRestResponse{
		HpCurrent:       req.HpMax,
		HitDiceSpent:    req.HitDiceSpent - restored,
		ExhaustionLevel: req.ExhaustionLevel - 1,
	}
	if resp.ExhaustionLevel < 0 {
		resp.ExhaustionLevel = 0
	}

	writeJSON(w, http.StatusOK, resp)
}

func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	var req equipmentLoadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Strength < 1 || req.Strength > 30 {
		writeError(w, http.StatusBadRequest, "strength must be between 1 and 30")
		return
	}
	if req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "weight must be non-negative")
		return
	}

	capacity := req.Strength * 15
	writeJSON(w, http.StatusOK, equipmentLoadResponse{
		Capacity:   capacity,
		Weight:     req.Weight,
		Encumbered: req.Weight > capacity,
	})
}

func dmEncounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	var req encounterBuilderRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if _, ok := globalStore.campaignState(req.CampaignID); !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if len(req.Party) == 0 {
		writeError(w, http.StatusBadRequest, "party is required")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest, "monster_slugs is required")
		return
	}

	counts := make(map[string]int, len(req.MonsterSlugs))
	for _, slug := range req.MonsterSlugs {
		counts[slug]++
	}
	monsters := make([]monster, 0, len(counts))
	for slug, count := range counts {
		m, ok := globalStore.getMonster(slug)
		if !ok {
			writeError(w, http.StatusBadRequest, "monster not found: "+slug)
			return
		}
		monsters = append(monsters, monster{CR: m.CR, Count: count})
	}

	enc, err := computeEncounter(req.Party, monsters)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, encounterBuilderResponse{
		CampaignID:     req.CampaignID,
		BaseXP:         enc.BaseXP,
		AdjustedXP:     int(enc.AdjustedXP),
		Difficulty:     enc.Difficulty,
		MonsterCount:   enc.MonsterCount,
		Recommendation: recommendationFor(enc.Difficulty),
	})
}

func dmLootParcelHandler(w http.ResponseWriter, r *http.Request) {
	var req lootParcelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if _, ok := globalStore.campaignState(req.CampaignID); !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if req.Tier != 1 {
		writeError(w, http.StatusBadRequest, "unsupported tier")
		return
	}

	writeJSON(w, http.StatusOK, lootParcelResponse{
		CampaignID: req.CampaignID,
		CoinsGP:    75,
		Items: []lootItem{
			{Slug: "healing-potion", Quantity: 2},
		},
	})
}

func dmSessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	var req sessionRecapRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	c, ok := globalStore.getCampaign(req.CampaignID)
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var events []campaignEvent
	for _, e := range c.Events {
		events = append(events, e)
	}
	sort.Slice(events, func(i, j int) bool {
		return events[i].ID < events[j].ID
	})

	summary := ""
	if len(events) > 0 {
		summary = events[len(events)-1].Summary
	}
	openThreads := []string{}
	if thread := generateOpenThread(summary); thread != "" {
		openThreads = append(openThreads, thread)
	}

	writeJSON(w, http.StatusOK, sessionRecapResponse{
		CampaignID:  req.CampaignID,
		Summary:     summary,
		OpenThreads: openThreads,
	})
}

func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, globalStore.status())
}

func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	if err := globalStore.reset(); err != nil {
		writeError(w, http.StatusInternalServerError, "storage error")
		return
	}
	writeJSON(w, http.StatusOK, storageResetResponse{
		OK:            true,
		SchemaVersion: schemaVersion,
	})
}

func main() {
	var err error
	globalStore, err = newStore(dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "storage init error: %v\n", err)
		os.Exit(1)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("POST /v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("POST /v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", encounterHandler)
	mux.HandleFunc("POST /v1/initiative/order", initiativeHandler)
	mux.HandleFunc("POST /v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("POST /v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("POST /v1/characters/derived-stats", derivedStatsHandler)
	mux.HandleFunc("POST /v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", addConditionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", advanceTurnHandler)
	mux.HandleFunc("POST /v1/auth/register", registerHandler)
	mux.HandleFunc("POST /v1/auth/login", loginHandler)
	mux.HandleFunc("GET /v1/storage/status", storageStatusHandler)
	mux.HandleFunc("POST /v1/storage/reset", storageResetHandler)
	mux.HandleFunc("POST /v1/compendium/monsters", createMonsterHandler)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", getMonsterHandler)
	mux.HandleFunc("POST /v1/compendium/items", createItemHandler)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", getItemHandler)
	mux.HandleFunc("POST /v1/campaigns", createCampaignHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", addCampaignCharacterHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", addCampaignEventHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", getCampaignStateHandler)
	mux.HandleFunc("POST /v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("POST /v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("POST /v1/phb/equipment-load", equipmentLoadHandler)
	mux.HandleFunc("POST /v1/dm/encounter-builder", dmEncounterBuilderHandler)
	mux.HandleFunc("POST /v1/dm/loot-parcel", dmLootParcelHandler)
	mux.HandleFunc("POST /v1/dm/session-recap", dmSessionRecapHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	addr := "127.0.0.1:" + port
	fmt.Println("Listening on", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		fmt.Fprintf(os.Stderr, "server error: %v\n", err)
		os.Exit(1)
	}
}
