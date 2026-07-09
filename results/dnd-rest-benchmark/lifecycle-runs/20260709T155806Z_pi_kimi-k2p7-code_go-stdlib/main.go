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

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
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
	mux.HandleFunc("POST /v1/combat/sessions", handleCreateSession)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", handleAdvance)

	log.Printf("listening on 127.0.0.1:%s", port)
	if err := http.ListenAndServe("127.0.0.1:"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func respond(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Printf("encode error: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	respond(w, http.StatusOK, map[string]bool{"ok": true})
}

var diceExpr = regexp.MustCompile(`^(\d+)d(\d+)(?:([+-])(\d+))?$`)

type diceRequest struct {
	Expression string `json:"expression"`
}

type diceResponse struct {
	DiceCount int     `json:"dice_count"`
	Sides     int     `json:"sides"`
	Modifier  int     `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

func handleDiceStats(w http.ResponseWriter, r *http.Request) {
	var req diceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}

	matches := diceExpr.FindStringSubmatch(strings.TrimSpace(req.Expression))
	if matches == nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid expression"})
		return
	}

	count, _ := strconv.Atoi(matches[1])
	sides, _ := strconv.Atoi(matches[2])
	modifier := 0
	if matches[3] != "" {
		mod, _ := strconv.Atoi(matches[4])
		if matches[3] == "-" {
			mod = -mod
		}
		modifier = mod
	}

	if count <= 0 || sides <= 0 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid expression"})
		return
	}

	min := count + modifier
	max := count*sides + modifier
	average := float64(min+max) / 2

	respond(w, http.StatusOK, diceResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       min,
		Max:       max,
		Average:   average,
	})
}

type abilityRequest struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

type abilityResponse struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

func handleAbilityCheck(w http.ResponseWriter, r *http.Request) {
	var req abilityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}

	total := req.Roll + req.Modifier
	respond(w, http.StatusOK, abilityResponse{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

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

var thresholdsByLevel = map[int]map[string]int{
	3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

type monsterGroup struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type partyMember struct {
	Level int `json:"level"`
}

type encounterRequest struct {
	Party    []partyMember  `json:"party"`
	Monsters []monsterGroup `json:"monsters"`
}

type encounterResponse struct {
	BaseXP      int            `json:"base_xp"`
	MonsterCount int           `json:"monster_count"`
	Multiplier  float64        `json:"multiplier"`
	AdjustedXP  int            `json:"adjusted_xp"`
	Difficulty  string         `json:"difficulty"`
	Thresholds map[string]int `json:"thresholds"`
}

func multiplierForCount(n int) float64 {
	switch {
	case n >= 15:
		return 4
	case n >= 11:
		return 3
	case n >= 7:
		return 2.5
	case n >= 3:
		return 2
	case n == 2:
		return 1.5
	default:
		return 1
	}
}

func handleAdjustedXP(w http.ResponseWriter, r *http.Request) {
	var req encounterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := xpByCR[m.CR]
		if !ok || m.Count <= 0 {
			respond(w, http.StatusBadRequest, map[string]string{"error": "invalid monster"})
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}

	if monsterCount == 0 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "no monsters"})
		return
	}

	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, p := range req.Party {
		th, ok := thresholdsByLevel[p.Level]
		if !ok {
			respond(w, http.StatusBadRequest, map[string]string{"error": "unsupported level"})
			return
		}
		for k, v := range th {
			thresholds[k] += v
		}
	}

	multiplier := multiplierForCount(monsterCount)
	adjustedXP := int(float64(baseXP) * multiplier)

	difficulty := "trivial"
	if adjustedXP >= thresholds["deadly"] {
		difficulty = "deadly"
	} else if adjustedXP >= thresholds["hard"] {
		difficulty = "hard"
	} else if adjustedXP >= thresholds["medium"] {
		difficulty = "medium"
	} else if adjustedXP >= thresholds["easy"] {
		difficulty = "easy"
	}

	respond(w, http.StatusOK, encounterResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty,
		Thresholds:   thresholds,
	})
}

type combatantInput struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

type scoredCombatant struct {
	Name  string
	Dex   int
	Score int
}

type initiativeRequest struct {
	Combatants []combatantInput `json:"combatants"`
}

type combatantOutput struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeResponse struct {
	Order []combatantOutput `json:"order"`
}

func handleInitiative(w http.ResponseWriter, r *http.Request) {
	var req initiativeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}

	scored := make([]scoredCombatant, len(req.Combatants))
	for i, c := range req.Combatants {
		scored[i] = scoredCombatant{Name: c.Name, Dex: c.Dex, Score: c.Roll + c.Dex}
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		if scored[i].Dex != scored[j].Dex {
			return scored[i].Dex > scored[j].Dex
		}
		return scored[i].Name < scored[j].Name
	})

	order := make([]combatantOutput, len(scored))
	for i, c := range scored {
		order[i] = combatantOutput{Name: c.Name, Score: c.Score}
	}

	respond(w, http.StatusOK, initiativeResponse{Order: order})
}

func abilityModifier(score int) int {
	return int(math.Floor(float64(score-10) / 2))
}

type abilityModifierRequest struct {
	Score int `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req abilityModifierRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if req.Score < 1 || req.Score > 30 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid score"})
		return
	}
	respond(w, http.StatusOK, abilityModifierResponse{
		Score:    req.Score,
		Modifier: abilityModifier(req.Score),
	})
}

type proficiencyRequest struct {
	Level int `json:"level"`
}

type proficiencyResponse struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
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

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req proficiencyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if req.Level < 1 || req.Level > 20 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid level"})
		return
	}
	respond(w, http.StatusOK, proficiencyResponse{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
	})
}

type abilities struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type armor struct {
	Base   int  `json:"base"`
	Shield bool `json:"shield"`
	DexCap int  `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     int       `json:"level"`
	Abilities abilities `json:"abilities"`
	Armor     armor     `json:"armor"`
}

type derivedStatsResponse struct {
	Level            int         `json:"level"`
	ProficiencyBonus int         `json:"proficiency_bonus"`
	HPMax            int         `json:"hp_max"`
	ArmorClass       int         `json:"armor_class"`
	Modifiers        map[string]int `json:"modifiers"`
}

func validateAbilityScore(score int) bool {
	return score >= 1 && score <= 30
}

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	var req derivedStatsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if req.Level < 1 || req.Level > 20 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid level"})
		return
	}
	if !validateAbilityScore(req.Abilities.Str) ||
		!validateAbilityScore(req.Abilities.Dex) ||
		!validateAbilityScore(req.Abilities.Con) ||
		!validateAbilityScore(req.Abilities.Int) ||
		!validateAbilityScore(req.Abilities.Wis) ||
		!validateAbilityScore(req.Abilities.Cha) {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid ability score"})
		return
	}

	modifiers := map[string]int{
		"str": abilityModifier(req.Abilities.Str),
		"dex": abilityModifier(req.Abilities.Dex),
		"con": abilityModifier(req.Abilities.Con),
		"int": abilityModifier(req.Abilities.Int),
		"wis": abilityModifier(req.Abilities.Wis),
		"cha": abilityModifier(req.Abilities.Cha),
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}

	dexMod := modifiers["dex"]
	if dexMod > req.Armor.DexCap {
		dexMod = req.Armor.DexCap
	}

	hpMax := req.Level * (6 + modifiers["con"])
	armorClass := req.Armor.Base + dexMod + shieldBonus

	respond(w, http.StatusOK, derivedStatsResponse{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
		HPMax:            hpMax,
		ArmorClass:       armorClass,
		Modifiers:        modifiers,
	})
}

var (
	sessionsMu sync.RWMutex
	sessions   = make(map[string]*session)
)

type session struct {
	mu         sync.RWMutex
	id         string
	round      int
	turnIndex  int
	order      []combatantOutput
	conditions map[string][]conditionEntry
}

type conditionEntry struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type createSessionRequest struct {
	ID         string           `json:"id"`
	Combatants []combatantInput `json:"combatants"`
}

type createSessionResponse struct {
	ID        string            `json:"id"`
	Round     int               `json:"round"`
	TurnIndex int               `json:"turn_index"`
	Active    *combatantOutput  `json:"active"`
	Order     []combatantOutput `json:"order"`
}

func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	var req createSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if req.ID == "" {
		respond(w, http.StatusBadRequest, map[string]string{"error": "missing id"})
		return
	}

	sessionsMu.Lock()
	if _, exists := sessions[req.ID]; exists {
		sessionsMu.Unlock()
		respond(w, http.StatusBadRequest, map[string]string{"error": "duplicate id"})
		return
	}

	scored := make([]scoredCombatant, len(req.Combatants))
	for i, c := range req.Combatants {
		scored[i] = scoredCombatant{Name: c.Name, Dex: c.Dex, Score: c.Roll + c.Dex}
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		if scored[i].Dex != scored[j].Dex {
			return scored[i].Dex > scored[j].Dex
		}
		return scored[i].Name < scored[j].Name
	})

	order := make([]combatantOutput, len(scored))
	for i, c := range scored {
		order[i] = combatantOutput{Name: c.Name, Score: c.Score}
	}

	s := &session{
		id:         req.ID,
		round:      1,
		turnIndex:  0,
		order:      order,
		conditions: make(map[string][]conditionEntry),
	}
	sessions[req.ID] = s
	sessionsMu.Unlock()

	var active *combatantOutput
	if len(order) > 0 {
		active = &order[0]
	}

	respond(w, http.StatusOK, createSessionResponse{
		ID:        req.ID,
		Round:     1,
		TurnIndex: 0,
		Active:    active,
		Order:     order,
	})
}

type addConditionRequest struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds int    `json:"duration_rounds"`
}

type addConditionResponse struct {
	Target     string             `json:"target"`
	Conditions []conditionEntry   `json:"conditions"`
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	sessionsMu.RLock()
	s, ok := sessions[id]
	sessionsMu.RUnlock()
	if !ok {
		respond(w, http.StatusNotFound, map[string]string{"error": "session not found"})
		return
	}

	var req addConditionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if req.Target == "" || req.Condition == "" || req.DurationRounds <= 0 {
		respond(w, http.StatusBadRequest, map[string]string{"error": "invalid condition"})
		return
	}

	valid := false
	s.mu.RLock()
	for _, c := range s.order {
		if c.Name == req.Target {
			valid = true
			break
		}
	}
	s.mu.RUnlock()
	if !valid {
		respond(w, http.StatusBadRequest, map[string]string{"error": "unknown target"})
		return
	}

	s.mu.Lock()
	s.conditions[req.Target] = append(s.conditions[req.Target], conditionEntry{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})
	conds := s.conditions[req.Target]
	s.mu.Unlock()

	respond(w, http.StatusOK, addConditionResponse{
		Target:     req.Target,
		Conditions: conds,
	})
}

type advanceResponse struct {
	ID         string                       `json:"id"`
	Round      int                          `json:"round"`
	TurnIndex  int                          `json:"turn_index"`
	Active     *combatantOutput             `json:"active"`
	Conditions map[string][]conditionEntry  `json:"conditions"`
}

func handleAdvance(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	sessionsMu.RLock()
	s, ok := sessions[id]
	sessionsMu.RUnlock()
	if !ok {
		respond(w, http.StatusNotFound, map[string]string{"error": "session not found"})
		return
	}

	s.mu.Lock()
	if len(s.order) > 0 {
		s.turnIndex++
		if s.turnIndex >= len(s.order) {
			s.turnIndex = 0
			s.round++
		}

		activeName := s.order[s.turnIndex].Name
		conds := s.conditions[activeName]
		if len(conds) > 0 {
			updated := make([]conditionEntry, 0, len(conds))
			for _, c := range conds {
				c.RemainingRounds--
				if c.RemainingRounds > 0 {
					updated = append(updated, c)
				}
			}
			s.conditions[activeName] = updated
		}
	}

	var active *combatantOutput
	if len(s.order) > 0 {
		active = &s.order[s.turnIndex]
	}

	respConds := make(map[string][]conditionEntry)
	for name, conds := range s.conditions {
		copyConds := make([]conditionEntry, len(conds))
		copy(copyConds, conds)
		respConds[name] = copyConds
	}

	resp := advanceResponse{
		ID:         s.id,
		Round:      s.round,
		TurnIndex:  s.turnIndex,
		Active:     active,
		Conditions: respConds,
	}
	s.mu.Unlock()

	respond(w, http.StatusOK, resp)
}
