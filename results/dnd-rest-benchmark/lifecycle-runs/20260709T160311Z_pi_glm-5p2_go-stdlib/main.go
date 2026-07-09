package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"sync"
)

// dice expression: <count>d<sides>[+<modifier>|-<modifier>]
// count and sides must be positive (no leading zeros); modifier is optional.
var diceRe = regexp.MustCompile(`^([1-9][0-9]*)d([1-9][0-9]*)(?:([+-])([0-9]+))?$`)

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

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)
	mux.HandleFunc("/v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("/v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("/v1/characters/derived-stats", derivedStatsHandler)
	mux.HandleFunc("POST /v1/combat/sessions", createSessionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", addConditionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", advanceSessionHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Fatal(http.ListenAndServe("127.0.0.1:"+port, mux))
}

// --- helpers ---

func writeJSON(w http.ResponseWriter, status int, v any) {
	b, _ := json.Marshal(v)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

func readJSON(r *http.Request, v any) error {
	defer r.Body.Close()
	return json.NewDecoder(r.Body).Decode(v)
}

func badRequest(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
}

// --- handlers ---

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

type diceStatsResp struct {
	DiceCount int `json:"dice_count"`
	Sides     int `json:"sides"`
	Modifier  int `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	m := diceRe.FindStringSubmatch(req.Expression)
	if m == nil {
		badRequest(w, "invalid expression")
		return
	}
	count, err1 := strconv.Atoi(m[1])
	sides, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil || count <= 0 || sides <= 0 {
		badRequest(w, "invalid expression")
		return
	}
	modifier := 0
	if m[3] != "" {
		val, err := strconv.Atoi(m[4])
		if err != nil {
			badRequest(w, "invalid expression")
			return
		}
		if m[3] == "-" {
			modifier = -val
		} else {
			modifier = val
		}
	}
	min := count + modifier
	max := count*sides + modifier
	average := (float64(min) + float64(max)) / 2
	writeJSON(w, http.StatusOK, diceStatsResp{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       min,
		Max:       max,
		Average:   average,
	})
}

type abilityResp struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := readJSON(r, &req); err != nil {
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

func encounterMultiplier(n int) float64 {
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

type adjustedXPResp struct {
	BaseXP       int            `json:"base_xp"`
	MonsterCount int            `json:"monster_count"`
	Multiplier   float64        `json:"multiplier"`
	AdjustedXP   float64        `json:"adjusted_xp"`
	Difficulty   string         `json:"difficulty"`
	Thresholds   map[string]int `json:"thresholds"`
}

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Party    []struct{ Level int `json:"level"` } `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, mon := range req.Monsters {
		xp, ok := crXP[mon.CR]
		if !ok {
			badRequest(w, "unknown challenge rating")
			return
		}
		baseXP += xp * mon.Count
		monsterCount += mon.Count
	}

	mult := encounterMultiplier(monsterCount)
	adjusted := float64(baseXP) * mult

	// Level-3 encounter thresholds (summed across party members).
	easy, medium, hard, deadly := 0, 0, 0, 0
	for _, p := range req.Party {
		if p.Level == 3 {
			easy += 75
			medium += 150
			hard += 225
			deadly += 400
		}
	}

	difficulty := "trivial"
	switch {
	case adjusted >= float64(deadly):
		difficulty = "deadly"
	case adjusted >= float64(hard):
		difficulty = "hard"
	case adjusted >= float64(medium):
		difficulty = "medium"
	case adjusted >= float64(easy):
		difficulty = "easy"
	}

	writeJSON(w, http.StatusOK, adjustedXPResp{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   mult,
		AdjustedXP:   adjusted,
		Difficulty:   difficulty,
		Thresholds: map[string]int{
			"easy":   easy,
			"medium": medium,
			"hard":   hard,
			"deadly": deadly,
		},
	})
}

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeResp struct {
	Order []initiativeEntry `json:"order"`
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	type c struct {
		name  string
		dex   int
		score int
	}
	cs := make([]c, len(req.Combatants))
	for i, cb := range req.Combatants {
		cs[i] = c{name: cb.Name, dex: cb.Dex, score: cb.Roll + cb.Dex}
	}
	sort.SliceStable(cs, func(i, j int) bool {
		if cs[i].score != cs[j].score {
			return cs[i].score > cs[j].score
		}
		if cs[i].dex != cs[j].dex {
			return cs[i].dex > cs[j].dex
		}
		return cs[i].name < cs[j].name
	})

	order := make([]initiativeEntry, len(cs))
	for i, cb := range cs {
		order[i] = initiativeEntry{Name: cb.name, Score: cb.score}
	}
	writeJSON(w, http.StatusOK, initiativeResp{Order: order})
}

// --- character handlers ---

// floorDiv computes floor(a/b) for integers, correcting Go's
// truncation-toward-zero division for negative dividends.
func floorDiv(a, b int) int {
	q := a / b
	if a%b != 0 && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// abilityModifier implements modifier = floor((score - 10) / 2).
func abilityModifier(score int) int {
	return floorDiv(score-10, 2)
}

// proficiencyBonus returns the PB for a valid level (1-20).
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

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score int `json:"score"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Score < 1 || req.Score > 30 {
		badRequest(w, "score must be an integer from 1 to 30")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{
		"score":    req.Score,
		"modifier": abilityModifier(req.Score),
	})
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level int `json:"level"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be an integer from 1 to 20")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{
		"level":             req.Level,
		"proficiency_bonus": proficiencyBonus(req.Level),
	})
}

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level     int `json:"level"`
		Abilities struct {
			Str int `json:"str"`
			Dex int `json:"dex"`
			Con int `json:"con"`
			Int int `json:"int"`
			Wis int `json:"wis"`
			Cha int `json:"cha"`
		} `json:"abilities"`
		Armor struct {
			Base   int  `json:"base"`
			Shield bool `json:"shield"`
			DexCap int  `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be an integer from 1 to 20")
		return
	}
	for _, s := range []int{req.Abilities.Str, req.Abilities.Dex, req.Abilities.Con,
		req.Abilities.Int, req.Abilities.Wis, req.Abilities.Cha} {
		if s < 1 || s > 30 {
			badRequest(w, "ability score must be an integer from 1 to 30")
			return
		}
	}

	mods := map[string]int{
		"str": abilityModifier(req.Abilities.Str),
		"dex": abilityModifier(req.Abilities.Dex),
		"con": abilityModifier(req.Abilities.Con),
		"int": abilityModifier(req.Abilities.Int),
		"wis": abilityModifier(req.Abilities.Wis),
		"cha": abilityModifier(req.Abilities.Cha),
	}

	hpMax := req.Level * (6 + mods["con"])

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := req.Armor.Base + min(mods["dex"], req.Armor.DexCap) + shieldBonus

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             req.Level,
		"proficiency_bonus": proficiencyBonus(req.Level),
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers":         mods,
	})
}

// --- combat session handlers ---

// combatCondition is a timed condition attached to a combatant.
type combatCondition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// combatant is an entry in a session's initiative order.
type combatant struct {
	Name       string
	Score      int
	Conditions []combatCondition
}

// sessionState holds the in-memory state for one combat session.
type sessionState struct {
	ID        string
	Round     int
	TurnIndex int
	Order     []*combatant
}

var (
	sessionsMu sync.Mutex
	sessions   = map[string]*sessionState{}
)

// orderEntry is the public {name, score} shape used in responses.
type orderEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

// activeEntry returns the combatant currently whose turn it is.
func activeEntry(s *sessionState) orderEntry {
	if s.TurnIndex >= 0 && s.TurnIndex < len(s.Order) {
		c := s.Order[s.TurnIndex]
		return orderEntry{Name: c.Name, Score: c.Score}
	}
	return orderEntry{}
}

// orderEntries returns the public initiative order.
func orderEntries(s *sessionState) []orderEntry {
	out := make([]orderEntry, len(s.Order))
	for i, c := range s.Order {
		out[i] = orderEntry{Name: c.Name, Score: c.Score}
	}
	return out
}

// findCombatant returns the combatant with the given name, or nil.
func (s *sessionState) findCombatant(name string) *combatant {
	for _, c := range s.Order {
		if c.Name == name {
			return c
		}
	}
	return nil
}

// conditionMap builds the {combatant: [conditions]} view. A combatant is
// included once they have ever been targeted by a condition: their Conditions
// slice is kept non-nil even after every condition expires, so an expired
// combatant still appears with an empty array. Combatants who never had a
// condition (nil slice) are omitted.
func conditionMap(s *sessionState) map[string][]combatCondition {
	m := map[string][]combatCondition{}
	for _, c := range s.Order {
		if c.Conditions != nil {
			cp := make([]combatCondition, len(c.Conditions))
			copy(cp, c.Conditions)
			m[c.Name] = cp
		}
	}
	return m
}

func createSessionHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.ID == "" {
		badRequest(w, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		badRequest(w, "combatants must not be empty")
		return
	}

	type tmp struct {
		name  string
		dex   int
		score int
	}
	cs := make([]tmp, len(req.Combatants))
	for i, cb := range req.Combatants {
		cs[i] = tmp{name: cb.Name, dex: cb.Dex, score: cb.Roll + cb.Dex}
	}
	sort.SliceStable(cs, func(i, j int) bool {
		if cs[i].score != cs[j].score {
			return cs[i].score > cs[j].score
		}
		if cs[i].dex != cs[j].dex {
			return cs[i].dex > cs[j].dex
		}
		return cs[i].name < cs[j].name
	})

	order := make([]*combatant, len(cs))
	for i, c := range cs {
		order[i] = &combatant{Name: c.name, Score: c.score}
	}
	s := &sessionState{
		ID:        req.ID,
		Round:     1,
		TurnIndex: 0,
		Order:     order,
	}

	sessionsMu.Lock()
	sessions[req.ID] = s
	sessionsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     activeEntry(s),
		"order":      orderEntries(s),
	})
}

func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sessionsMu.Lock()
	s, ok := sessions[id]
	sessionsMu.Unlock()
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}

	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if err := readJSON(r, &req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.DurationRounds <= 0 {
		badRequest(w, "duration_rounds must be a positive integer")
		return
	}

	sessionsMu.Lock()
	target := s.findCombatant(req.Target)
	if target == nil {
		sessionsMu.Unlock()
		badRequest(w, "unknown target")
		return
	}
	target.Conditions = append(target.Conditions, combatCondition{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})
	conds := make([]combatCondition, len(target.Conditions))
	copy(conds, target.Conditions)
	sessionsMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     req.Target,
		"conditions": conds,
	})
}

func advanceSessionHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sessionsMu.Lock()
	s, ok := sessions[id]
	sessionsMu.Unlock()
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}

	sessionsMu.Lock()
	n := len(s.Order)
	if n == 0 {
		sessionsMu.Unlock()
		badRequest(w, "session has no combatants")
		return
	}
	wrapped := s.TurnIndex == n-1
	s.TurnIndex = (s.TurnIndex + 1) % n
	if wrapped {
		s.Round++
	}
	// At the start of the new active combatant's turn, decrement their
	// conditions and drop any that have expired. If this combatant had any
	// conditions before this turn, keep the slice non-nil even when all of
	// them expire, so the combatant still shows up in the conditions view as
	// an empty array rather than vanishing.
	active := s.Order[s.TurnIndex]
	hadConditions := active.Conditions != nil
	var kept []combatCondition
	for _, c := range active.Conditions {
		c.RemainingRounds--
		if c.RemainingRounds > 0 {
			kept = append(kept, c)
		}
	}
	if hadConditions && kept == nil {
		kept = []combatCondition{}
	}
	active.Conditions = kept
	resp := map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     activeEntry(s),
		"conditions": conditionMap(s),
	}
	sessionsMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}
