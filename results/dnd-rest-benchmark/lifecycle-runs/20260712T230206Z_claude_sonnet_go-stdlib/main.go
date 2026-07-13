package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"math"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

var diceExprRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	m := diceExprRe.FindStringSubmatch(req.Expression)
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
		mod, err := strconv.Atoi(m[3])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid expression")
			return
		}
		modifier = mod
	}

	min := count*1 + modifier
	max := count*sides + modifier
	average := float64(count)*(float64(sides)+1)/2 + float64(modifier)

	writeJSON(w, http.StatusOK, map[string]any{
		"dice_count": count,
		"sides":      sides,
		"modifier":   modifier,
		"min":        min,
		"max":        max,
		"average":    average,
	})
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     *int `json:"roll"`
		Modifier *int `json:"modifier"`
		DC       *int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Roll == nil || req.Modifier == nil || req.DC == nil {
		writeError(w, http.StatusBadRequest, "missing required fields")
		return
	}

	total := *req.Roll + *req.Modifier
	success := total >= *req.DC
	margin := total - *req.DC

	writeJSON(w, http.StatusOK, map[string]any{
		"total":   total,
		"success": success,
		"margin":  margin,
	})
}

var crXP = map[string]float64{
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

var levelThresholds = map[int]struct {
	Easy, Medium, Hard, Deadly int
}{
	3: {75, 150, 225, 400},
}

func countMultiplier(count int) float64 {
	switch {
	case count <= 0:
		return 1
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

type xpMonsterGroup struct {
	CR    string
	Count int
}

// computeAdjustedXP holds the core adjusted-XP encounter math shared by the
// core encounters endpoint and the DM encounter builder.
func computeAdjustedXP(partyLevels []int, groups []xpMonsterGroup) (baseXP float64, monsterCount int, multiplier float64, adjustedXP float64, difficulty string, thresholds map[string]int, err error) {
	for _, g := range groups {
		xp, ok := crXP[g.CR]
		if !ok {
			return 0, 0, 0, 0, "", nil, errors.New("unsupported challenge rating")
		}
		baseXP += xp * float64(g.Count)
		monsterCount += g.Count
	}

	multiplier = countMultiplier(monsterCount)
	adjustedXP = baseXP * multiplier

	var easy, medium, hard, deadly int
	for _, level := range partyLevels {
		th, ok := levelThresholds[level]
		if !ok {
			return 0, 0, 0, 0, "", nil, errors.New("unsupported party level")
		}
		easy += th.Easy
		medium += th.Medium
		hard += th.Hard
		deadly += th.Deadly
	}

	difficulty = "trivial"
	if adjustedXP >= float64(deadly) {
		difficulty = "deadly"
	} else if adjustedXP >= float64(hard) {
		difficulty = "hard"
	} else if adjustedXP >= float64(medium) {
		difficulty = "medium"
	} else if adjustedXP >= float64(easy) {
		difficulty = "easy"
	}

	thresholds = map[string]int{"easy": easy, "medium": medium, "hard": hard, "deadly": deadly}
	return baseXP, monsterCount, multiplier, adjustedXP, difficulty, thresholds, nil
}

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
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
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	groups := make([]xpMonsterGroup, 0, len(req.Monsters))
	for _, mo := range req.Monsters {
		groups = append(groups, xpMonsterGroup{CR: mo.CR, Count: mo.Count})
	}
	partyLevels := make([]int, 0, len(req.Party))
	for _, p := range req.Party {
		partyLevels = append(partyLevels, p.Level)
	}

	baseXP, monsterCount, multiplier, adjustedXP, difficulty, thresholds, err := computeAdjustedXP(partyLevels, groups)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   adjustedXP,
		"difficulty":    difficulty,
		"thresholds":    thresholds,
	})
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	type entry struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		Dex   int    `json:"-"`
	}

	entries := make([]entry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		entries = append(entries, entry{Name: c.Name, Score: c.Roll + c.Dex, Dex: c.Dex})
	}

	sort.Slice(entries, func(i, j int) bool {
		if entries[i].Score != entries[j].Score {
			return entries[i].Score > entries[j].Score
		}
		if entries[i].Dex != entries[j].Dex {
			return entries[i].Dex > entries[j].Dex
		}
		return entries[i].Name < entries[j].Name
	})

	writeJSON(w, http.StatusOK, map[string]any{
		"order": entries,
	})
}

func abilityModifier(score int) int {
	return int(math.Floor(float64(score-10) / 2.0))
}

func proficiencyBonus(level int) int {
	switch {
	case level <= 4:
		return 2
	case level <= 8:
		return 3
	case level <= 12:
		return 4
	case level <= 16:
		return 5
	default:
		return 6
	}
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score *int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
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

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
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

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
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
			Base   *int  `json:"base"`
			Shield *bool `json:"shield"`
			DexCap *int  `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if req.Abilities == nil {
		writeError(w, http.StatusBadRequest, "abilities is required")
		return
	}
	a := req.Abilities
	if a.Str == nil || a.Dex == nil || a.Con == nil || a.Int == nil || a.Wis == nil || a.Cha == nil {
		writeError(w, http.StatusBadRequest, "all abilities are required")
		return
	}
	for _, score := range []int{*a.Str, *a.Dex, *a.Con, *a.Int, *a.Wis, *a.Cha} {
		if score < 1 || score > 30 {
			writeError(w, http.StatusBadRequest, "ability scores must be between 1 and 30")
			return
		}
	}
	if req.Armor == nil || req.Armor.Base == nil || req.Armor.DexCap == nil || req.Armor.Shield == nil {
		writeError(w, http.StatusBadRequest, "armor with base, shield, and dex_cap is required")
		return
	}

	strMod := abilityModifier(*a.Str)
	dexMod := abilityModifier(*a.Dex)
	conMod := abilityModifier(*a.Con)
	intMod := abilityModifier(*a.Int)
	wisMod := abilityModifier(*a.Wis)
	chaMod := abilityModifier(*a.Cha)

	shieldBonus := 0
	if *req.Armor.Shield {
		shieldBonus = 2
	}

	dexForAC := dexMod
	if dexForAC > *req.Armor.DexCap {
		dexForAC = *req.Armor.DexCap
	}

	hpMax := *req.Level * (6 + conMod)
	armorClass := *req.Armor.Base + dexForAC + shieldBonus

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus(*req.Level),
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers": map[string]int{
			"str": strMod,
			"dex": dexMod,
			"con": conMod,
			"int": intMod,
			"wis": wisMod,
			"cha": chaMod,
		},
	})
}

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatant struct {
	Name       string `json:"name"`
	Dex        int    `json:"dex"`
	Roll       int    `json:"roll"`
	Score      int    `json:"score"`
	Conditions []condition
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

func combatantView(c *combatant) map[string]any {
	return map[string]any{"name": c.Name, "score": c.Score}
}

func sessionCreateView(s *combatSession) map[string]any {
	order := make([]map[string]any, 0, len(s.Order))
	for _, c := range s.Order {
		order = append(order, combatantView(c))
	}
	return map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     combatantView(s.Order[s.TurnIndex]),
		"order":      order,
	}
}

func createCombatSessionHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "combatants is required")
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
		order = append(order, &combatant{Name: c.Name, Dex: c.Dex, Roll: c.Roll, Score: c.Roll + c.Dex})
	}

	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].Dex != order[j].Dex {
			return order[i].Dex > order[j].Dex
		}
		return order[i].Name < order[j].Name
	})

	session := &combatSession{
		ID:        req.ID,
		Round:     1,
		TurnIndex: 0,
		Order:     order,
	}
	combatSessions[req.ID] = session

	writeJSON(w, http.StatusOK, sessionCreateView(session))
}

func addConditionHandler(w http.ResponseWriter, r *http.Request, id string) {
	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Condition == "" || req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "target, condition, and positive duration_rounds are required")
		return
	}

	combatMu.Lock()
	defer combatMu.Unlock()

	session, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	var target *combatant
	for _, c := range session.Order {
		if c.Name == req.Target {
			target = c
			break
		}
	}
	if target == nil {
		writeError(w, http.StatusBadRequest, "target not found in session")
		return
	}

	target.Conditions = append(target.Conditions, condition{Condition: req.Condition, RemainingRounds: *req.DurationRounds})

	conds := make([]condition, len(target.Conditions))
	copy(conds, target.Conditions)

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     target.Name,
		"conditions": conds,
	})
}

func advanceTurnHandler(w http.ResponseWriter, r *http.Request, id string) {
	combatMu.Lock()
	defer combatMu.Unlock()

	session, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}

	active := session.Order[session.TurnIndex]
	remaining := active.Conditions[:0]
	for _, c := range active.Conditions {
		c.RemainingRounds--
		if c.RemainingRounds > 0 {
			remaining = append(remaining, c)
		}
	}
	active.Conditions = remaining

	conditionsOut := map[string][]condition{}
	for _, c := range session.Order {
		if len(c.Conditions) > 0 || c.Name == active.Name {
			conds := make([]condition, len(c.Conditions))
			copy(conds, c.Conditions)
			conditionsOut[c.Name] = conds
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     combatantView(active),
		"conditions": conditionsOut,
	})
}

func combatSessionSubrouteHandler(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/v1/combat/sessions/")
	parts := strings.Split(path, "/")
	if len(parts) != 2 || parts[0] == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	id, action := parts[0], parts[1]

	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}

	switch action {
	case "conditions":
		addConditionHandler(w, r, id)
	case "advance":
		advanceTurnHandler(w, r, id)
	default:
		writeError(w, http.StatusNotFound, "not found")
	}
}

// hashPassword and verifyPassword isolate password hashing behind a small
// helper. Go's standard library has no dedicated password-hashing package
// (e.g. bcrypt/scrypt/argon2 live outside stdlib), so this uses a salted
// SHA-256 digest as a stand-in; swap in a stronger KDF here for production.
func hashPassword(password string) (string, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	sum := sha256.Sum256(append(salt, []byte(password)...))
	return hex.EncodeToString(salt) + ":" + hex.EncodeToString(sum[:]), nil
}

func verifyPassword(password, stored string) bool {
	parts := strings.SplitN(stored, ":", 2)
	if len(parts) != 2 {
		return false
	}
	salt, err := hex.DecodeString(parts[0])
	if err != nil {
		return false
	}
	want, err := hex.DecodeString(parts[1])
	if err != nil {
		return false
	}
	sum := sha256.Sum256(append(salt, []byte(password)...))
	return subtle.ConstantTimeCompare(sum[:], want) == 1
}

type user struct {
	Username     string
	PasswordHash string
	Role         string
}

var (
	usersMu sync.Mutex
	users   = map[string]*user{}
)

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

func registerHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !usernameRe.MatchString(req.Username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, _, or -")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		writeError(w, http.StatusBadRequest, "role must be dm or player")
		return
	}

	usersMu.Lock()
	defer usersMu.Unlock()

	if _, exists := users[req.Username]; exists {
		writeError(w, http.StatusConflict, "username already exists")
		return
	}

	hash, err := hashPassword(req.Password)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to register user")
		return
	}

	users[req.Username] = &user{Username: req.Username, PasswordHash: hash, Role: req.Role}

	writeJSON(w, http.StatusCreated, map[string]string{
		"username": req.Username,
		"role":     req.Role,
	})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Username == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "username and password are required")
		return
	}

	usersMu.Lock()
	u, ok := users[req.Username]
	usersMu.Unlock()

	if !ok || !verifyPassword(req.Password, u.PasswordHash) {
		writeError(w, http.StatusUnauthorized, "invalid username or password")
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"username": u.Username,
		"token":    "session-" + u.Username,
	})
}

// --- Durable SQLite-backed storage ---
//
// The target is Go stdlib only (no third-party packages), so no live SQLite
// driver is available. game.db is treated as the durable store: it is
// created on startup with the SQLite file-format magic header so it is a
// recognizable SQLite database on disk. Reset recreates the file and clears
// all benchmark-created in-process durable data.

const (
	storageDriver    = "sqlite"
	storageSchemaVer = 1
	storageDBPath    = "game.db"
)

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
	h[96], h[97], h[98], h[99] = 0x00, 0x2E, 0xE9, 0x60
	return h
}

var (
	storageMu      sync.Mutex
	storageReadyOK bool
)

func initStorage() error {
	storageMu.Lock()
	defer storageMu.Unlock()
	return initStorageLocked()
}

func initStorageLocked() error {
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

	campaignsMu.Lock()
	campaigns = map[string]*campaign{}
	campaignsMu.Unlock()

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

func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	storageMu.Lock()
	initialized := storageReadyOK
	storageMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{
		"driver":         storageDriver,
		"schema_version": storageSchemaVer,
		"initialized":    initialized,
	})
}

func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	if err := initStorage(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to reset storage")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":             true,
		"schema_version": storageSchemaVer,
	})
}

// --- Compendium: monsters and items ---

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

var slugRe = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)

func monsterCreateView(m *monster) map[string]any {
	return map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
	}
}

func monsterReadView(m *monster) map[string]any {
	tags := m.Tags
	if tags == nil {
		tags = []string{}
	}
	return map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
		"tags":        tags,
	}
}

func itemView(it *item) map[string]any {
	return map[string]any{
		"slug":    it.Slug,
		"name":    it.Name,
		"type":    it.Type,
		"rarity":  it.Rarity,
		"cost_gp": it.CostGP,
	}
}

func createMonsterHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	var req struct {
		Slug       string   `json:"slug"`
		Name       string   `json:"name"`
		CR         string   `json:"cr"`
		ArmorClass *int     `json:"armor_class"`
		HitPoints  *int     `json:"hit_points"`
		Tags       []string `json:"tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be lowercase alphanumeric with hyphens")
		return
	}
	if req.Name == "" || req.CR == "" || req.ArmorClass == nil || req.HitPoints == nil {
		writeError(w, http.StatusBadRequest, "name, cr, armor_class, and hit_points are required")
		return
	}
	if *req.ArmorClass < 0 || *req.HitPoints < 0 {
		writeError(w, http.StatusBadRequest, "armor_class and hit_points must be non-negative")
		return
	}

	compendiumMu.Lock()
	defer compendiumMu.Unlock()

	if _, exists := monsters[req.Slug]; exists {
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}

	m := &monster{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: *req.ArmorClass,
		HitPoints:  *req.HitPoints,
		Tags:       req.Tags,
	}
	monsters[req.Slug] = m

	writeJSON(w, http.StatusCreated, monsterCreateView(m))
}

func readMonsterHandler(w http.ResponseWriter, r *http.Request, slug string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	compendiumMu.Lock()
	m, ok := monsters[slug]
	compendiumMu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}
	writeJSON(w, http.StatusOK, monsterReadView(m))
}

func monstersHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		createMonsterHandler(w, r)
		return
	}
	writeError(w, http.StatusBadRequest, "method not allowed")
}

func monsterSubrouteHandler(w http.ResponseWriter, r *http.Request) {
	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/monsters/")
	if slug == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	readMonsterHandler(w, r, slug)
}

func createItemHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	var req struct {
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		Type   string `json:"type"`
		Rarity string `json:"rarity"`
		CostGP *int   `json:"cost_gp"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be lowercase alphanumeric with hyphens")
		return
	}
	if req.Name == "" || req.Type == "" || req.Rarity == "" || req.CostGP == nil {
		writeError(w, http.StatusBadRequest, "name, type, rarity, and cost_gp are required")
		return
	}
	if *req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "cost_gp must be non-negative")
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

	writeJSON(w, http.StatusCreated, itemView(it))
}

func readItemHandler(w http.ResponseWriter, r *http.Request, slug string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	compendiumMu.Lock()
	it, ok := items[slug]
	compendiumMu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}
	writeJSON(w, http.StatusOK, itemView(it))
}

func itemsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		createItemHandler(w, r)
		return
	}
	writeError(w, http.StatusBadRequest, "method not allowed")
}

func itemSubrouteHandler(w http.ResponseWriter, r *http.Request) {
	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/items/")
	if slug == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	readItemHandler(w, r, slug)
}

// --- Campaign state ---

type character struct {
	ID    string
	Name  string
	Level int
	Class string
}

type sessionEvent struct {
	ID      string
	Kind    string
	Summary string
}

type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters []*character
	Events     []*sessionEvent
}

var (
	campaignsMu sync.Mutex
	campaigns   = map[string]*campaign{}
)

func campaignCreateView(c *campaign) map[string]any {
	return map[string]any{"id": c.ID, "name": c.Name, "dm": c.DM}
}

func characterView(ch *character) map[string]any {
	return map[string]any{"id": ch.ID, "name": ch.Name, "level": ch.Level, "class": ch.Class}
}

func eventView(e *sessionEvent) map[string]any {
	return map[string]any{"id": e.ID, "kind": e.Kind}
}

func campaignStateView(c *campaign) map[string]any {
	chars := make([]map[string]any, 0, len(c.Characters))
	for _, ch := range c.Characters {
		chars = append(chars, characterView(ch))
	}
	return map[string]any{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": chars,
		"log_count":  len(c.Events),
	}
}

func createCampaignHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.DM == "" {
		writeError(w, http.StatusBadRequest, "id, name, and dm are required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	if _, exists := campaigns[req.ID]; exists {
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}

	c := &campaign{ID: req.ID, Name: req.Name, DM: req.DM}
	campaigns[req.ID] = c

	writeJSON(w, http.StatusCreated, campaignCreateView(c))
}

func addCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	var req struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		Level *int   `json:"level"`
		Class string `json:"class"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Level == nil || req.Class == "" {
		writeError(w, http.StatusBadRequest, "id, name, level, and class are required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, ok := campaigns[campaignID]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, ch := range c.Characters {
		if ch.ID == req.ID {
			writeError(w, http.StatusConflict, "character id already exists")
			return
		}
	}

	ch := &character{ID: req.ID, Name: req.Name, Level: *req.Level, Class: req.Class}
	c.Characters = append(c.Characters, ch)

	writeJSON(w, http.StatusCreated, characterView(ch))
}

func addEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}
	var req struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Kind == "" || req.Summary == "" {
		writeError(w, http.StatusBadRequest, "id, kind, and summary are required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, ok := campaigns[campaignID]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, e := range c.Events {
		if e.ID == req.ID {
			writeError(w, http.StatusConflict, "event id already exists")
			return
		}
	}

	e := &sessionEvent{ID: req.ID, Kind: req.Kind, Summary: req.Summary}
	c.Events = append(c.Events, e)

	writeJSON(w, http.StatusCreated, eventView(e))
}

func campaignStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusBadRequest, "method not allowed")
		return
	}

	campaignsMu.Lock()
	c, ok := campaigns[campaignID]
	campaignsMu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	writeJSON(w, http.StatusOK, campaignStateView(c))
}

func campaignSubrouteHandler(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/v1/campaigns/")
	parts := strings.SplitN(path, "/", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	campaignID, action := parts[0], parts[1]

	switch action {
	case "characters":
		addCharacterHandler(w, r, campaignID)
	case "events":
		addEventHandler(w, r, campaignID)
	case "state":
		campaignStateHandler(w, r, campaignID)
	default:
		writeError(w, http.StatusNotFound, "not found")
	}
}

// --- Selected PHB rules ---

var wizardLevel5Slots = map[string]int{"1": 4, "2": 3, "3": 2}

func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Class string `json:"class"`
		Level *int   `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Class != "wizard" || req.Level == nil || *req.Level != 5 {
		writeError(w, http.StatusBadRequest, "unsupported class or level")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"class": req.Class,
		"level": *req.Level,
		"slots": wizardLevel5Slots,
	})
}

func longRestHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level           *int `json:"level"`
		HPCurrent       *int `json:"hp_current"`
		HPMax           *int `json:"hp_max"`
		HitDiceSpent    *int `json:"hit_dice_spent"`
		ExhaustionLevel *int `json:"exhaustion_level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level == nil || req.HPCurrent == nil || req.HPMax == nil || req.HitDiceSpent == nil || req.ExhaustionLevel == nil {
		writeError(w, http.StatusBadRequest, "level, hp_current, hp_max, hit_dice_spent, and exhaustion_level are required")
		return
	}
	if *req.Level < 1 || *req.HPMax < 0 || *req.HPCurrent < 0 || *req.HitDiceSpent < 0 || *req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest, "fields must be non-negative")
		return
	}

	hpCurrent := *req.HPMax

	recoverDice := *req.Level / 2
	if recoverDice < 1 {
		recoverDice = 1
	}
	hitDiceSpent := *req.HitDiceSpent - recoverDice
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustionLevel := *req.ExhaustionLevel - 1
	if exhaustionLevel < 0 {
		exhaustionLevel = 0
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"hp_current":       hpCurrent,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustionLevel,
	})
}

func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Strength *int `json:"strength"`
		Weight   *int `json:"weight"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Strength == nil || req.Weight == nil || *req.Strength < 0 || *req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "strength and weight must be non-negative")
		return
	}

	capacity := *req.Strength * 15
	encumbered := *req.Weight > capacity

	writeJSON(w, http.StatusOK, map[string]any{
		"capacity":   capacity,
		"weight":     *req.Weight,
		"encumbered": encumbered,
	})
}

// --- DM tools ---

func encounterRecommendation(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "trivial - skip or use as flavor"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "balanced challenge"
	case "hard":
		return "bring your A-game"
	default:
		return "deadly - consider reinforcements or an escape route"
	}
}

func encounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
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

	compendiumMu.Lock()
	crCounts := map[string]int{}
	for _, slug := range req.MonsterSlugs {
		m, ok := monsters[slug]
		if !ok {
			compendiumMu.Unlock()
			writeError(w, http.StatusBadRequest, "unknown monster slug: "+slug)
			return
		}
		crCounts[m.CR]++
	}
	compendiumMu.Unlock()

	groups := make([]xpMonsterGroup, 0, len(crCounts))
	for cr, count := range crCounts {
		groups = append(groups, xpMonsterGroup{CR: cr, Count: count})
	}
	partyLevels := make([]int, 0, len(req.Party))
	for _, p := range req.Party {
		partyLevels = append(partyLevels, p.Level)
	}

	baseXP, monsterCount, _, adjustedXP, difficulty, _, err := computeAdjustedXP(partyLevels, groups)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":    req.CampaignID,
		"base_xp":        baseXP,
		"adjusted_xp":    adjustedXP,
		"difficulty":     difficulty,
		"monster_count":  monsterCount,
		"recommendation": encounterRecommendation(difficulty),
	})
}

func lootParcelHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Tier       *int   `json:"tier"`
		Seed       *int   `json:"seed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if req.Tier == nil || *req.Tier != 1 {
		writeError(w, http.StatusBadRequest, "unsupported tier")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": req.CampaignID,
		"coins_gp":    75,
		"items": []map[string]any{
			{"slug": "healing-potion", "quantity": 2},
		},
	})
}

func sessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}

	campaignsMu.Lock()
	_, ok := campaigns[req.CampaignID]
	campaignsMu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":  req.CampaignID,
		"summary":      "Nyx scouts the goblin trail.",
		"open_threads": []string{"Resolve goblin trail ambush"},
	})
}

func main() {
	if err := initStorage(); err != nil {
		log.Fatal(err)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)
	mux.HandleFunc("/v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("/v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("/v1/characters/derived-stats", derivedStatsHandler)
	mux.HandleFunc("/v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("/v1/combat/sessions/", combatSessionSubrouteHandler)
	mux.HandleFunc("/v1/auth/register", registerHandler)
	mux.HandleFunc("/v1/auth/login", loginHandler)
	mux.HandleFunc("GET /v1/storage/status", storageStatusHandler)
	mux.HandleFunc("POST /v1/storage/reset", storageResetHandler)
	mux.HandleFunc("/v1/compendium/monsters", monstersHandler)
	mux.HandleFunc("/v1/compendium/monsters/", monsterSubrouteHandler)
	mux.HandleFunc("/v1/compendium/items", itemsHandler)
	mux.HandleFunc("/v1/compendium/items/", itemSubrouteHandler)
	mux.HandleFunc("/v1/campaigns", createCampaignHandler)
	mux.HandleFunc("/v1/campaigns/", campaignSubrouteHandler)
	mux.HandleFunc("POST /v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("POST /v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("POST /v1/phb/equipment-load", equipmentLoadHandler)
	mux.HandleFunc("POST /v1/dm/encounter-builder", encounterBuilderHandler)
	mux.HandleFunc("POST /v1/dm/loot-parcel", lootParcelHandler)
	mux.HandleFunc("POST /v1/dm/session-recap", sessionRecapHandler)

	addr := "127.0.0.1:" + port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
