package main

import (
	"encoding/json"
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

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

var diceRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	m := diceRe.FindStringSubmatch(req.Expression)
	if m == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid expression"})
		return
	}
	count, _ := strconv.Atoi(m[1])
	sides, _ := strconv.Atoi(m[2])
	modifier := 0
	if m[3] != "" {
		modifier, _ = strconv.Atoi(m[3])
	}
	if count <= 0 || sides <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid expression"})
		return
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

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, map[string]any{
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

var levelThresholds = map[int]map[string]int{
	3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
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
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "unsupported cr"})
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}
	multiplier := countMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * multiplier

	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, p := range req.Party {
		t, ok := levelThresholds[p.Level]
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "unsupported level"})
			return
		}
		thresholds["easy"] += t["easy"]
		thresholds["medium"] += t["medium"]
		thresholds["hard"] += t["hard"]
		thresholds["deadly"] += t["deadly"]
	}

	difficulty := "trivial"
	adj := int(adjustedXP)
	if adj >= thresholds["deadly"] {
		difficulty = "deadly"
	} else if adj >= thresholds["hard"] {
		difficulty = "hard"
	} else if adj >= thresholds["medium"] {
		difficulty = "medium"
	} else if adj >= thresholds["easy"] {
		difficulty = "easy"
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

func initiativeHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
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
	order := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		order = append(order, map[string]any{"name": e.Name, "score": e.Score})
	}
	writeJSON(w, http.StatusOK, map[string]any{"order": order})
}

func abilityModifier(score int) int {
	diff := score - 10
	if diff >= 0 {
		return diff / 2
	}
	return -((-diff + 1) / 2)
}

func proficiencyBonus(level int) int {
	return (level-1)/4 + 2
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score *int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Score == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	score := *req.Score
	if score < 1 || score > 30 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "score out of range"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"score":    score,
		"modifier": abilityModifier(score),
	})
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Level == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	level := *req.Level
	if level < 1 || level > 20 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "level out of range"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"level":             level,
		"proficiency_bonus": proficiencyBonus(level),
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
			Base   *int `json:"base"`
			Shield bool `json:"shield"`
			DexCap *int `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	if req.Level == nil || req.Abilities == nil || req.Armor == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	level := *req.Level
	if level < 1 || level > 20 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "level out of range"})
		return
	}
	a := req.Abilities
	if a.Str == nil || a.Dex == nil || a.Con == nil || a.Int == nil || a.Wis == nil || a.Cha == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid abilities"})
		return
	}
	scores := map[string]int{
		"str": *a.Str, "dex": *a.Dex, "con": *a.Con,
		"int": *a.Int, "wis": *a.Wis, "cha": *a.Cha,
	}
	mods := map[string]int{}
	for k, v := range scores {
		if v < 1 || v > 30 {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ability score out of range"})
			return
		}
		mods[k] = abilityModifier(v)
	}
	if req.Armor.Base == nil || req.Armor.DexCap == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid armor"})
		return
	}
	prof := proficiencyBonus(level)
	hpMax := level * (6 + mods["con"])
	dexMod := mods["dex"]
	if *req.Armor.DexCap < dexMod {
		dexMod = *req.Armor.DexCap
	}
	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := *req.Armor.Base + dexMod + shieldBonus
	writeJSON(w, http.StatusOK, map[string]any{
		"level":             level,
		"proficiency_bonus": prof,
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers":         mods,
	})
}

type condition struct {
	Condition string
	Remaining int
}

type combatant struct {
	Name         string
	Dex          int
	Score        int
	Conditions   []condition
	HadCondition bool
}

type session struct {
	ID        string
	Round     int
	TurnIndex int
	Order     []*combatant
}

type combatStore struct {
	mu       sync.Mutex
	sessions map[string]*session
}

var combat = &combatStore{sessions: map[string]*session{}}

func combatantSummary(c *combatant) map[string]any {
	return map[string]any{"name": c.Name, "score": c.Score}
}

func conditionsMap(s *session) map[string]any {
	out := map[string]any{}
	for _, c := range s.Order {
		if len(c.Conditions) == 0 && !c.HadCondition {
			continue
		}
		list := make([]map[string]any, 0, len(c.Conditions))
		for _, cond := range c.Conditions {
			list = append(list, map[string]any{
				"condition":       cond.Condition,
				"remaining_rounds": cond.Remaining,
			})
		}
		out[c.Name] = list
	}
	return out
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
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	if req.ID == "" || len(req.Combatants) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	order := make([]*combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid combatant"})
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

	combat.mu.Lock()
	if _, exists := combat.sessions[req.ID]; exists {
		combat.mu.Unlock()
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "session id already exists"})
		return
	}
	s := &session{ID: req.ID, Round: 1, TurnIndex: 0, Order: order}
	combat.sessions[req.ID] = s
	combat.mu.Unlock()

	orderOut := make([]map[string]any, 0, len(s.Order))
	for _, c := range s.Order {
		orderOut = append(orderOut, combatantSummary(c))
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     combatantSummary(s.Order[s.TurnIndex]),
		"order":      orderOut,
	})
}

func addConditionHandler(w http.ResponseWriter, r *http.Request, id string) {
	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}
	if req.Condition == "" || req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid request"})
		return
	}

	combat.mu.Lock()
	defer combat.mu.Unlock()
	s, ok := combat.sessions[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "unknown session"})
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
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "unknown target"})
		return
	}
	target.Conditions = append(target.Conditions, condition{Condition: req.Condition, Remaining: *req.DurationRounds})
	target.HadCondition = true

	list := make([]map[string]any, 0, len(target.Conditions))
	for _, cond := range target.Conditions {
		list = append(list, map[string]any{
			"condition":       cond.Condition,
			"remaining_rounds": cond.Remaining,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"target":     target.Name,
		"conditions": list,
	})
}

func advanceHandler(w http.ResponseWriter, r *http.Request, id string) {
	combat.mu.Lock()
	defer combat.mu.Unlock()
	s, ok := combat.sessions[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "unknown session"})
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

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     combatantSummary(active),
		"conditions": conditionsMap(s),
	})
}

var sessionPathRe = regexp.MustCompile(`^/v1/combat/sessions/([^/]+)/(conditions|advance)$`)

func combatSessionRouter(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		return
	}
	m := sessionPathRe.FindStringSubmatch(r.URL.Path)
	if m == nil {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
		return
	}
	id := m[1]
	switch m[2] {
	case "conditions":
		addConditionHandler(w, r, id)
	case "advance":
		advanceHandler(w, r, id)
	}
}

func combatSessionsHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/v1/combat/sessions" || r.URL.Path == "/v1/combat/sessions/" {
		post(createSessionHandler)(w, r)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/v1/combat/sessions/") {
		combatSessionRouter(w, r)
		return
	}
	writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
}

func post(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
			return
		}
		h(w, r)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", post(diceStatsHandler))
	mux.HandleFunc("/v1/checks/ability", post(abilityCheckHandler))
	mux.HandleFunc("/v1/encounters/adjusted-xp", post(adjustedXPHandler))
	mux.HandleFunc("/v1/initiative/order", post(initiativeHandler))
	mux.HandleFunc("/v1/characters/ability-modifier", post(abilityModifierHandler))
	mux.HandleFunc("/v1/characters/proficiency", post(proficiencyHandler))
	mux.HandleFunc("/v1/characters/derived-stats", post(derivedStatsHandler))
	mux.HandleFunc("/v1/combat/sessions", combatSessionsHandler)
	mux.HandleFunc("/v1/combat/sessions/", combatSessionsHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	if err := http.ListenAndServe("127.0.0.1:"+port, mux); err != nil {
		panic(err)
	}
}
