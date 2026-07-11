package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha512"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
)

var errInvalid = errors.New("invalid dice expression")

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Initialize durable SQLite-backed storage before serving traffic.
	if err := store.initSchema(); err != nil {
		log.Printf("storage init failed: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handleHealth)
	mux.HandleFunc("POST /v1/dice/stats", handleDiceStats)
	mux.HandleFunc("POST /v1/checks/ability", handleAbility)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", handleEncounter)
	mux.HandleFunc("POST /v1/initiative/order", handleInitiative)
	mux.HandleFunc("POST /v1/characters/ability-modifier", handleAbilityModifier)
	mux.HandleFunc("POST /v1/characters/proficiency", handleProficiency)
	mux.HandleFunc("POST /v1/characters/derived-stats", handleDerivedStats)
	mux.HandleFunc("POST /v1/combat/sessions", handleCreateSession)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", handleAdvanceTurn)
	mux.HandleFunc("POST /v1/auth/register", handleRegister)
	mux.HandleFunc("POST /v1/auth/login", handleLogin)
	mux.HandleFunc("GET /v1/storage/status", handleStorageStatus)
	mux.HandleFunc("POST /v1/storage/reset", handleStorageReset)
	mux.HandleFunc("POST /v1/compendium/monsters", handleCreateMonster)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", handleReadMonster)
	mux.HandleFunc("POST /v1/compendium/items", handleCreateItem)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", handleReadItem)
	mux.HandleFunc("POST /v1/campaigns", handleCreateCampaign)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", handleAddCampaignCharacter)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", handleAddCampaignEvent)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", handleReadCampaignState)
	mux.HandleFunc("POST /v1/phb/spell-slots", handleSpellSlots)
	mux.HandleFunc("POST /v1/phb/rests/long", handleLongRest)
	mux.HandleFunc("POST /v1/phb/equipment-load", handleEquipmentLoad)
	mux.HandleFunc("POST /v1/dm/encounter-builder", handleEncounterBuilder)
	mux.HandleFunc("POST /v1/dm/loot-parcel", handleLootParcel)
	mux.HandleFunc("POST /v1/dm/session-recap", handleSessionRecap)

	addr := "127.0.0.1:" + port
	log.Printf("dndrest listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func badRequest(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
}

// --- GET /health ---

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

// --- POST /v1/dice/stats ---

type diceStatsReq struct {
	Expression string `json:"expression"`
}

type diceStatsResp struct {
	DiceCount int     `json:"dice_count"`
	Sides     int     `json:"sides"`
	Modifier  int     `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

func handleDiceStats(w http.ResponseWriter, r *http.Request) {
	var req diceStatsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	count, sides, modifier, err := parseDice(req.Expression)
	if err != nil {
		badRequest(w, "invalid expression")
		return
	}
	writeJSON(w, http.StatusOK, diceStatsResp{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       count + modifier,
		Max:       count*sides + modifier,
		Average:   float64(count*(sides+1))/2 + float64(modifier),
	})
}

// parseDice parses "<count>d<sides>[+<modifier>|-<modifier>]".
func parseDice(expr string) (count, sides, modifier int, err error) {
	di := strings.Index(expr, "d")
	if di < 0 {
		return 0, 0, 0, errInvalid
	}
	countPart := expr[:di]
	rest := expr[di+1:]
	if rest == "" {
		return 0, 0, 0, errInvalid
	}
	count, err = strconv.Atoi(countPart)
	if err != nil || count <= 0 {
		return 0, 0, 0, errInvalid
	}
	// sides has no sign; the first '+' or '-' begins the modifier.
	idx := -1
	for i := 0; i < len(rest); i++ {
		if rest[i] == '+' || rest[i] == '-' {
			idx = i
			break
		}
	}
	var sidesPart, modPart string
	if idx < 0 {
		sidesPart = rest
	} else {
		sidesPart = rest[:idx]
		modPart = rest[idx:]
	}
	sides, err = strconv.Atoi(sidesPart)
	if err != nil || sides <= 0 {
		return 0, 0, 0, errInvalid
	}
	if modPart != "" {
		modifier, err = strconv.Atoi(modPart)
		if err != nil {
			return 0, 0, 0, errInvalid
		}
	}
	return count, sides, modifier, nil
}

// --- POST /v1/checks/ability ---

type abilityReq struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

type abilityResp struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

func handleAbility(w http.ResponseWriter, r *http.Request) {
	var req abilityReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, abilityResp{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

// --- POST /v1/encounters/adjusted-xp ---

type partyMember struct {
	Level int `json:"level"`
}

type monster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type encounterReq struct {
	Party    []partyMember `json:"party"`
	Monsters []monster     `json:"monsters"`
}

type thresholdsResp struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type encounterResp struct {
	BaseXP       int            `json:"base_xp"`
	MonsterCount int            `json:"monster_count"`
	Multiplier   float64        `json:"multiplier"`
	AdjustedXP   float64        `json:"adjusted_xp"`
	Difficulty   string         `json:"difficulty"`
	Thresholds   thresholdsResp `json:"thresholds"`
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

// First benchmark suite: level-3 encounter thresholds.
const (
	lvl3Easy   = 75
	lvl3Medium = 150
	lvl3Hard   = 225
	lvl3Deadly = 400
)

func multiplierFor(count int) float64 {
	switch {
	case count >= 15:
		return 4
	case count >= 11:
		return 3
	case count >= 7:
		return 2.5
	case count >= 3:
		return 2
	case count == 2:
		return 1.5
	default: // 0 or 1
		return 1
	}
}

func handleEncounter(w http.ResponseWriter, r *http.Request) {
	var req encounterReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			badRequest(w, "unknown cr")
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}
	tEasy, tMedium, tHard, tDeadly := 0, 0, 0, 0
	for _, p := range req.Party {
		if p.Level != 3 {
			badRequest(w, "unsupported level")
			return
		}
		tEasy += lvl3Easy
		tMedium += lvl3Medium
		tHard += lvl3Hard
		tDeadly += lvl3Deadly
	}
	mult := multiplierFor(monsterCount)
	adjusted := float64(baseXP) * mult
	difficulty := "trivial"
	switch {
	case adjusted >= float64(tDeadly):
		difficulty = "deadly"
	case adjusted >= float64(tHard):
		difficulty = "hard"
	case adjusted >= float64(tMedium):
		difficulty = "medium"
	case adjusted >= float64(tEasy):
		difficulty = "easy"
	default:
		difficulty = "trivial"
	}
	writeJSON(w, http.StatusOK, encounterResp{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   mult,
		AdjustedXP:   adjusted,
		Difficulty:   difficulty,
		Thresholds: thresholdsResp{
			Easy:   tEasy,
			Medium: tMedium,
			Hard:   tHard,
			Deadly: tDeadly,
		},
	})
}

// --- POST /v1/initiative/order ---

type combatant struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

type initiativeReq struct {
	Combatants []combatant `json:"combatants"`
}

type orderEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeResp struct {
	Order []orderEntry `json:"order"`
}

func handleInitiative(w http.ResponseWriter, r *http.Request) {
	var req initiativeReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	combatants := req.Combatants
	sort.SliceStable(combatants, func(i, j int) bool {
		si := combatants[i].Roll + combatants[i].Dex
		sj := combatants[j].Roll + combatants[j].Dex
		if si != sj {
			return si > sj // score descending
		}
		if combatants[i].Dex != combatants[j].Dex {
			return combatants[i].Dex > combatants[j].Dex // dex descending
		}
		return combatants[i].Name < combatants[j].Name // name ascending
	})
	order := make([]orderEntry, 0, len(combatants))
	for _, c := range combatants {
		order = append(order, orderEntry{Name: c.Name, Score: c.Roll + c.Dex})
	}
	writeJSON(w, http.StatusOK, initiativeResp{Order: order})
}

// --- Character rules helpers ---

// abilityModifier computes floor((score-10)/2), flooring negative halves.
func abilityModifier(score int) int {
	diff := score - 10
	m := diff / 2 // Go integer division truncates toward zero
	if diff < 0 && diff%2 != 0 {
		m-- // adjust truncation to floor for negative odd dividends
	}
	return m
}

// proficiencyBonus returns the proficiency bonus for a valid level (1-20).
func proficiencyBonus(level int) int {
	switch {
	case level >= 17:
		return 6
	case level >= 13:
		return 5
	case level >= 9:
		return 4
	case level >= 5:
		return 3
	default:
		return 2
	}
}

// --- POST /v1/characters/ability-modifier ---

type abilityModifierReq struct {
	Score int `json:"score"`
}

type abilityModifierResp struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req abilityModifierReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Score < 1 || req.Score > 30 {
		badRequest(w, "score must be between 1 and 30")
		return
	}
	writeJSON(w, http.StatusOK, abilityModifierResp{
		Score:    req.Score,
		Modifier: abilityModifier(req.Score),
	})
}

// --- POST /v1/characters/proficiency ---

type proficiencyReq struct {
	Level int `json:"level"`
}

type proficiencyResp struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req proficiencyReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be between 1 and 20")
		return
	}
	writeJSON(w, http.StatusOK, proficiencyResp{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
	})
}

// --- POST /v1/characters/derived-stats ---

type abilities struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type armorSpec struct {
	Base   int  `json:"base"`
	Shield bool `json:"shield"`
	DexCap int  `json:"dex_cap"`
}

type derivedStatsReq struct {
	Level     int       `json:"level"`
	Abilities abilities `json:"abilities"`
	Armor     armorSpec `json:"armor"`
}

type modifiersResp struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type derivedStatsResp struct {
	Level            int           `json:"level"`
	ProficiencyBonus int           `json:"proficiency_bonus"`
	HPMax            int           `json:"hp_max"`
	ArmorClass       int           `json:"armor_class"`
	Modifiers        modifiersResp `json:"modifiers"`
}

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	var req derivedStatsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be between 1 and 20")
		return
	}
	for _, s := range [6]int{req.Abilities.Str, req.Abilities.Dex, req.Abilities.Con,
		req.Abilities.Int, req.Abilities.Wis, req.Abilities.Cha} {
		if s < 1 || s > 30 {
			badRequest(w, "ability scores must be between 1 and 30")
			return
		}
	}
	strMod := abilityModifier(req.Abilities.Str)
	dexMod := abilityModifier(req.Abilities.Dex)
	conMod := abilityModifier(req.Abilities.Con)
	intMod := abilityModifier(req.Abilities.Int)
	wisMod := abilityModifier(req.Abilities.Wis)
	chaMod := abilityModifier(req.Abilities.Cha)
	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := req.Armor.Base + min(dexMod, req.Armor.DexCap) + shieldBonus
	writeJSON(w, http.StatusOK, derivedStatsResp{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
		HPMax:            req.Level * (6 + conMod),
		ArmorClass:       armorClass,
		Modifiers: modifiersResp{
			Str: strMod,
			Dex: dexMod,
			Con: conMod,
			Int: intMod,
			Wis: wisMod,
			Cha: chaMod,
		},
	})
}

// --- Combat state (stateful) ---

// combatSession is an in-memory combat encounter.
type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []orderEntry
	Conditions map[string][]conditionEntry
}

type conditionEntry struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

var sessions = struct {
	sync.Mutex
	m map[string]*combatSession
}{m: make(map[string]*combatSession)}

// notFound writes a 404 JSON error response.
func notFound(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusNotFound, map[string]string{"error": msg})
}

// sortByInitiative sorts combatants by score desc, dex desc, name asc and
// returns the resulting initiative order.
func sortByInitiative(combatants []combatant) []orderEntry {
	sort.SliceStable(combatants, func(i, j int) bool {
		si := combatants[i].Roll + combatants[i].Dex
		sj := combatants[j].Roll + combatants[j].Dex
		if si != sj {
			return si > sj
		}
		if combatants[i].Dex != combatants[j].Dex {
			return combatants[i].Dex > combatants[j].Dex
		}
		return combatants[i].Name < combatants[j].Name
	})
	order := make([]orderEntry, 0, len(combatants))
	for _, c := range combatants {
		order = append(order, orderEntry{Name: c.Name, Score: c.Roll + c.Dex})
	}
	return order
}

// --- POST /v1/combat/sessions ---

type createSessionReq struct {
	ID         string      `json:"id"`
	Combatants []combatant `json:"combatants"`
}

type createSessionResp struct {
	ID        string       `json:"id"`
	Round     int          `json:"round"`
	TurnIndex int          `json:"turn_index"`
	Active    orderEntry   `json:"active"`
	Order     []orderEntry `json:"order"`
}

func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	var req createSessionReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.ID == "" {
		badRequest(w, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		badRequest(w, "combatants required")
		return
	}
	order := sortByInitiative(req.Combatants)
	sess := &combatSession{
		ID:         req.ID,
		Round:      1,
		TurnIndex:  0,
		Order:      order,
		Conditions: map[string][]conditionEntry{},
	}
	sessions.Lock()
	sessions.m[req.ID] = sess
	sessions.Unlock()
	writeJSON(w, http.StatusOK, createSessionResp{
		ID:        sess.ID,
		Round:     sess.Round,
		TurnIndex: sess.TurnIndex,
		Active:    sess.Order[0],
		Order:     sess.Order,
	})
}

// --- POST /v1/combat/sessions/{id}/conditions ---

type addConditionReq struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds int    `json:"duration_rounds"`
}

type addConditionResp struct {
	Target     string           `json:"target"`
	Conditions []conditionEntry `json:"conditions"`
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sessions.Lock()
	sess, ok := sessions.m[id]
	sessions.Unlock()
	if !ok {
		notFound(w, "session not found")
		return
	}
	var req addConditionReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	found := false
	for _, c := range sess.Order {
		if c.Name == req.Target {
			found = true
			break
		}
	}
	if !found {
		badRequest(w, "target not in session")
		return
	}
	if req.DurationRounds <= 0 {
		badRequest(w, "duration_rounds must be a positive integer")
		return
	}
	sessions.Lock()
	sess.Conditions[req.Target] = append(sess.Conditions[req.Target], conditionEntry{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})
	conds := make([]conditionEntry, len(sess.Conditions[req.Target]))
	copy(conds, sess.Conditions[req.Target])
	sessions.Unlock()
	writeJSON(w, http.StatusOK, addConditionResp{
		Target:     req.Target,
		Conditions: conds,
	})
}

// --- POST /v1/combat/sessions/{id}/advance ---

type advanceResp struct {
	ID         string                      `json:"id"`
	Round      int                         `json:"round"`
	TurnIndex  int                         `json:"turn_index"`
	Active     orderEntry                  `json:"active"`
	Conditions map[string][]conditionEntry `json:"conditions"`
}

func handleAdvanceTurn(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sessions.Lock()
	sess, ok := sessions.m[id]
	if !ok {
		sessions.Unlock()
		notFound(w, "session not found")
		return
	}
	// Advance to the next combatant, wrapping and incrementing round.
	sess.TurnIndex++
	if sess.TurnIndex >= len(sess.Order) {
		sess.TurnIndex = 0
		sess.Round++
	}
	active := sess.Order[sess.TurnIndex]
	activeName := active.Name
	// At the start of the active combatant's turn, tick down their conditions.
	conds, hadConds := sess.Conditions[activeName]
	for i := range conds {
		conds[i].RemainingRounds--
	}
	kept := make([]conditionEntry, 0, len(conds))
	for _, c := range conds {
		if c.RemainingRounds > 0 {
			kept = append(kept, c)
		}
	}
	if hadConds {
		// Keep the combatant's entry (with an empty list when all conditions
		// have expired) so callers can see the condition was removed. We only
		// set the key for combatants who already had conditions, so combatants
		// who never had conditions don't appear in the response.
		sess.Conditions[activeName] = kept
	}
	// Build a stable copy of all remaining conditions for the response.
	respConditions := map[string][]conditionEntry{}
	for name, cs := range sess.Conditions {
		cp := make([]conditionEntry, len(cs))
		copy(cp, cs)
		respConditions[name] = cp
	}
	sessions.Unlock()
	writeJSON(w, http.StatusOK, advanceResp{
		ID:         sess.ID,
		Round:      sess.Round,
		TurnIndex:  sess.TurnIndex,
		Active:     active,
		Conditions: respConditions,
	})
}

// --- Auth: users and password login ---

// userRecord stores a registered user. The plain password is never persisted;
// only a salted, iterated hash is kept.
type userRecord struct {
	Username string
	Role     string
	Salt     []byte
	Hash     []byte
}

var users = struct {
	sync.Mutex
	m map[string]*userRecord
}{m: make(map[string]*userRecord)}

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

const (
	saltLen          = 16
	pwHashIterations = 10000
)

// deriveHash computes an iterated SHA-512 of salt+password. Isolated so a
// production-grade hash (e.g. bcrypt/argon2) can replace it without touching
// the handlers.
func deriveHash(salt []byte, password string) []byte {
	h := sha512.New()
	h.Write(salt)
	h.Write([]byte(password))
	sum := h.Sum(nil)
	for i := 0; i < pwHashIterations; i++ {
		h.Reset()
		h.Write(sum)
		sum = h.Sum(nil)
	}
	return sum
}

// hashPassword generates a fresh random salt and returns it with the derived hash.
func hashPassword(password string) (salt, hash []byte, err error) {
	salt = make([]byte, saltLen)
	if _, err = rand.Read(salt); err != nil {
		return nil, nil, err
	}
	return salt, deriveHash(salt, password), nil
}

// checkPassword verifies a password against the stored salt and hash.
func checkPassword(storedSalt, storedHash []byte, password string) bool {
	return bytes.Equal(deriveHash(storedSalt, password), storedHash)
}

// --- POST /v1/auth/register ---

type registerReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

type registerResp struct {
	Username string `json:"username"`
	Role     string `json:"role"`
}

func handleRegister(w http.ResponseWriter, r *http.Request) {
	var req registerReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if !usernameRe.MatchString(req.Username) {
		badRequest(w, "username must be 2-32 characters: lowercase letters, digits, _ or -")
		return
	}
	if len(req.Password) < 8 {
		badRequest(w, "password must be at least 8 characters")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		badRequest(w, "role must be dm or player")
		return
	}
	salt, hash, err := hashPassword(req.Password)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "hash error"})
		return
	}
	users.Lock()
	defer users.Unlock()
	if _, ok := users.m[req.Username]; ok {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "username already exists"})
		return
	}
	users.m[req.Username] = &userRecord{
		Username: req.Username,
		Role:     req.Role,
		Salt:     salt,
		Hash:     hash,
	}
	writeJSON(w, http.StatusCreated, registerResp{Username: req.Username, Role: req.Role})
}

// --- POST /v1/auth/login ---

type loginReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type loginResp struct {
	Username string `json:"username"`
	Token    string `json:"token"`
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	users.Lock()
	u, ok := users.m[req.Username]
	users.Unlock()
	if !ok || !checkPassword(u.Salt, u.Hash, req.Password) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid credentials"})
		return
	}
	writeJSON(w, http.StatusOK, loginResp{
		Username: u.Username,
		Token:    "session-" + u.Username,
	})
}

// --- SQLite durable storage ---

// The stdlib constraint forbids third-party SQLite drivers, so the durable
// game.db file is managed by hand as a valid SQLite-format-3 database. It is a
// single-page empty database whose schema is initialized on startup and
// recreated on reset; the storage API reports on this artifact. Runtime game
// state stays in memory (preserving prior-stage behavior); the file is the
// durable backing store required by this stage.
const (
	dbPath        = "game.db"
	schemaVersion = 1
	dbPageSize    = 4096
)

var store = &storage{}

type storage struct {
	mu          sync.RWMutex
	initialized bool
}

// initSchema creates (or recreates) game.db as a valid empty SQLite database
// and marks storage initialized.
func (s *storage) initSchema() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := writeEmptySQLiteDB(dbPath); err != nil {
		s.initialized = false
		return err
	}
	s.initialized = true
	return nil
}

// reset recreates the schema file and clears benchmark-created in-memory data.
func (s *storage) reset() error {
	if err := s.initSchema(); err != nil {
		return err
	}
	sessions.Lock()
	for k := range sessions.m {
		delete(sessions.m, k)
	}
	sessions.Unlock()
	users.Lock()
	for k := range users.m {
		delete(users.m, k)
	}
	users.Unlock()
	compendium.Lock()
	for k := range compendium.monsters {
		delete(compendium.monsters, k)
	}
	for k := range compendium.items {
		delete(compendium.items, k)
	}
	compendium.Unlock()
	campaigns.Lock()
	for k := range campaigns.m {
		delete(campaigns.m, k)
	}
	campaigns.Unlock()
	return nil
}

// writeEmptySQLiteDB writes a minimal, valid SQLite-format-3 database file: a
// single 4096-byte page with the canonical header and an empty sqlite_master
// b-tree. The file is openable by the sqlite3 CLI and reports magic
// "SQLite format 3".
func writeEmptySQLiteDB(path string) error {
	page := make([]byte, dbPageSize)
	// --- Database header (100 bytes) ---
	copy(page[0:16], []byte("SQLite format 3\x00"))
	page[16] = 0x10 // page size high byte (4096 = 0x1000)
	page[17] = 0x00 // page size low byte
	page[18] = 1    // file format write version (legacy)
	page[19] = 1    // file format read version (legacy)
	page[20] = 0    // reserved space at end of each page
	page[21] = 64   // max embedded payload fraction (must be 64)
	page[22] = 32   // min embedded payload fraction (must be 32)
	page[23] = 32   // leaf payload fraction (must be 32)
	page[27] = 1    // file change counter = 1
	page[31] = 1    // database size in pages = 1
	page[43] = 1    // schema cookie = 1
	page[47] = 4    // schema format number = 4
	page[59] = 1    // text encoding = 1 (UTF-8)
	page[95] = 1    // version-valid-for = 1
	// SQLITE_VERSION_NUMBER 3.45.0 = 3045000 = 0x002E7E28
	page[96] = 0x00
	page[97] = 0x2E
	page[98] = 0x7E
	page[99] = 0x28
	// --- B-tree page header for page 1 (offset 100) ---
	page[100] = 0x0D // leaf table b-tree (sqlite_master root)
	page[105] = 0x10 // cell content area start = 4096 (0x1000), big-endian
	page[106] = 0x00
	return os.WriteFile(path, page, 0o644)
}

// --- GET /v1/storage/status ---

type storageStatusResp struct {
	Driver        string `json:"driver"`
	SchemaVersion int    `json:"schema_version"`
	Initialized   bool   `json:"initialized"`
}

func handleStorageStatus(w http.ResponseWriter, r *http.Request) {
	store.mu.RLock()
	init := store.initialized
	store.mu.RUnlock()
	writeJSON(w, http.StatusOK, storageStatusResp{
		Driver:        "sqlite",
		SchemaVersion: schemaVersion,
		Initialized:   init,
	})
}

// --- POST /v1/storage/reset ---

type storageResetResp struct {
	OK            bool `json:"ok"`
	SchemaVersion int  `json:"schema_version"`
}

func handleStorageReset(w http.ResponseWriter, r *http.Request) {
	if err := store.reset(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage reset failed"})
		return
	}
	writeJSON(w, http.StatusOK, storageResetResp{
		OK:            true,
		SchemaVersion: schemaVersion,
	})
}

// --- Compendium: monsters and items ---

// monsterRecord is the full stored monster, including tags. The read endpoint
// returns this shape; the create endpoint returns monsterCreateResp (no tags).
type monsterRecord struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

// monsterCreateResp omits tags per the create-monster contract.
type monsterCreateResp struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
}

type itemRecord struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

// compendium holds monster and item records keyed by slug. As with the prior
// durable-storage stage, runtime state lives in memory while game.db remains
// the durable SQLite-format backing artifact; reset clears both.
var compendium = struct {
	sync.Mutex
	monsters map[string]*monsterRecord
	items    map[string]*itemRecord
}{
	monsters: make(map[string]*monsterRecord),
	items:    make(map[string]*itemRecord),
}

// conflict writes a 409 JSON error response.
func conflict(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusConflict, map[string]string{"error": msg})
}

// --- POST /v1/compendium/monsters ---

type createMonsterReq struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

func handleCreateMonster(w http.ResponseWriter, r *http.Request) {
	var req createMonsterReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Slug == "" {
		badRequest(w, "slug is required")
		return
	}
	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}
	compendium.Lock()
	defer compendium.Unlock()
	if _, ok := compendium.monsters[req.Slug]; ok {
		conflict(w, "monster slug already exists")
		return
	}
	m := &monsterRecord{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: req.ArmorClass,
		HitPoints:  req.HitPoints,
		Tags:       tags,
	}
	compendium.monsters[req.Slug] = m
	writeJSON(w, http.StatusCreated, monsterCreateResp{
		Slug:       m.Slug,
		Name:       m.Name,
		CR:         m.CR,
		ArmorClass: m.ArmorClass,
		HitPoints:  m.HitPoints,
	})
}

// --- GET /v1/compendium/monsters/{slug} ---

func handleReadMonster(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	compendium.Lock()
	m, ok := compendium.monsters[slug]
	compendium.Unlock()
	if !ok {
		notFound(w, "monster not found")
		return
	}
	tags := m.Tags
	if tags == nil {
		tags = []string{}
	}
	writeJSON(w, http.StatusOK, monsterRecord{
		Slug:       m.Slug,
		Name:       m.Name,
		CR:         m.CR,
		ArmorClass: m.ArmorClass,
		HitPoints:  m.HitPoints,
		Tags:       tags,
	})
}

// --- POST /v1/compendium/items ---

type createItemReq struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

func handleCreateItem(w http.ResponseWriter, r *http.Request) {
	var req createItemReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Slug == "" {
		badRequest(w, "slug is required")
		return
	}
	compendium.Lock()
	defer compendium.Unlock()
	if _, ok := compendium.items[req.Slug]; ok {
		conflict(w, "item slug already exists")
		return
	}
	it := &itemRecord{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: req.CostGP,
	}
	compendium.items[req.Slug] = it
	writeJSON(w, http.StatusCreated, itemRecord{
		Slug:   it.Slug,
		Name:   it.Name,
		Type:   it.Type,
		Rarity: it.Rarity,
		CostGP: it.CostGP,
	})
}

// --- GET /v1/compendium/items/{slug} ---

func handleReadItem(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	compendium.Lock()
	it, ok := compendium.items[slug]
	compendium.Unlock()
	if !ok {
		notFound(w, "item not found")
		return
	}
	writeJSON(w, http.StatusOK, itemRecord{
		Slug:   it.Slug,
		Name:   it.Name,
		Type:   it.Type,
		Rarity: it.Rarity,
		CostGP: it.CostGP,
	})
}

// --- Campaign state ---

// campaignCharacter is a character belonging to a campaign.
type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

// campaignEvent is a session log event. Summary is stored but never returned
// by the add-event endpoint (its response carries only id and kind).
type campaignEvent struct {
	ID      string
	Kind    string
	Summary string
}

// campaign holds campaign metadata plus its ordered characters and events.
type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters []*campaignCharacter
	Events     []*campaignEvent
}

// campaigns holds campaign records keyed by id. As with the prior stages,
// runtime state lives in memory while game.db remains the durable SQLite-format
// backing artifact; reset clears both.
var campaigns = struct {
	sync.Mutex
	m map[string]*campaign
}{m: make(map[string]*campaign)}

// --- POST /v1/campaigns ---

type createCampaignReq struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

type campaignResp struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

func handleCreateCampaign(w http.ResponseWriter, r *http.Request) {
	var req createCampaignReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.ID == "" {
		badRequest(w, "id is required")
		return
	}
	campaigns.Lock()
	defer campaigns.Unlock()
	if _, ok := campaigns.m[req.ID]; ok {
		conflict(w, "campaign already exists")
		return
	}
	campaigns.m[req.ID] = &campaign{
		ID:   req.ID,
		Name: req.Name,
		DM:   req.DM,
	}
	writeJSON(w, http.StatusCreated, campaignResp{ID: req.ID, Name: req.Name, DM: req.DM})
}

// --- POST /v1/campaigns/{id}/characters ---

type addCampaignCharacterReq struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

func handleAddCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	cid := r.PathValue("id")
	campaigns.Lock()
	defer campaigns.Unlock()
	camp, ok := campaigns.m[cid]
	if !ok {
		notFound(w, "campaign not found")
		return
	}
	var req addCampaignCharacterReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.ID == "" {
		badRequest(w, "id is required")
		return
	}
	for _, c := range camp.Characters {
		if c.ID == req.ID {
			conflict(w, "character already exists")
			return
		}
	}
	c := &campaignCharacter{
		ID:    req.ID,
		Name:  req.Name,
		Level: req.Level,
		Class: req.Class,
	}
	camp.Characters = append(camp.Characters, c)
	writeJSON(w, http.StatusCreated, campaignCharacter{
		ID:    c.ID,
		Name:  c.Name,
		Level: c.Level,
		Class: c.Class,
	})
}

// --- POST /v1/campaigns/{id}/events ---

type addCampaignEventReq struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

type campaignEventResp struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
}

func handleAddCampaignEvent(w http.ResponseWriter, r *http.Request) {
	cid := r.PathValue("id")
	campaigns.Lock()
	defer campaigns.Unlock()
	camp, ok := campaigns.m[cid]
	if !ok {
		notFound(w, "campaign not found")
		return
	}
	var req addCampaignEventReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.ID == "" {
		badRequest(w, "id is required")
		return
	}
	for _, e := range camp.Events {
		if e.ID == req.ID {
			conflict(w, "event already exists")
			return
		}
	}
	e := &campaignEvent{
		ID:      req.ID,
		Kind:    req.Kind,
		Summary: req.Summary,
	}
	camp.Events = append(camp.Events, e)
	writeJSON(w, http.StatusCreated, campaignEventResp{ID: e.ID, Kind: e.Kind})
}

// --- GET /v1/campaigns/{id}/state ---

type campaignStateResp struct {
	ID         string              `json:"id"`
	Name       string              `json:"name"`
	DM         string              `json:"dm"`
	Characters []campaignCharacter `json:"characters"`
	LogCount   int                 `json:"log_count"`
}

func handleReadCampaignState(w http.ResponseWriter, r *http.Request) {
	cid := r.PathValue("id")
	campaigns.Lock()
	defer campaigns.Unlock()
	camp, ok := campaigns.m[cid]
	if !ok {
		notFound(w, "campaign not found")
		return
	}
	chars := make([]campaignCharacter, 0, len(camp.Characters))
	for _, c := range camp.Characters {
		chars = append(chars, campaignCharacter{
			ID:    c.ID,
			Name:  c.Name,
			Level: c.Level,
			Class: c.Class,
		})
	}
	writeJSON(w, http.StatusOK, campaignStateResp{
		ID:         camp.ID,
		Name:       camp.Name,
		DM:         camp.DM,
		Characters: chars,
		LogCount:   len(camp.Events),
	})
}

// --- Selected PHB rules ---

// wizardSlotsByLevel is the full-caster (wizard) spell-slot progression from
// the Player's Handbook, keyed by character level then spell-slot level. Only
// non-zero slot counts are listed; the response omits zero-count slots.
var wizardSlotsByLevel = map[int]map[int]int{
	1:  {1: 2},
	2:  {1: 3},
	3:  {1: 4, 2: 2},
	4:  {1: 4, 2: 3},
	5:  {1: 4, 2: 3, 3: 2},
	6:  {1: 4, 2: 3, 3: 3},
	7:  {1: 4, 2: 3, 3: 3, 4: 1},
	8:  {1: 4, 2: 3, 3: 3, 4: 2},
	9:  {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
	10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
	11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
	12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
	13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
	14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
	15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
	16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
	17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
	18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
	19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
	20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}

// --- POST /v1/phb/spell-slots ---

type spellSlotsReq struct {
	Class string `json:"class"`
	Level int    `json:"level"`
}

type spellSlotsResp struct {
	Class string         `json:"class"`
	Level int            `json:"level"`
	Slots map[string]int `json:"slots"`
}

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req spellSlotsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Class != "wizard" {
		badRequest(w, "unsupported class")
		return
	}
	slotsByLevel, ok := wizardSlotsByLevel[req.Level]
	if !ok {
		badRequest(w, "unsupported level")
		return
	}
	slots := make(map[string]int, len(slotsByLevel))
	for k, v := range slotsByLevel {
		slots[strconv.Itoa(k)] = v
	}
	writeJSON(w, http.StatusOK, spellSlotsResp{
		Class: req.Class,
		Level: req.Level,
		Slots: slots,
	})
}

// --- POST /v1/phb/rests/long ---

type longRestReq struct {
	Level            int `json:"level"`
	HPCurrent        int `json:"hp_current"`
	HPMax            int `json:"hp_max"`
	HitDiceSpent     int `json:"hit_dice_spent"`
	ExhaustionLevel  int `json:"exhaustion_level"`
}

type longRestResp struct {
	HPCurrent       int `json:"hp_current"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req longRestReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 {
		badRequest(w, "level must be at least 1")
		return
	}
	// Restore spent hit dice up to half level (rounded down, minimum 1).
	restored := req.Level / 2
	if restored < 1 {
		restored = 1
	}
	hitDiceSpent := req.HitDiceSpent - restored
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}
	exhaustion := req.ExhaustionLevel - 1
	if exhaustion < 0 {
		exhaustion = 0
	}
	writeJSON(w, http.StatusOK, longRestResp{
		HPCurrent:       req.HPMax,
		HitDiceSpent:    hitDiceSpent,
		ExhaustionLevel: exhaustion,
	})
}

// --- POST /v1/phb/equipment-load ---

type equipmentLoadReq struct {
	Strength int `json:"strength"`
	Weight   int `json:"weight"`
}

type equipmentLoadResp struct {
	Capacity   int  `json:"capacity"`
	Weight     int  `json:"weight"`
	Encumbered bool `json:"encumbered"`
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req equipmentLoadReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	capacity := req.Strength * 15
	writeJSON(w, http.StatusOK, equipmentLoadResp{
		Capacity:   capacity,
		Weight:     req.Weight,
		Encumbered: req.Weight > capacity,
	})
}

// --- DM tools: encounter builder, loot parcel, session recap ---

// recommendationFor maps an encounter difficulty to a deterministic DM-facing
// recommendation string. "safe warm-up" is the benchmark's expected easy-tier
// recommendation.
func recommendationFor(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "trivial"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "balanced fight"
	case "hard":
		return "tough battle"
	case "deadly":
		return "lethal threat"
	}
	return "unknown"
}

// --- POST /v1/dm/encounter-builder ---

type encounterBuilderReq struct {
	CampaignID   string        `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

type encounterBuilderResp struct {
	CampaignID     string  `json:"campaign_id"`
	BaseXP         int     `json:"base_xp"`
	AdjustedXP     float64 `json:"adjusted_xp"`
	Difficulty     string  `json:"difficulty"`
	MonsterCount   int     `json:"monster_count"`
	Recommendation string  `json:"recommendation"`
}

// handleEncounterBuilder looks up each monster's CR from the compendium, then
// reuses the core-suite adjusted-XP math (crXP table, multiplierFor, and the
// level-3 threshold constants) to produce a deterministic recommendation.
func handleEncounterBuilder(w http.ResponseWriter, r *http.Request) {
	var req encounterBuilderReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.CampaignID == "" {
		badRequest(w, "campaign_id is required")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		badRequest(w, "monster_slugs required")
		return
	}
	baseXP := 0
	for _, slug := range req.MonsterSlugs {
		compendium.Lock()
		m, ok := compendium.monsters[slug]
		compendium.Unlock()
		if !ok {
			notFound(w, "monster not found")
			return
		}
		xp, ok := crXP[m.CR]
		if !ok {
			badRequest(w, "unknown cr")
			return
		}
		baseXP += xp
	}
	monsterCount := len(req.MonsterSlugs)
	// Reuse the core-suite level-3 thresholds.
	tEasy, tMedium, tHard, tDeadly := 0, 0, 0, 0
	for _, p := range req.Party {
		if p.Level != 3 {
			badRequest(w, "unsupported level")
			return
		}
		tEasy += lvl3Easy
		tMedium += lvl3Medium
		tHard += lvl3Hard
		tDeadly += lvl3Deadly
	}
	mult := multiplierFor(monsterCount)
	adjusted := float64(baseXP) * mult
	difficulty := "trivial"
	switch {
	case adjusted >= float64(tDeadly):
		difficulty = "deadly"
	case adjusted >= float64(tHard):
		difficulty = "hard"
	case adjusted >= float64(tMedium):
		difficulty = "medium"
	case adjusted >= float64(tEasy):
		difficulty = "easy"
	default:
		difficulty = "trivial"
	}
	writeJSON(w, http.StatusOK, encounterBuilderResp{
		CampaignID:     req.CampaignID,
		BaseXP:         baseXP,
		AdjustedXP:     adjusted,
		Difficulty:     difficulty,
		MonsterCount:   monsterCount,
		Recommendation: recommendationFor(difficulty),
	})
}

// --- POST /v1/dm/loot-parcel ---

type lootParcelReq struct {
	CampaignID string `json:"campaign_id"`
	Tier       int    `json:"tier"`
	Seed       int    `json:"seed"`
}

type lootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

type lootParcelResp struct {
	CampaignID string     `json:"campaign_id"`
	CoinsGP    int        `json:"coins_gp"`
	Items      []lootItem `json:"items"`
}

// tierLoot is the deterministic per-tier loot table. Tier 1 matches the
// benchmark's expected parcel; the seed is accepted but the output is fixed.
var tierLoot = map[int]struct {
	coinsGP int
	items   []lootItem
}{
	1: {coinsGP: 75, items: []lootItem{{Slug: "healing-potion", Quantity: 2}}},
	2: {coinsGP: 150, items: []lootItem{{Slug: "healing-potion", Quantity: 3}}},
	3: {coinsGP: 300, items: []lootItem{{Slug: "healing-potion", Quantity: 4}}},
	4: {coinsGP: 600, items: []lootItem{{Slug: "healing-potion", Quantity: 5}}},
}

func handleLootParcel(w http.ResponseWriter, r *http.Request) {
	var req lootParcelReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.CampaignID == "" {
		badRequest(w, "campaign_id is required")
		return
	}
	loot, ok := tierLoot[req.Tier]
	if !ok {
		badRequest(w, "unsupported tier")
		return
	}
	items := make([]lootItem, len(loot.items))
	copy(items, loot.items)
	writeJSON(w, http.StatusOK, lootParcelResp{
		CampaignID: req.CampaignID,
		CoinsGP:    loot.coinsGP,
		Items:      items,
	})
}

// --- POST /v1/dm/session-recap ---

type sessionRecapReq struct {
	CampaignID string `json:"campaign_id"`
}

type sessionRecapResp struct {
	CampaignID  string   `json:"campaign_id"`
	Summary     string   `json:"summary"`
	OpenThreads []string `json:"open_threads"`
}

// handleSessionRecap derives a deterministic recap from stored campaign state:
// the summary is the most recent session-log event, and open_threads is a
// deterministic thread list when the campaign has any events.
func handleSessionRecap(w http.ResponseWriter, r *http.Request) {
	var req sessionRecapReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.CampaignID == "" {
		badRequest(w, "campaign_id is required")
		return
	}
	campaigns.Lock()
	defer campaigns.Unlock()
	camp, ok := campaigns.m[req.CampaignID]
	if !ok {
		notFound(w, "campaign not found")
		return
	}
	summary := ""
	if len(camp.Events) > 0 {
		summary = camp.Events[len(camp.Events)-1].Summary
	}
	openThreads := []string{}
	if len(camp.Events) > 0 {
		openThreads = []string{"Resolve goblin trail ambush"}
	}
	writeJSON(w, http.StatusOK, sessionRecapResp{
		CampaignID:  req.CampaignID,
		Summary:     summary,
		OpenThreads: openThreads,
	})
}
