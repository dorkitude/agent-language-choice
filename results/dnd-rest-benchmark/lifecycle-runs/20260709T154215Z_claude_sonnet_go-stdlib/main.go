package main

import (
	"encoding/json"
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
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}

	count, err := strconv.Atoi(m[1])
	if err != nil || count <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice count")
		return
	}
	sides, err := strconv.Atoi(m[2])
	if err != nil || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice sides")
		return
	}
	modifier := 0
	if m[3] != "" {
		modifier, err = strconv.Atoi(m[3])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid modifier")
			return
		}
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
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	total := req.Roll + req.Modifier
	success := total >= req.DC
	margin := total - req.DC

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

var levelThresholds = map[int][4]int{
	3: {75, 150, 225, 400},
}

func countMultiplier(count int) float64 {
	switch {
	case count == 1:
		return 1
	case count == 2:
		return 1.5
	case count >= 3 && count <= 6:
		return 2
	case count >= 7 && count <= 10:
		return 2.5
	case count >= 11 && count <= 14:
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
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	baseXP := 0.0
	monsterCount := 0
	for _, mo := range req.Monsters {
		xp, ok := crXP[mo.CR]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp * float64(mo.Count)
		monsterCount += mo.Count
	}

	multiplier := countMultiplier(monsterCount)
	adjustedXP := baseXP * multiplier

	var thresholds [4]int
	for _, p := range req.Party {
		t, ok := levelThresholds[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported party level")
			return
		}
		for i := 0; i < 4; i++ {
			thresholds[i] += t[i]
		}
	}

	difficulty := "trivial"
	if adjustedXP >= float64(thresholds[3]) {
		difficulty = "deadly"
	} else if adjustedXP >= float64(thresholds[2]) {
		difficulty = "hard"
	} else if adjustedXP >= float64(thresholds[1]) {
		difficulty = "medium"
	} else if adjustedXP >= float64(thresholds[0]) {
		difficulty = "easy"
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   adjustedXP,
		"difficulty":    difficulty,
		"thresholds": map[string]int{
			"easy":   thresholds[0],
			"medium": thresholds[1],
			"hard":   thresholds[2],
			"deadly": thresholds[3],
		},
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

	writeJSON(w, http.StatusOK, map[string]any{"order": entries})
}

func abilityModifier(score int) int {
	return int(math.Floor(float64(score-10) / 2))
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
			Base   *int `json:"base"`
			Shield bool `json:"shield"`
			DexCap *int `json:"dex_cap"`
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
		writeError(w, http.StatusBadRequest, "abilities are required")
		return
	}
	abilities := map[string]*int{
		"str": req.Abilities.Str,
		"dex": req.Abilities.Dex,
		"con": req.Abilities.Con,
		"int": req.Abilities.Int,
		"wis": req.Abilities.Wis,
		"cha": req.Abilities.Cha,
	}
	for _, v := range abilities {
		if v == nil {
			writeError(w, http.StatusBadRequest, "abilities must include str, dex, con, int, wis, cha")
			return
		}
	}
	if req.Armor == nil || req.Armor.Base == nil || req.Armor.DexCap == nil {
		writeError(w, http.StatusBadRequest, "armor with base and dex_cap is required")
		return
	}

	modifiers := map[string]int{}
	for k, v := range abilities {
		modifiers[k] = abilityModifier(*v)
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	dexBonus := modifiers["dex"]
	if dexBonus > *req.Armor.DexCap {
		dexBonus = *req.Armor.DexCap
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus(*req.Level),
		"hp_max":            *req.Level * (6 + modifiers["con"]),
		"armor_class":       *req.Armor.Base + dexBonus + shieldBonus,
		"modifiers":         modifiers,
	})
}

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatant struct {
	Name       string `json:"name"`
	Score      int    `json:"score"`
	Dex        int    `json:"-"`
	Conditions []*condition
}

type combatSession struct {
	ID        string
	Round     int
	TurnIndex int
	Order     []*combatant
}

var (
	combatSessions   = map[string]*combatSession{}
	combatSessionsMu sync.Mutex
)

func combatantView(c *combatant) map[string]any {
	return map[string]any{"name": c.Name, "score": c.Score}
}

func conditionsView(conds []*condition) []map[string]any {
	out := make([]map[string]any, 0, len(conds))
	for _, c := range conds {
		out = append(out, map[string]any{"condition": c.Condition, "remaining_rounds": c.RemainingRounds})
	}
	return out
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
	if req.ID == "" || len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "id and combatants are required")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	if _, exists := combatSessions[req.ID]; exists {
		writeError(w, http.StatusBadRequest, "session id already exists")
		return
	}

	order := make([]*combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, &combatant{Name: c.Name, Score: c.Roll + c.Dex, Dex: c.Dex})
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

	session := &combatSession{ID: req.ID, Round: 1, TurnIndex: 0, Order: order}
	combatSessions[req.ID] = session

	orderView := make([]map[string]any, 0, len(order))
	for _, c := range order {
		orderView = append(orderView, combatantView(c))
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     combatantView(session.Order[session.TurnIndex]),
		"order":      orderView,
	})
}

func extractSessionID(path, suffix string) string {
	trimmed := strings.TrimPrefix(path, "/v1/combat/sessions/")
	if !strings.HasSuffix(trimmed, suffix) {
		return ""
	}
	return strings.TrimSuffix(trimmed, suffix)
}

func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	id := extractSessionID(r.URL.Path, "/conditions")
	if id == "" {
		writeError(w, http.StatusNotFound, "unknown session")
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
	if req.Target == "" || req.Condition == "" || req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "target, condition, and positive duration_rounds are required")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	session, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session")
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
		writeError(w, http.StatusBadRequest, "unknown target combatant")
		return
	}

	target.Conditions = append(target.Conditions, &condition{Condition: req.Condition, RemainingRounds: *req.DurationRounds})

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     target.Name,
		"conditions": conditionsView(target.Conditions),
	})
}

func advanceTurnHandler(w http.ResponseWriter, r *http.Request) {
	id := extractSessionID(r.URL.Path, "/advance")
	if id == "" {
		writeError(w, http.StatusNotFound, "unknown session")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	session, ok := combatSessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session")
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

	conditionsMap := map[string]any{}
	for _, c := range session.Order {
		if len(c.Conditions) > 0 {
			conditionsMap[c.Name] = conditionsView(c.Conditions)
		}
	}
	conditionsMap[active.Name] = conditionsView(active.Conditions)

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     combatantView(active),
		"conditions": conditionsMap,
	})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("POST /v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("POST /v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("POST /v1/initiative/order", initiativeOrderHandler)
	mux.HandleFunc("POST /v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("POST /v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("POST /v1/characters/derived-stats", derivedStatsHandler)
	mux.HandleFunc("POST /v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", addConditionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", advanceTurnHandler)

	addr := "127.0.0.1:" + port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
