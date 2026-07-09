package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handleHealth)
	mux.HandleFunc("POST /v1/dice/stats", handleDiceStats)
	mux.HandleFunc("POST /v1/checks/ability", handleAbility)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", handleEncounter)
	mux.HandleFunc("POST /v1/initiative/order", handleInitiative)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	addr := "127.0.0.1:" + port
	fmt.Fprintf(os.Stderr, "dndrest listening on %s\n", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		fmt.Fprintf(os.Stderr, "server error: %v\n", err)
		os.Exit(1)
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if buf, err := json.Marshal(v); err == nil {
		_, _ = w.Write(buf)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func decode(r *http.Request, v any) bool {
	return json.NewDecoder(r.Body).Decode(v) == nil
}

// --- GET /health ---

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, struct {
		Ok bool `json:"ok"`
	}{true})
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
	if !decode(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	count, sides, mod, ok := parseDice(req.Expression)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}
	writeJSON(w, http.StatusOK, diceStatsResp{
		DiceCount: count,
		Sides:     sides,
		Modifier:  mod,
		Min:       count + mod,
		Max:       count*sides + mod,
		Average:   float64(count)*float64(sides+1)/2 + float64(mod),
	})
}

// parseDice parses "<count>d<sides>[+<mod>|-<mod>]".
// count and sides must be positive base-10 integers (digits only, no sign).
func parseDice(expr string) (count, sides, mod int, ok bool) {
	idx := strings.IndexByte(expr, 'd')
	if idx <= 0 { // no 'd', or empty count
		return
	}
	rest := expr[idx+1:]
	if rest == "" { // no sides
		return
	}
	var okc bool
	count, okc = parseUintStrict(expr[:idx])
	if !okc || count <= 0 {
		return
	}
	// Locate an optional modifier sign. It cannot be at index 0 because
	// sides must begin with a digit.
	signIdx := -1
	for i := 1; i < len(rest); i++ {
		if rest[i] == '+' || rest[i] == '-' {
			signIdx = i
			break
		}
	}
	var sidesStr string
	if signIdx == -1 {
		sidesStr = rest
	} else {
		sidesStr = rest[:signIdx]
		var okm bool
		mod, okm = parseIntSigned(rest[signIdx:])
		if !okm {
			return
		}
	}
	var oks bool
	sides, oks = parseUintStrict(sidesStr)
	if !oks || sides <= 0 {
		return
	}
	ok = true
	return
}

// parseUintStrict accepts only non-empty digit strings (no sign).
func parseUintStrict(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, false
	}
	return n, true
}

// parseIntSigned requires a leading '+' or '-' followed by >=1 digit.
func parseIntSigned(s string) (int, bool) {
	if len(s) < 2 || (s[0] != '+' && s[0] != '-') {
		return 0, false
	}
	for i := 1; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, false
	}
	return n, true
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
	if !decode(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid json")
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

type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

var thresholdsByLevel = map[int]thresholds{
	3: {Easy: 75, Medium: 150, Hard: 225, Deadly: 400},
}

type partyMember struct {
	Level int `json:"level"`
}

type monsterEntry struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type encounterReq struct {
	Party    []partyMember  `json:"party"`
	Monsters []monsterEntry `json:"monsters"`
}

type encounterResp struct {
	BaseXP       int        `json:"base_xp"`
	MonsterCount int        `json:"monster_count"`
	Multiplier   float64    `json:"multiplier"`
	AdjustedXP   float64    `json:"adjusted_xp"`
	Difficulty   string     `json:"difficulty"`
	Thresholds   thresholds `json:"thresholds"`
}

func monsterMultiplier(count int) float64 {
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

func difficultyFor(adjusted float64, t thresholds) string {
	switch {
	case adjusted >= float64(t.Deadly):
		return "deadly"
	case adjusted >= float64(t.Hard):
		return "hard"
	case adjusted >= float64(t.Medium):
		return "medium"
	case adjusted >= float64(t.Easy):
		return "easy"
	default:
		return "trivial"
	}
}

func handleEncounter(w http.ResponseWriter, r *http.Request) {
	var req encounterReq
	if !decode(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := xpByCR[m.CR]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}
	mult := monsterMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * mult

	var t thresholds
	for _, p := range req.Party {
		pt, ok := thresholdsByLevel[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported level")
			return
		}
		t.Easy += pt.Easy
		t.Medium += pt.Medium
		t.Hard += pt.Hard
		t.Deadly += pt.Deadly
	}

	writeJSON(w, http.StatusOK, encounterResp{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   mult,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficultyFor(adjustedXP, t),
		Thresholds:   t,
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

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeResp struct {
	Order []initiativeEntry `json:"order"`
}

func handleInitiative(w http.ResponseWriter, r *http.Request) {
	var req initiativeReq
	if !decode(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	sort.SliceStable(req.Combatants, func(i, j int) bool {
		ci, cj := req.Combatants[i], req.Combatants[j]
		si, sj := ci.Roll+ci.Dex, cj.Roll+cj.Dex
		if si != sj {
			return si > sj // score descending
		}
		if ci.Dex != cj.Dex {
			return ci.Dex > cj.Dex // dex descending
		}
		return ci.Name < cj.Name // name ascending
	})
	order := make([]initiativeEntry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, initiativeEntry{Name: c.Name, Score: c.Roll + c.Dex})
	}
	writeJSON(w, http.StatusOK, initiativeResp{Order: order})
}
