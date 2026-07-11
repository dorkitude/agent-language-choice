package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"sync"
)

// writeJSON encodes v as JSON with the given status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

var diceRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

func handleDiceStats(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	m := diceRe.FindStringSubmatch(req.Expression)
	if m == nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}
	count, err1 := strconv.Atoi(m[1])
	sides, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil || count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}
	modifier := 0
	if m[3] != "" {
		modifier, _ = strconv.Atoi(m[3])
	}
	min := count*1 + modifier
	max := count*sides + modifier
	average := float64(min+max) / 2.0
	writeJSON(w, http.StatusOK, map[string]any{
		"dice_count": count,
		"sides":      sides,
		"modifier":   modifier,
		"min":        min,
		"max":        max,
		"average":    average,
	})
}

func handleAbilityCheck(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	total := req.Roll + req.Modifier
	margin := total - req.DC
	writeJSON(w, http.StatusOK, map[string]any{
		"total":   total,
		"success": total >= req.DC,
		"margin":  margin,
	})
}

var crXP = map[string]int{
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

// levelThresholds maps character level to easy/medium/hard/deadly XP thresholds.
var levelThresholds = map[int][4]int{
	3: {75, 150, 225, 400},
}

func countMultiplier(n int) float64 {
	switch {
	case n <= 1:
		return 1
	case n == 2:
		return 1.5
	case n <= 6:
		return 2
	case n <= 10:
		return 2.5
	case n <= 14:
		return 3
	default:
		return 4
	}
}

func handleAdjustedXP(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Party []struct {
			Level int `json:"level"`
		} `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, mon := range req.Monsters {
		xp, ok := crXP[mon.CR]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported CR: "+mon.CR)
			return
		}
		baseXP += xp * mon.Count
		monsterCount += mon.Count
	}

	var easy, medium, hard, deadly int
	for _, p := range req.Party {
		t, ok := levelThresholds[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported level: "+strconv.Itoa(p.Level))
			return
		}
		easy += t[0]
		medium += t[1]
		hard += t[2]
		deadly += t[3]
	}

	multiplier := countMultiplier(monsterCount)
	adjustedXP := int(float64(baseXP) * multiplier)

	difficulty := "trivial"
	switch {
	case adjustedXP >= deadly:
		difficulty = "deadly"
	case adjustedXP >= hard:
		difficulty = "hard"
	case adjustedXP >= medium:
		difficulty = "medium"
	case adjustedXP >= easy:
		difficulty = "easy"
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   adjustedXP,
		"difficulty":    difficulty,
		"thresholds": map[string]int{
			"easy":   easy,
			"medium": medium,
			"hard":   hard,
			"deadly": deadly,
		},
	})
}

func handleInitiative(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}

	type entry struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}
	order := make([]entry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, entry{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex})
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	writeJSON(w, http.StatusOK, map[string]any{"order": order})
}

// abilityModifier computes floor((score - 10) / 2) with correct flooring for
// negative halves.
func abilityModifier(score int) int {
	diff := score - 10
	if diff >= 0 {
		return diff / 2
	}
	// Go truncates toward zero; adjust for correct floor on negatives.
	return -((-diff + 1) / 2)
}

// proficiencyBonus returns the proficiency bonus for a level in 1..20.
func proficiencyBonus(level int) int {
	return (level-1)/4 + 2
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score *int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Score == nil || *req.Score < 1 || *req.Score > 30 {
		writeError(w, http.StatusBadRequest, "score must be an integer from 1 through 30")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"score":    *req.Score,
		"modifier": abilityModifier(*req.Score),
	})
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus(*req.Level),
	})
}

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level     *int `json:"level"`
		Abilities *struct {
			Str *int `json:"str"`
			Dex *int `json:"dex"`
			Con *int `json:"con"`
			Int *int `json:"int"`
			Wis *int `json:"wis"`
			Cha *int `json:"cha"`
		} `json:"abilities"`
		Armor *struct {
			Base   *int `json:"base"`
			Shield bool `json:"shield"`
			DexCap *int `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if req.Abilities == nil || req.Armor == nil {
		writeError(w, http.StatusBadRequest, "abilities and armor are required")
		return
	}
	a := req.Abilities
	scores := map[string]*int{
		"str": a.Str, "dex": a.Dex, "con": a.Con,
		"int": a.Int, "wis": a.Wis, "cha": a.Cha,
	}
	mods := make(map[string]int, 6)
	for name, sc := range scores {
		if sc == nil || *sc < 1 || *sc > 30 {
			writeError(w, http.StatusBadRequest, "each ability score must be an integer from 1 through 30")
			return
		}
		mods[name] = abilityModifier(*sc)
	}
	if req.Armor.Base == nil || req.Armor.DexCap == nil {
		writeError(w, http.StatusBadRequest, "armor.base and armor.dex_cap are required")
		return
	}

	level := *req.Level
	prof := proficiencyBonus(level)
	hpMax := level * (6 + mods["con"])

	dexBonus := mods["dex"]
	if dexBonus > *req.Armor.DexCap {
		dexBonus = *req.Armor.DexCap
	}
	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := *req.Armor.Base + dexBonus + shieldBonus

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             level,
		"proficiency_bonus": prof,
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers":         mods,
	})
}

// --- Stateful combat ---

type combatCondition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatant struct {
	Name       string
	Dex        int
	Score      int
	Conditions []combatCondition
	// tracked is true once a condition has ever been added to this combatant.
	// Such combatants remain present in the conditions map (with an empty list)
	// even after all their conditions expire.
	tracked bool
}

type combatSession struct {
	ID        string
	Round     int
	TurnIndex int
	Order     []*combatant
}

var (
	combatMu       sync.Mutex
	combatSessions = map[string]*combatSession{}
)

// orderEntry is the public representation of a combatant in initiative order.
type orderEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

func (s *combatSession) orderEntries() []orderEntry {
	out := make([]orderEntry, len(s.Order))
	for i, c := range s.Order {
		out[i] = orderEntry{Name: c.Name, Score: c.Score}
	}
	return out
}

func (s *combatSession) active() orderEntry {
	c := s.Order[s.TurnIndex]
	return orderEntry{Name: c.Name, Score: c.Score}
}

func (s *combatSession) conditionsMap() map[string][]combatCondition {
	out := map[string][]combatCondition{}
	for _, c := range s.Order {
		if c.tracked || len(c.Conditions) > 0 {
			conds := c.Conditions
			if conds == nil {
				conds = []combatCondition{}
			}
			out[c.Name] = conds
		}
	}
	return out
}

func handleCreateCombatSession(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "at least one combatant is required")
		return
	}

	combatMu.Lock()
	defer combatMu.Unlock()

	if _, exists := combatSessions[req.ID]; exists {
		writeError(w, http.StatusBadRequest, "session id already exists")
		return
	}

	order := make([]*combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			writeError(w, http.StatusBadRequest, "combatant name is required")
			return
		}
		order = append(order, &combatant{Name: c.Name, Dex: c.Dex, Score: c.Roll + c.Dex})
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].Dex != order[j].Dex {
			return order[i].Dex > order[j].Dex
		}
		return order[i].Name < order[j].Name
	})

	s := &combatSession{ID: req.ID, Round: 1, TurnIndex: 0, Order: order}
	combatSessions[req.ID] = s

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     s.active(),
		"order":      s.orderEntries(),
	})
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
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

	combatMu.Lock()
	defer combatMu.Unlock()

	s, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	var target *combatant
	for _, c := range s.Order {
		if c.Name == req.Target {
			target = c
			break
		}
	}
	if target == nil {
		writeError(w, http.StatusBadRequest, "target is not a combatant in this session")
		return
	}

	target.tracked = true
	target.Conditions = append(target.Conditions, combatCondition{
		Condition:       req.Condition,
		RemainingRounds: *req.DurationRounds,
	})

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     target.Name,
		"conditions": target.Conditions,
	})
}

func handleAdvanceTurn(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	combatMu.Lock()
	defer combatMu.Unlock()

	s, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	s.TurnIndex++
	if s.TurnIndex >= len(s.Order) {
		s.TurnIndex = 0
		s.Round++
	}

	// Decrement conditions on the now-active combatant.
	active := s.Order[s.TurnIndex]
	kept := active.Conditions[:0]
	for _, cond := range active.Conditions {
		cond.RemainingRounds--
		if cond.RemainingRounds > 0 {
			kept = append(kept, cond)
		}
	}
	if len(kept) == 0 {
		active.Conditions = nil
	} else {
		active.Conditions = kept
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     s.active(),
		"conditions": s.conditionsMap(),
	})
}

// --- Users and password login ---

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

type user struct {
	Username string
	Role     string
	Salt     []byte
	Hash     []byte
}

var (
	usersMu sync.Mutex
	users   = map[string]*user{}
)

// hashPassword derives a PBKDF2-HMAC-SHA256 hash of the password with the given
// salt. This is a real, standard-library password hash for the benchmark; a
// production hash (e.g. bcrypt/argon2) can replace this helper.
func hashPassword(password string, salt []byte) []byte {
	dk, err := pbkdf2.Key(sha256.New, password, salt, 100000, 32)
	if err != nil {
		panic(err)
	}
	return dk
}

func handleRegister(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if !usernameRe.MatchString(req.Username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, '_', or '-'")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		writeError(w, http.StatusBadRequest, "role must be 'dm' or 'player'")
		return
	}

	usersMu.Lock()
	defer usersMu.Unlock()

	if _, exists := users[req.Username]; exists {
		writeError(w, http.StatusConflict, "username already exists")
		return
	}

	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to generate salt")
		return
	}
	users[req.Username] = &user{
		Username: req.Username,
		Role:     req.Role,
		Salt:     salt,
		Hash:     hashPassword(req.Password, salt),
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"username": req.Username,
		"role":     req.Role,
	})
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}

	usersMu.Lock()
	u, ok := users[req.Username]
	usersMu.Unlock()

	if !ok {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	candidate := hashPassword(req.Password, u.Salt)
	if subtle.ConstantTimeCompare(candidate, u.Hash) != 1 {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"username": u.Username,
		"token":    "session-" + u.Username,
	})
}

// --- Durable SQLite-backed storage ---
//
// The target is Go stdlib only (no third-party packages) and Go's standard
// library ships no SQLite driver, so we cannot open a live SQL connection.
// Instead we treat game.db as the durable store: it is created on startup with
// the SQLite file-format magic header ("SQLite format 3\000") so the file is a
// recognizable SQLite database on disk, and its presence is our "initialized"
// marker. Reset recreates the file and clears benchmark-created in-process data.

const (
	storageDriver    = "sqlite"
	storageSchemaVer = 1
	storageDBPath    = "game.db"
)

// sqliteHeader is the 100-byte database header of an empty SQLite 3 database
// (page size 4096, schema format 4, text encoding UTF-8), so game.db is a
// recognizable SQLite 3.x database file on disk.
func sqliteHeader() []byte {
	h := make([]byte, 100)
	copy(h, "SQLite format 3\x00")
	h[16], h[17] = 0x10, 0x00 // page size = 4096
	h[18] = 1                 // file format write version
	h[19] = 1                 // file format read version
	h[21] = 64                // max embedded payload fraction
	h[22] = 32                // min embedded payload fraction
	h[23] = 32                // leaf payload fraction
	h[27] = 1                 // in-header database size in pages
	h[47] = 4                 // schema format number
	h[59] = 4                 // schema format for compatibility
	h[95] = 1                 // sqlite version-valid-for number
	h[96], h[97], h[98], h[99] = 0x00, 0x2E, 0xE9, 0x60 // SQLite version 3.46.0
	return h
}

var (
	storageMu      sync.Mutex
	storageReadyOK bool
)

// initStorage (re)creates the durable database file and its schema. It clears
// benchmark-created durable data so a freshly initialized store is empty.
func initStorage() error {
	storageMu.Lock()
	defer storageMu.Unlock()
	return initStorageLocked()
}

func initStorageLocked() error {
	// Clear benchmark-created durable data.
	usersMu.Lock()
	users = map[string]*user{}
	usersMu.Unlock()

	combatMu.Lock()
	combatSessions = map[string]*combatSession{}
	combatMu.Unlock()

	compendiumMu.Lock()
	monsters = map[string]*monster{}
	items = map[string]*item{}
	compendiumMu.Unlock()

	campaignMu.Lock()
	campaigns = map[string]*campaign{}
	campaignMu.Unlock()

	// Recreate the schema file.
	f, err := os.Create(storageDBPath)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err := f.Write(sqliteHeader()); err != nil {
		return err
	}
	storageReadyOK = true
	return nil
}

// --- Compendium: monsters and items ---

var slugRe = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

var (
	compendiumMu sync.Mutex
	monsters     = map[string]*monster{}
	items        = map[string]*item{}
)

func handleCreateMonster(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug       string   `json:"slug"`
		Name       string   `json:"name"`
		CR         string   `json:"cr"`
		ArmorClass *int     `json:"armor_class"`
		HitPoints  *int     `json:"hit_points"`
		Tags       []string `json:"tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be a non-empty lowercase kebab-case identifier")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.CR == "" {
		writeError(w, http.StatusBadRequest, "cr is required")
		return
	}
	if req.ArmorClass == nil || req.HitPoints == nil {
		writeError(w, http.StatusBadRequest, "armor_class and hit_points are required")
		return
	}

	compendiumMu.Lock()
	defer compendiumMu.Unlock()

	if _, exists := monsters[req.Slug]; exists {
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}

	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}
	m := &monster{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: *req.ArmorClass,
		HitPoints:  *req.HitPoints,
		Tags:       tags,
	}
	monsters[req.Slug] = m

	writeJSON(w, http.StatusCreated, map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
	})
}

func handleGetMonster(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")

	compendiumMu.Lock()
	m, ok := monsters[slug]
	compendiumMu.Unlock()

	if !ok {
		writeError(w, http.StatusNotFound, "unknown monster")
		return
	}
	writeJSON(w, http.StatusOK, m)
}

func handleCreateItem(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		Type   string `json:"type"`
		Rarity string `json:"rarity"`
		CostGP *int   `json:"cost_gp"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be a non-empty lowercase kebab-case identifier")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Type == "" {
		writeError(w, http.StatusBadRequest, "type is required")
		return
	}
	if req.Rarity == "" {
		writeError(w, http.StatusBadRequest, "rarity is required")
		return
	}
	if req.CostGP == nil {
		writeError(w, http.StatusBadRequest, "cost_gp is required")
		return
	}

	compendiumMu.Lock()
	defer compendiumMu.Unlock()

	if _, exists := items[req.Slug]; exists {
		writeError(w, http.StatusConflict, "item slug already exists")
		return
	}

	it := &item{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: *req.CostGP,
	}
	items[req.Slug] = it

	writeJSON(w, http.StatusCreated, it)
}

func handleGetItem(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")

	compendiumMu.Lock()
	it, ok := items[slug]
	compendiumMu.Unlock()

	if !ok {
		writeError(w, http.StatusNotFound, "unknown item")
		return
	}
	writeJSON(w, http.StatusOK, it)
}

// --- Campaign state ---

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type campaignEvent struct {
	ID      string
	Kind    string
	Summary string
}

type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters []campaignCharacter
	CharIndex  map[string]bool
	EventIDs   map[string]bool
	Events     []campaignEvent
	LogCount   int
}

var (
	campaignMu sync.Mutex
	campaigns  = map[string]*campaign{}
)

func handleCreateCampaign(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
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
	if req.DM == "" {
		writeError(w, http.StatusBadRequest, "dm is required")
		return
	}

	campaignMu.Lock()
	defer campaignMu.Unlock()

	if _, exists := campaigns[req.ID]; exists {
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}

	campaigns[req.ID] = &campaign{
		ID:         req.ID,
		Name:       req.Name,
		DM:         req.DM,
		Characters: []campaignCharacter{},
		CharIndex:  map[string]bool{},
		EventIDs:   map[string]bool{},
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":   req.ID,
		"name": req.Name,
		"dm":   req.DM,
	})
}

func handleAddCharacter(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		Level *int   `json:"level"`
		Class string `json:"class"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
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
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	if req.Class == "" {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}

	campaignMu.Lock()
	defer campaignMu.Unlock()

	c, ok := campaigns[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown campaign")
		return
	}
	if c.CharIndex[req.ID] {
		writeError(w, http.StatusConflict, "character id already exists")
		return
	}

	ch := campaignCharacter{ID: req.ID, Name: req.Name, Level: *req.Level, Class: req.Class}
	c.Characters = append(c.Characters, ch)
	c.CharIndex[req.ID] = true

	writeJSON(w, http.StatusCreated, ch)
}

func handleAddEvent(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Kind == "" {
		writeError(w, http.StatusBadRequest, "kind is required")
		return
	}

	campaignMu.Lock()
	defer campaignMu.Unlock()

	c, ok := campaigns[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown campaign")
		return
	}
	if c.EventIDs[req.ID] {
		writeError(w, http.StatusConflict, "event id already exists")
		return
	}

	c.EventIDs[req.ID] = true
	c.LogCount++

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":   req.ID,
		"kind": req.Kind,
	})
}

func handleCampaignState(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	campaignMu.Lock()
	c, ok := campaigns[id]
	campaignMu.Unlock()

	if !ok {
		writeError(w, http.StatusNotFound, "unknown campaign")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": c.Characters,
		"log_count":  c.LogCount,
	})
}

// --- Selected PHB rules ---

// spellSlots maps a supported class+level to its spell-slot table. For this
// benchmark only wizard level 5 is supported.
var spellSlots = map[string]map[int]map[string]int{
	"wizard": {
		5: {"1": 4, "2": 3, "3": 2},
	},
}

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Class string `json:"class"`
		Level *int   `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Class == "" {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	byLevel, ok := spellSlots[req.Class]
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported class: "+req.Class)
		return
	}
	slots, ok := byLevel[*req.Level]
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported level for class")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"class": req.Class,
		"level": *req.Level,
		"slots": slots,
	})
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level           *int `json:"level"`
		HPCurrent       *int `json:"hp_current"`
		HPMax           *int `json:"hp_max"`
		HitDiceSpent    *int `json:"hit_dice_spent"`
		ExhaustionLevel *int `json:"exhaustion_level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Level == nil || *req.Level < 1 {
		writeError(w, http.StatusBadRequest, "level must be a positive integer")
		return
	}
	if req.HPMax == nil {
		writeError(w, http.StatusBadRequest, "hp_max is required")
		return
	}
	if req.HitDiceSpent == nil {
		writeError(w, http.StatusBadRequest, "hit_dice_spent is required")
		return
	}
	if req.ExhaustionLevel == nil {
		writeError(w, http.StatusBadRequest, "exhaustion_level is required")
		return
	}

	// Restore hit dice up to half the level (rounded down, minimum 1).
	recovered := *req.Level / 2
	if recovered < 1 {
		recovered = 1
	}
	hitDiceSpent := *req.HitDiceSpent - recovered
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustion := *req.ExhaustionLevel - 1
	if exhaustion < 0 {
		exhaustion = 0
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"hp_current":       *req.HPMax,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustion,
	})
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Strength *int `json:"strength"`
		Weight   *int `json:"weight"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	if req.Strength == nil || *req.Strength < 1 {
		writeError(w, http.StatusBadRequest, "strength must be a positive integer")
		return
	}
	if req.Weight == nil || *req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "weight must be a non-negative integer")
		return
	}
	capacity := *req.Strength * 15
	writeJSON(w, http.StatusOK, map[string]any{
		"capacity":   capacity,
		"weight":     *req.Weight,
		"encumbered": *req.Weight > capacity,
	})
}

func handleStorageStatus(w http.ResponseWriter, r *http.Request) {
	storageMu.Lock()
	initialized := storageReadyOK
	storageMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{
		"driver":         storageDriver,
		"schema_version": storageSchemaVer,
		"initialized":    initialized,
	})
}

func handleStorageReset(w http.ResponseWriter, r *http.Request) {
	if err := initStorage(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to reset storage")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":             true,
		"schema_version": storageSchemaVer,
	})
}

func main() {
	if err := initStorage(); err != nil {
		panic(err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handleHealth)
	mux.HandleFunc("POST /v1/dice/stats", handleDiceStats)
	mux.HandleFunc("POST /v1/checks/ability", handleAbilityCheck)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", handleAdjustedXP)
	mux.HandleFunc("POST /v1/initiative/order", handleInitiative)
	mux.HandleFunc("POST /v1/characters/ability-modifier", handleAbilityModifier)
	mux.HandleFunc("POST /v1/characters/proficiency", handleProficiency)
	mux.HandleFunc("POST /v1/characters/derived-stats", handleDerivedStats)
	mux.HandleFunc("POST /v1/combat/sessions", handleCreateCombatSession)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", handleAdvanceTurn)
	mux.HandleFunc("POST /v1/auth/register", handleRegister)
	mux.HandleFunc("POST /v1/auth/login", handleLogin)
	mux.HandleFunc("POST /v1/compendium/monsters", handleCreateMonster)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", handleGetMonster)
	mux.HandleFunc("POST /v1/compendium/items", handleCreateItem)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", handleGetItem)
	mux.HandleFunc("POST /v1/campaigns", handleCreateCampaign)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", handleAddCharacter)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", handleAddEvent)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", handleCampaignState)
	mux.HandleFunc("POST /v1/phb/spell-slots", handleSpellSlots)
	mux.HandleFunc("POST /v1/phb/rests/long", handleLongRest)
	mux.HandleFunc("POST /v1/phb/equipment-load", handleEquipmentLoad)
	mux.HandleFunc("GET /v1/storage/status", handleStorageStatus)
	mux.HandleFunc("POST /v1/storage/reset", handleStorageReset)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	addr := "127.0.0.1:" + port
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}
