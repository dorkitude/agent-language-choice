package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
)

var diceExpression = regexp.MustCompile(`^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$`)
var combatSessions = newCombatStore()

type errorResponse struct {
	Error string `json:"error"`
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
	mux.HandleFunc("/v1/combat/sessions", combatSessionsHandler)
	mux.HandleFunc("/v1/combat/sessions/", combatSessionActionHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	addr := "127.0.0.1:" + port
	log.Fatal(http.ListenAndServe(addr, mux))
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
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

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req diceStatsRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	count, sides, modifier, err := parseDiceExpression(req.Expression)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	minimum := count + modifier
	maximum := count*sides + modifier
	average := float64(count)*(float64(sides)+1)/2 + float64(modifier)

	writeJSON(w, http.StatusOK, diceStatsResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       minimum,
		Max:       maximum,
		Average:   average,
	})
}

func parseDiceExpression(expression string) (int, int, int, error) {
	matches := diceExpression.FindStringSubmatch(expression)
	if matches == nil {
		return 0, 0, 0, errors.New("expression does not match dice grammar")
	}

	count, err := strconv.Atoi(matches[1])
	if err != nil || count <= 0 {
		return 0, 0, 0, errors.New("invalid dice count")
	}

	sides, err := strconv.Atoi(matches[2])
	if err != nil || sides <= 0 {
		return 0, 0, 0, errors.New("invalid die sides")
	}

	modifier := 0
	if matches[4] != "" {
		modifier, err = strconv.Atoi(matches[4])
		if err != nil {
			return 0, 0, 0, errors.New("invalid modifier")
		}
		if matches[3] == "-" {
			modifier = -modifier
		}
	}

	return count, sides, modifier, nil
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

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req abilityCheckRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, abilityCheckResponse{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

type adjustedXPRequest struct {
	Party    []partyMember `json:"party"`
	Monsters []monster     `json:"monsters"`
}

type partyMember struct {
	Level int `json:"level"`
}

type monster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type adjustedXPResponse struct {
	BaseXP       int        `json:"base_xp"`
	MonsterCount int        `json:"monster_count"`
	Multiplier   float64    `json:"multiplier"`
	AdjustedXP   float64    `json:"adjusted_xp"`
	Difficulty   string     `json:"difficulty"`
	Thresholds   thresholds `json:"thresholds"`
}

var monsterXP = map[string]int{
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

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req adjustedXPRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, monster := range req.Monsters {
		xp, ok := monsterXP[monster.CR]
		if !ok || monster.Count <= 0 {
			writeError(w, http.StatusBadRequest, "invalid monster")
			return
		}
		baseXP += xp * monster.Count
		monsterCount += monster.Count
	}

	partyThresholds := thresholds{}
	for _, member := range req.Party {
		if member.Level != 3 {
			writeError(w, http.StatusBadRequest, "unsupported party level")
			return
		}
		partyThresholds.Easy += 75
		partyThresholds.Medium += 150
		partyThresholds.Hard += 225
		partyThresholds.Deadly += 400
	}

	multiplier := monsterMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * multiplier
	writeJSON(w, http.StatusOK, adjustedXPResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty(adjustedXP, partyThresholds),
		Thresholds:   partyThresholds,
	})
}

func monsterMultiplier(count int) float64 {
	switch {
	case count <= 0:
		return 0
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

func difficulty(adjustedXP float64, t thresholds) string {
	switch {
	case t.Deadly > 0 && adjustedXP >= float64(t.Deadly):
		return "deadly"
	case t.Hard > 0 && adjustedXP >= float64(t.Hard):
		return "hard"
	case t.Medium > 0 && adjustedXP >= float64(t.Medium):
		return "medium"
	case t.Easy > 0 && adjustedXP >= float64(t.Easy):
		return "easy"
	default:
		return "trivial"
	}
}

type initiativeOrderRequest struct {
	Combatants []combatant `json:"combatants"`
}

type combatant struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeOrderResponse struct {
	Order []initiativeEntry `json:"order"`
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req initiativeOrderRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	order := initiativeOrder(req.Combatants)

	writeJSON(w, http.StatusOK, initiativeOrderResponse{Order: order})
}

func initiativeOrder(input []combatant) []initiativeEntry {
	combatants := append([]combatant(nil), input...)
	sort.SliceStable(combatants, func(i, j int) bool {
		leftScore := combatants[i].Roll + combatants[i].Dex
		rightScore := combatants[j].Roll + combatants[j].Dex
		if leftScore != rightScore {
			return leftScore > rightScore
		}
		if combatants[i].Dex != combatants[j].Dex {
			return combatants[i].Dex > combatants[j].Dex
		}
		return combatants[i].Name < combatants[j].Name
	})

	order := make([]initiativeEntry, 0, len(combatants))
	for _, combatant := range combatants {
		order = append(order, initiativeEntry{
			Name:  combatant.Name,
			Score: combatant.Roll + combatant.Dex,
		})
	}

	return order
}

type combatStore struct {
	mu       sync.Mutex
	sessions map[string]*combatSession
}

type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []initiativeEntry
	Conditions map[string][]conditionEntry
}

type conditionEntry struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type createCombatSessionRequest struct {
	ID         string      `json:"id"`
	Combatants []combatant `json:"combatants"`
}

type combatSessionResponse struct {
	ID        string            `json:"id"`
	Round     int               `json:"round"`
	TurnIndex int               `json:"turn_index"`
	Active    initiativeEntry   `json:"active"`
	Order     []initiativeEntry `json:"order,omitempty"`
}

type addConditionRequest struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds int    `json:"duration_rounds"`
}

type conditionTargetResponse struct {
	Target     string           `json:"target"`
	Conditions []conditionEntry `json:"conditions"`
}

type advanceCombatResponse struct {
	ID         string                      `json:"id"`
	Round      int                         `json:"round"`
	TurnIndex  int                         `json:"turn_index"`
	Active     initiativeEntry             `json:"active"`
	Conditions map[string][]conditionEntry `json:"conditions"`
}

func newCombatStore() *combatStore {
	return &combatStore{sessions: make(map[string]*combatSession)}
}

func combatSessionsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req createCombatSessionRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	if req.ID == "" || len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "invalid session")
		return
	}

	order := initiativeOrder(req.Combatants)
	for _, entry := range order {
		if entry.Name == "" {
			writeError(w, http.StatusBadRequest, "invalid combatant")
			return
		}
	}

	combatSessions.mu.Lock()
	defer combatSessions.mu.Unlock()

	if _, exists := combatSessions.sessions[req.ID]; exists {
		writeError(w, http.StatusBadRequest, "session already exists")
		return
	}

	session := &combatSession{
		ID:         req.ID,
		Round:      1,
		TurnIndex:  0,
		Order:      order,
		Conditions: make(map[string][]conditionEntry),
	}
	combatSessions.sessions[req.ID] = session

	writeJSON(w, http.StatusOK, session.snapshot(true))
}

func combatSessionActionHandler(w http.ResponseWriter, r *http.Request) {
	rest := strings.TrimPrefix(r.URL.Path, "/v1/combat/sessions/")
	parts := strings.Split(rest, "/")
	if len(parts) != 2 || parts[0] == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}

	switch parts[1] {
	case "conditions":
		addConditionHandler(w, r, parts[0])
	case "advance":
		advanceCombatHandler(w, r, parts[0])
	default:
		writeError(w, http.StatusNotFound, "not found")
	}
}

func addConditionHandler(w http.ResponseWriter, r *http.Request, id string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req addConditionRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	if req.Target == "" || req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "invalid condition")
		return
	}

	combatSessions.mu.Lock()
	defer combatSessions.mu.Unlock()

	session, ok := combatSessions.sessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session")
		return
	}
	if !session.hasCombatant(req.Target) {
		writeError(w, http.StatusBadRequest, "unknown target")
		return
	}

	session.Conditions[req.Target] = append(session.Conditions[req.Target], conditionEntry{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})

	writeJSON(w, http.StatusOK, conditionTargetResponse{
		Target:     req.Target,
		Conditions: copyConditions(session.Conditions[req.Target]),
	})
}

func advanceCombatHandler(w http.ResponseWriter, r *http.Request, id string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	combatSessions.mu.Lock()
	defer combatSessions.mu.Unlock()

	session, ok := combatSessions.sessions[id]
	if !ok {
		writeError(w, http.StatusNotFound, "unknown session")
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}
	session.decrementActiveConditions()

	writeJSON(w, http.StatusOK, advanceCombatResponse{
		ID:         session.ID,
		Round:      session.Round,
		TurnIndex:  session.TurnIndex,
		Active:     session.active(),
		Conditions: session.conditionsSnapshot(),
	})
}

func (s *combatSession) snapshot(includeOrder bool) combatSessionResponse {
	response := combatSessionResponse{
		ID:        s.ID,
		Round:     s.Round,
		TurnIndex: s.TurnIndex,
		Active:    s.active(),
	}
	if includeOrder {
		response.Order = append([]initiativeEntry(nil), s.Order...)
	}
	return response
}

func (s *combatSession) active() initiativeEntry {
	return s.Order[s.TurnIndex]
}

func (s *combatSession) hasCombatant(name string) bool {
	for _, entry := range s.Order {
		if entry.Name == name {
			return true
		}
	}
	return false
}

func (s *combatSession) decrementActiveConditions() {
	activeName := s.active().Name
	conditions := s.Conditions[activeName]
	if len(conditions) == 0 {
		return
	}

	kept := conditions[:0]
	for _, condition := range conditions {
		condition.RemainingRounds--
		if condition.RemainingRounds > 0 {
			kept = append(kept, condition)
		}
	}
	if len(kept) == 0 {
		s.Conditions[activeName] = []conditionEntry{}
		return
	}
	s.Conditions[activeName] = kept
}

func (s *combatSession) conditionsSnapshot() map[string][]conditionEntry {
	conditions := make(map[string][]conditionEntry)
	for target, entries := range s.Conditions {
		conditions[target] = copyConditions(entries)
	}
	return conditions
}

func copyConditions(entries []conditionEntry) []conditionEntry {
	if len(entries) == 0 {
		return []conditionEntry{}
	}
	return append([]conditionEntry(nil), entries...)
}

type abilityModifierRequest struct {
	Score int `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req abilityModifierRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	if !validAbilityScore(req.Score) {
		writeError(w, http.StatusBadRequest, "invalid score")
		return
	}

	writeJSON(w, http.StatusOK, abilityModifierResponse{
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

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req proficiencyRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	bonus, ok := proficiencyBonus(req.Level)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid level")
		return
	}

	writeJSON(w, http.StatusOK, proficiencyResponse{
		Level:            req.Level,
		ProficiencyBonus: bonus,
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
	Level            int       `json:"level"`
	ProficiencyBonus int       `json:"proficiency_bonus"`
	HPMax            int       `json:"hp_max"`
	ArmorClass       int       `json:"armor_class"`
	Modifiers        abilities `json:"modifiers"`
}

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req derivedStatsRequest
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	bonus, ok := proficiencyBonus(req.Level)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid level")
		return
	}
	if !validAbilities(req.Abilities) {
		writeError(w, http.StatusBadRequest, "invalid abilities")
		return
	}

	modifiers := abilities{
		Str: abilityModifier(req.Abilities.Str),
		Dex: abilityModifier(req.Abilities.Dex),
		Con: abilityModifier(req.Abilities.Con),
		Int: abilityModifier(req.Abilities.Int),
		Wis: abilityModifier(req.Abilities.Wis),
		Cha: abilityModifier(req.Abilities.Cha),
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}

	writeJSON(w, http.StatusOK, derivedStatsResponse{
		Level:            req.Level,
		ProficiencyBonus: bonus,
		HPMax:            req.Level * (6 + modifiers.Con),
		ArmorClass:       req.Armor.Base + minInt(modifiers.Dex, req.Armor.DexCap) + shieldBonus,
		Modifiers:        modifiers,
	})
}

func validAbilityScore(score int) bool {
	return score >= 1 && score <= 30
}

func validAbilities(a abilities) bool {
	return validAbilityScore(a.Str) &&
		validAbilityScore(a.Dex) &&
		validAbilityScore(a.Con) &&
		validAbilityScore(a.Int) &&
		validAbilityScore(a.Wis) &&
		validAbilityScore(a.Cha)
}

func abilityModifier(score int) int {
	return floorDiv(score-10, 2)
}

func proficiencyBonus(level int) (int, bool) {
	if level < 1 || level > 20 {
		return 0, false
	}
	return 2 + (level-1)/4, true
}

func floorDiv(n, d int) int {
	q := n / d
	if n%d != 0 && (n < 0) != (d < 0) {
		q--
	}
	return q
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func requireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method == method {
		return true
	}
	w.Header().Set("Allow", method)
	writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	return false
}

func readJSON(r *http.Request, dst any) error {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(dst); err != nil {
		return err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return fmt.Errorf("request body must contain a single json value")
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		log.Printf("write response: %v", err)
	}
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, errorResponse{Error: message})
}
