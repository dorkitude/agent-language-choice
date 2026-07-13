package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"sync"
)

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func badRequest(w http.ResponseWriter) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request"})
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
		badRequest(w)
		return
	}
	m := diceRe.FindStringSubmatch(req.Expression)
	if m == nil {
		badRequest(w)
		return
	}
	count, err1 := strconv.Atoi(m[1])
	sides, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil || count <= 0 || sides <= 0 {
		badRequest(w)
		return
	}
	modifier := 0
	if m[3] != "" {
		modifier, _ = strconv.Atoi(m[3])
	}
	min := count + modifier
	max := count*sides + modifier
	average := float64(count)*(float64(sides)+1)/2 + float64(modifier)
	writeJSON(w, http.StatusOK, map[string]interface{}{
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
		badRequest(w)
		return
	}
	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"total":   total,
		"success": total >= req.DC,
		"margin":  total - req.DC,
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

var levelThresholds = map[int][4]int{
	3: {75, 150, 225, 400},
}

func encounterMultiplier(count int) float64 {
	switch {
	case count <= 1:
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
		badRequest(w)
		return
	}
	baseXP := 0
	monsterCount := 0
	for _, mon := range req.Monsters {
		xp, ok := crXP[mon.CR]
		if !ok {
			badRequest(w)
			return
		}
		baseXP += xp * mon.Count
		monsterCount += mon.Count
	}
	multiplier := encounterMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * multiplier

	var easy, medium, hard, deadly int
	for _, p := range req.Party {
		t, ok := levelThresholds[p.Level]
		if !ok {
			badRequest(w)
			return
		}
		easy += t[0]
		medium += t[1]
		hard += t[2]
		deadly += t[3]
	}

	difficulty := "trivial"
	adj := adjustedXP
	if adj >= float64(deadly) {
		difficulty = "deadly"
	} else if adj >= float64(hard) {
		difficulty = "hard"
	} else if adj >= float64(medium) {
		difficulty = "medium"
	} else if adj >= float64(easy) {
		difficulty = "easy"
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
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
		badRequest(w)
		return
	}
	type entry struct {
		Name  string
		Dex   int
		Score int
	}
	entries := make([]entry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		entries = append(entries, entry{Name: c.Name, Dex: c.Dex, Score: c.Roll + c.Dex})
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
	order := make([]map[string]interface{}, 0, len(entries))
	for _, e := range entries {
		order = append(order, map[string]interface{}{
			"name":  e.Name,
			"score": e.Score,
		})
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"order": order})
}

func abilityModifier(score int) int {
	diff := score - 10
	if diff >= 0 {
		return diff / 2
	}
	return -((-diff + 1) / 2)
}

func proficiencyBonus(level int) int {
	return 2 + (level-1)/4
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score *int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Score == nil {
		badRequest(w)
		return
	}
	if *req.Score < 1 || *req.Score > 30 {
		badRequest(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"score":    *req.Score,
		"modifier": abilityModifier(*req.Score),
	})
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Level == nil {
		badRequest(w)
		return
	}
	if *req.Level < 1 || *req.Level > 20 {
		badRequest(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
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
		badRequest(w)
		return
	}
	if req.Level == nil || req.Abilities == nil || req.Armor == nil {
		badRequest(w)
		return
	}
	if *req.Level < 1 || *req.Level > 20 {
		badRequest(w)
		return
	}
	a := req.Abilities
	if a.Str == nil || a.Dex == nil || a.Con == nil || a.Int == nil || a.Wis == nil || a.Cha == nil {
		badRequest(w)
		return
	}
	scores := []int{*a.Str, *a.Dex, *a.Con, *a.Int, *a.Wis, *a.Cha}
	for _, s := range scores {
		if s < 1 || s > 30 {
			badRequest(w)
			return
		}
	}
	if req.Armor.Base == nil || req.Armor.DexCap == nil {
		badRequest(w)
		return
	}

	conMod := abilityModifier(*a.Con)
	dexMod := abilityModifier(*a.Dex)
	prof := proficiencyBonus(*req.Level)
	hpMax := *req.Level * (6 + conMod)

	dexBonus := dexMod
	if dexBonus > *req.Armor.DexCap {
		dexBonus = *req.Armor.DexCap
	}
	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := *req.Armor.Base + dexBonus + shieldBonus

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"level":             *req.Level,
		"proficiency_bonus": prof,
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers": map[string]int{
			"str": abilityModifier(*a.Str),
			"dex": dexMod,
			"con": conMod,
			"int": abilityModifier(*a.Int),
			"wis": abilityModifier(*a.Wis),
			"cha": abilityModifier(*a.Cha),
		},
	})
}

// --- Combat sessions (Maintenance Stage 2) ---

type condition struct {
	Condition string `json:"condition"`
	Remaining int    `json:"remaining_rounds"`
}

type combatant struct {
	Name       string
	Dex        int
	Score      int
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

func combatantView(c *combatant) map[string]interface{} {
	return map[string]interface{}{"name": c.Name, "score": c.Score}
}

func orderView(s *combatSession) []map[string]interface{} {
	out := make([]map[string]interface{}, 0, len(s.Order))
	for _, c := range s.Order {
		out = append(out, combatantView(c))
	}
	return out
}

func conditionsView(s *combatSession) map[string]interface{} {
	out := map[string]interface{}{}
	for _, c := range s.Order {
		list := make([]map[string]interface{}, 0, len(c.Conditions))
		for _, cond := range c.Conditions {
			list = append(list, map[string]interface{}{
				"condition":        cond.Condition,
				"remaining_rounds": cond.Remaining,
			})
		}
		out[c.Name] = list
	}
	return out
}

func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.ID == "" || len(req.Combatants) == 0 {
		badRequest(w)
		return
	}
	combatants := make([]*combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			badRequest(w)
			return
		}
		combatants = append(combatants, &combatant{
			Name:  c.Name,
			Dex:   c.Dex,
			Score: c.Roll + c.Dex,
		})
	}
	sort.SliceStable(combatants, func(i, j int) bool {
		if combatants[i].Score != combatants[j].Score {
			return combatants[i].Score > combatants[j].Score
		}
		if combatants[i].Dex != combatants[j].Dex {
			return combatants[i].Dex > combatants[j].Dex
		}
		return combatants[i].Name < combatants[j].Name
	})

	combatMu.Lock()
	if _, exists := combatSessions[req.ID]; exists {
		combatMu.Unlock()
		badRequest(w)
		return
	}
	s := &combatSession{ID: req.ID, Round: 1, TurnIndex: 0, Order: combatants}
	combatSessions[req.ID] = s
	resp := map[string]interface{}{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     combatantView(s.Order[s.TurnIndex]),
		"order":      orderView(s),
	}
	combatMu.Unlock()
	writeJSON(w, http.StatusOK, resp)
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		Target    string `json:"target"`
		Condition string `json:"condition"`
		Duration  *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}

	combatMu.Lock()
	defer combatMu.Unlock()
	s, ok := combatSessions[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}
	if req.Target == "" || req.Condition == "" || req.Duration == nil || *req.Duration <= 0 {
		badRequest(w)
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
		badRequest(w)
		return
	}
	target.Conditions = append(target.Conditions, condition{
		Condition: req.Condition,
		Remaining: *req.Duration,
	})
	list := make([]map[string]interface{}, 0, len(target.Conditions))
	for _, cond := range target.Conditions {
		list = append(list, map[string]interface{}{
			"condition":        cond.Condition,
			"remaining_rounds": cond.Remaining,
		})
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"target":     target.Name,
		"conditions": list,
	})
}

func handleAdvanceTurn(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	combatMu.Lock()
	defer combatMu.Unlock()
	s, ok := combatSessions[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}
	s.TurnIndex++
	if s.TurnIndex >= len(s.Order) {
		s.TurnIndex = 0
		s.Round++
	}
	active := s.Order[s.TurnIndex]
	kept := active.Conditions[:0]
	for _, cond := range active.Conditions {
		cond.Remaining--
		if cond.Remaining > 0 {
			kept = append(kept, cond)
		}
	}
	active.Conditions = kept
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     combatantView(active),
		"conditions": conditionsView(s),
	})
}

// --- Users and password login (Maintenance Stage 3) ---

// Password hashing is isolated behind these helpers. Go's standard library has
// no built-in adaptive password hash (bcrypt/argon2 live in golang.org/x/crypto,
// which this benchmark forbids), so we use a salted SHA-256. In production,
// swap hashPassword/verifyPassword for a memory-hard KDF such as bcrypt.
func hashPassword(password string) string {
	salt := make([]byte, 16)
	rand.Read(salt)
	sum := sha256.Sum256(append(salt, []byte(password)...))
	return hex.EncodeToString(salt) + ":" + hex.EncodeToString(sum[:])
}

func verifyPassword(stored, password string) bool {
	parts := regexp.MustCompile(`:`).Split(stored, 2)
	if len(parts) != 2 {
		return false
	}
	salt, err := hex.DecodeString(parts[0])
	if err != nil {
		return false
	}
	sum := sha256.Sum256(append(salt, []byte(password)...))
	return subtle.ConstantTimeCompare([]byte(hex.EncodeToString(sum[:])), []byte(parts[1])) == 1
}

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

type user struct {
	Username string
	Role     string
	Hash     string
}

var (
	usersMu sync.Mutex
	users   = map[string]*user{}
)

func handleRegister(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if !usernameRe.MatchString(req.Username) {
		badRequest(w)
		return
	}
	if len(req.Password) < 8 {
		badRequest(w)
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		badRequest(w)
		return
	}
	usersMu.Lock()
	defer usersMu.Unlock()
	if _, exists := users[req.Username]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "username already exists"})
		return
	}
	users[req.Username] = &user{
		Username: req.Username,
		Role:     req.Role,
		Hash:     hashPassword(req.Password),
	}
	writeJSON(w, http.StatusCreated, map[string]interface{}{
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
		badRequest(w)
		return
	}
	usersMu.Lock()
	u, ok := users[req.Username]
	usersMu.Unlock()
	if !ok || !verifyPassword(u.Hash, req.Password) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid credentials"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"username": u.Username,
		"token":    "session-" + u.Username,
	})
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handleHealth)
	mux.HandleFunc("POST /v1/dice/stats", handleDiceStats)
	mux.HandleFunc("POST /v1/checks/ability", handleAbilityCheck)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", handleAdjustedXP)
	mux.HandleFunc("POST /v1/initiative/order", handleInitiative)
	mux.HandleFunc("POST /v1/characters/ability-modifier", handleAbilityModifier)
	mux.HandleFunc("POST /v1/characters/proficiency", handleProficiency)
	mux.HandleFunc("POST /v1/characters/derived-stats", handleDerivedStats)
	mux.HandleFunc("POST /v1/combat/sessions", handleCreateSession)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", handleAdvanceTurn)
	mux.HandleFunc("POST /v1/auth/register", handleRegister)
	mux.HandleFunc("POST /v1/auth/login", handleLogin)
	mux.HandleFunc("POST /v1/compendium/monsters", handleCreateMonster)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", handleReadMonster)
	mux.HandleFunc("POST /v1/compendium/items", handleCreateItem)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", handleReadItem)
	mux.HandleFunc("GET /v1/storage/status", handleStorageStatus)
	mux.HandleFunc("POST /v1/storage/reset", handleStorageReset)
	mux.HandleFunc("POST /v1/campaigns", handleCreateCampaign)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", handleAddCharacter)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", handleAddEvent)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", handleReadCampaignState)
	mux.HandleFunc("POST /v1/phb/spell-slots", handleSpellSlots)
	mux.HandleFunc("POST /v1/phb/rests/long", handleLongRest)
	mux.HandleFunc("POST /v1/phb/equipment-load", handleEquipmentLoad)
	mux.HandleFunc("POST /v1/dm/encounter-builder", handleEncounterBuilder)
	mux.HandleFunc("POST /v1/dm/loot-parcel", handleLootParcel)
	mux.HandleFunc("POST /v1/dm/session-recap", handleSessionRecap)

	if err := ensureDB(); err != nil {
		panic(err)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	if err := http.ListenAndServe("127.0.0.1:"+port, mux); err != nil {
		panic(err)
	}
}
