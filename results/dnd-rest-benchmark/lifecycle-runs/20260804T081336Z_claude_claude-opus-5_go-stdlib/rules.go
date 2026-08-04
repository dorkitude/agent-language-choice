package main

import (
	"encoding/json"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Stateless core rules: dice statistics, ability checks, encounter XP, and
// initiative ordering. Nothing here reads or writes persistent state.

// ---------- POST /v1/dice/stats ----------

// diceRe matches "NdM" with an optional signed flat modifier, e.g. "2d6+3".
var diceRe = regexp.MustCompile(`^([0-9]+)[dD]([0-9]+)([+-][0-9]+)?$`)

type diceRequest struct {
	Expression *string `json:"expression"`
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
	if !requirePost(w, r) {
		return
	}
	var req diceRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Expression == nil {
		writeError(w, http.StatusBadRequest, "expression is required")
		return
	}

	m := diceRe.FindStringSubmatch(strings.TrimSpace(*req.Expression))
	if m == nil {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}
	count, err := strconv.Atoi(m[1])
	if err != nil || count <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}
	sides, err := strconv.Atoi(m[2])
	if err != nil || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}
	modifier := 0
	if m[3] != "" {
		modifier, err = strconv.Atoi(m[3])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid dice expression")
			return
		}
	}

	writeJSON(w, http.StatusOK, diceResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       count + modifier,
		Max:       count*sides + modifier,
		Average:   float64(count)*(float64(sides)+1)/2 + float64(modifier),
	})
}

// ---------- POST /v1/checks/ability ----------

type abilityRequest struct {
	Roll     *int `json:"roll"`
	Modifier *int `json:"modifier"`
	DC       *int `json:"dc"`
}

type abilityResponse struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

func handleAbilityCheck(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req abilityRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Roll == nil {
		writeError(w, http.StatusBadRequest, "roll is required")
		return
	}
	if req.DC == nil {
		writeError(w, http.StatusBadRequest, "dc is required")
		return
	}
	modifier := 0
	if req.Modifier != nil {
		modifier = *req.Modifier
	}

	total := *req.Roll + modifier
	writeJSON(w, http.StatusOK, abilityResponse{
		Total:   total,
		Success: total >= *req.DC,
		Margin:  total - *req.DC,
	})
}

// ---------- POST /v1/encounters/adjusted-xp ----------

type partyMember struct {
	Level *int `json:"level"`
}

type monsterGroup struct {
	CR    *json.RawMessage `json:"cr"`
	Count *int             `json:"count"`
}

type encounterRequest struct {
	Party    []partyMember  `json:"party"`
	Monsters []monsterGroup `json:"monsters"`
}

type encounterResponse struct {
	BaseXP       int        `json:"base_xp"`
	MonsterCount int        `json:"monster_count"`
	Multiplier   float64    `json:"multiplier"`
	AdjustedXP   float64    `json:"adjusted_xp"`
	Difficulty   string     `json:"difficulty"`
	Thresholds   thresholds `json:"thresholds"`
}

func handleAdjustedXP(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req encounterRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	th, msg := sumThresholds(req.Party, coreLevelThreshold)
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, group := range req.Monsters {
		key, ok := crKey(group.CR)
		if !ok {
			writeError(w, http.StatusBadRequest, "invalid challenge rating")
			return
		}
		xp, ok := coreCRXP[key]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		count := 1
		if group.Count != nil {
			count = *group.Count
		}
		if count < 0 {
			writeError(w, http.StatusBadRequest, "monster count must not be negative")
			return
		}
		baseXP += xp * count
		monsterCount += count
	}

	multiplier := countMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * multiplier

	writeJSON(w, http.StatusOK, encounterResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   classifyDifficulty(adjustedXP, th),
		Thresholds:   th,
	})
}

// ---------- POST /v1/initiative/order ----------

type combatant struct {
	Name *string `json:"name"`
	Dex  *int    `json:"dex"`
	Roll *int    `json:"roll"`
}

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeRequest struct {
	Combatants []combatant `json:"combatants"`
}

type initiativeResponse struct {
	Order []initiativeEntry `json:"order"`
}

// initiativeOrder validates combatants and returns them in deterministic
// initiative order: score descending, then dexterity descending, then name
// ascending. Ties are fully broken so the same input always yields the same
// order — no randomness anywhere.
//
// uniqueNames tightens validation for stateful combat sessions, where a name is
// the key used to attach conditions and so must be present and unambiguous.
// The stateless endpoint keeps its looser original contract.
//
// The second result is a client-facing message, empty when the input is valid;
// every failure here maps to 400.
func initiativeOrder(combatants []combatant, uniqueNames bool) ([]initiativeEntry, string) {
	type ranked struct {
		name  string
		dex   int
		score int
	}
	entries := make([]ranked, 0, len(combatants))
	seen := make(map[string]bool, len(combatants))
	for _, c := range combatants {
		if c.Name == nil || (uniqueNames && *c.Name == "") {
			return nil, "combatant name is required"
		}
		if c.Roll == nil {
			return nil, "combatant roll is required"
		}
		if uniqueNames {
			if seen[*c.Name] {
				return nil, "combatant names must be unique"
			}
			seen[*c.Name] = true
		}
		dex := 0
		if c.Dex != nil {
			dex = *c.Dex
		}
		entries = append(entries, ranked{name: *c.Name, dex: dex, score: *c.Roll + dex})
	}

	sort.SliceStable(entries, func(i, j int) bool {
		a, b := entries[i], entries[j]
		if a.score != b.score {
			return a.score > b.score
		}
		if a.dex != b.dex {
			return a.dex > b.dex
		}
		return a.name < b.name
	})

	order := make([]initiativeEntry, 0, len(entries))
	for _, e := range entries {
		order = append(order, initiativeEntry{Name: e.name, Score: e.score})
	}
	return order, ""
}

func handleInitiative(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req initiativeRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	order, msg := initiativeOrder(req.Combatants, false)
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}
	writeJSON(w, http.StatusOK, initiativeResponse{Order: order})
}
