package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
)

// JSON response helpers. These keep the wire format uniform across all
// handlers and centralize the single Content-Type header we send.

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("encode response: %v", err)
	}
}

func badRequest(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
}

func conflict(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusConflict, map[string]string{"error": msg})
}

func notFound(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusNotFound, map[string]string{"error": msg})
}

func unauthorized(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusUnauthorized, map[string]string{"error": msg})
}

func forbidden(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusForbidden, map[string]string{"error": msg})
}

// isUniqueViolation reports whether an SQLite error is a unique-constraint
// failure. Callers use this to translate the raw driver error into a 409
// response with a domain-specific message.
func isUniqueViolation(err error) bool {
	return err != nil && strings.Contains(err.Error(), "UNIQUE constraint failed")
}

// isForeignKeyViolation reports whether an SQLite error is a foreign-key
// failure. Callers use this to translate the raw driver error into a 404
// response when a referenced entity is missing.
func isForeignKeyViolation(err error) bool {
	return err != nil && strings.Contains(err.Error(), "FOREIGN KEY constraint failed")
}

// authFail writes the standard authentication-failure response. status is the
// HTTP code returned by authenticate: 401 for missing or malformed credentials,
// 403 for a syntactically valid token whose user does not exist.
func authFail(w http.ResponseWriter, status int) {
	if status == http.StatusUnauthorized {
		unauthorized(w, "missing or invalid credentials")
	} else {
		forbidden(w, "not a campaign member")
	}
}

// requireCampaign loads a campaign by id and writes a 404 response if the id is
// empty, the query fails, or the campaign does not exist. It returns the loaded
// campaign or nil when a response has already been written.
func requireCampaign(w http.ResponseWriter, campaignID string) *campaign {
	if campaignID == "" {
		notFound(w, "campaign not found")
		return nil
	}
	c, err := dbGetCampaign(campaignID)
	if err != nil {
		log.Printf("get campaign: %v", err)
		notFound(w, "campaign not found")
		return nil
	}
	if c == nil {
		notFound(w, "campaign not found")
		return nil
	}
	return c
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	m := diceExpr.FindStringSubmatch(strings.TrimSpace(req.Expression))
	if m == nil {
		badRequest(w, "invalid expression")
		return
	}

	count, _ := strconv.Atoi(m[1])
	sides, _ := strconv.Atoi(m[2])
	modifier := 0
	if m[3] != "" {
		modifier, _ = strconv.Atoi(m[3])
	}

	if count <= 0 || sides <= 0 {
		badRequest(w, "invalid expression")
		return
	}

	min := count + modifier
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
		badRequest(w, "invalid json")
		return
	}

	total := req.Roll + req.Modifier

	writeJSON(w, http.StatusOK, map[string]any{
		"total":   total,
		"success": total >= req.DC,
		"margin":  total - req.DC,
	})
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
		badRequest(w, "invalid json")
		return
	}

	groups := make([]encounterMonsterGroup, len(req.Monsters))
	for i, m := range req.Monsters {
		groups[i] = encounterMonsterGroup{CR: m.CR, Count: m.Count}
	}
	partyLevels := make([]int, len(req.Party))
	for i, p := range req.Party {
		partyLevels[i] = p.Level
	}

	baseXP, monsterCount, _, multiplier, totals, difficulty, err := computeEncounterMetrics(partyLevels, groups)
	if err != nil {
		badRequest(w, err.Error())
		return
	}

	// The original wire format returns the raw floating-point adjusted XP.
	// The difficulty label is computed from the truncated integer value, which
	// computeEncounterMetrics already provides.
	writeJSON(w, http.StatusOK, map[string]any{
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   float64(baseXP) * multiplier,
		"difficulty":    difficulty,
		"thresholds": map[string]int{
			"easy":   totals.easy,
			"medium": totals.medium,
			"hard":   totals.hard,
			"deadly": totals.deadly,
		},
	})
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Combatants []combatantInput `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	order := computeInitiative(req.Combatants)
	writeJSON(w, http.StatusOK, map[string]any{"order": order})
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Score < 1 || req.Score > 30 {
		badRequest(w, "score must be between 1 and 30")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"score":    req.Score,
		"modifier": abilityModifier(req.Score),
	})
}

func proficiencyBonusHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be between 1 and 20")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
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
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be between 1 and 20")
		return
	}

	scores := map[string]int{
		"str": req.Abilities.Str,
		"dex": req.Abilities.Dex,
		"con": req.Abilities.Con,
		"int": req.Abilities.Int,
		"wis": req.Abilities.Wis,
		"cha": req.Abilities.Cha,
	}
	for name, score := range scores {
		if score < 1 || score > 30 {
			badRequest(w, fmt.Sprintf("ability score %s must be between 1 and 30", name))
			return
		}
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
	dexContribution := modifiers["dex"]
	if dexContribution > req.Armor.DexCap {
		dexContribution = req.Armor.DexCap
	}
	armorClass := req.Armor.Base + dexContribution + shieldBonus

	hpMax := req.Level * (6 + modifiers["con"])

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             req.Level,
		"proficiency_bonus": proficiencyBonus(req.Level),
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers":         modifiers,
	})
}
