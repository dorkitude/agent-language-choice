package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("POST /v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("POST /v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("POST /v1/initiative/order", initiativeOrderHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	addr := "127.0.0.1:" + port
	log.Printf("Listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}

func respondJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Printf("encode error: %v", err)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	respondJSON(w, http.StatusOK, map[string]any{"ok": true})
}

var diceExprRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

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

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req diceStatsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid JSON"})
		return
	}

	matches := diceExprRe.FindStringSubmatch(req.Expression)
	if matches == nil {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid expression"})
		return
	}

	count, _ := strconv.Atoi(matches[1])
	sides, _ := strconv.Atoi(matches[2])
	modifier := 0
	if matches[3] != "" {
		modifier, _ = strconv.Atoi(matches[3])
	}

	if count <= 0 || sides <= 0 {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid expression"})
		return
	}

	min := count + modifier
	max := count*sides + modifier
	average := float64(min+max) / 2.0

	respondJSON(w, http.StatusOK, diceStatsResp{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       min,
		Max:       max,
		Average:   average,
	})
}

type abilityCheckReq struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

type abilityCheckResp struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req abilityCheckReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid JSON"})
		return
	}

	total := req.Roll + req.Modifier
	respondJSON(w, http.StatusOK, abilityCheckResp{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
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

var level3Thresholds = map[string]int{
	"easy":   75,
	"medium": 150,
	"hard":   225,
	"deadly": 400,
}

type partyMember struct {
	Level int `json:"level"`
}

type monster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type adjustedXPReq struct {
	Party    []partyMember `json:"party"`
	Monsters []monster     `json:"monsters"`
}

type adjustedXPResp struct {
	BaseXP      int            `json:"base_xp"`
	MonsterCount int           `json:"monster_count"`
	Multiplier  float64        `json:"multiplier"`
	AdjustedXP  int            `json:"adjusted_xp"`
	Difficulty  string         `json:"difficulty"`
	Thresholds  map[string]int `json:"thresholds"`
}

func multiplierForCount(count int) float64 {
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
	var req adjustedXPReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid JSON"})
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok || m.Count <= 0 {
			respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid monster"})
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}

	multiplier := multiplierForCount(monsterCount)
	adjustedXP := int(float64(baseXP) * multiplier)

	thresholds := map[string]int{
		"easy":   0,
		"medium": 0,
		"hard":   0,
		"deadly": 0,
	}
	for _, p := range req.Party {
		if p.Level != 3 {
			respondJSON(w, http.StatusBadRequest, map[string]any{"error": "unsupported level"})
			return
		}
		for k, v := range level3Thresholds {
			thresholds[k] += v
		}
	}

	difficulty := "trivial"
	if adjustedXP >= thresholds["easy"] {
		difficulty = "easy"
	}
	if adjustedXP >= thresholds["medium"] {
		difficulty = "medium"
	}
	if adjustedXP >= thresholds["hard"] {
		difficulty = "hard"
	}
	if adjustedXP >= thresholds["deadly"] {
		difficulty = "deadly"
	}

	respondJSON(w, http.StatusOK, adjustedXPResp{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty,
		Thresholds:   thresholds,
	})
}

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

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	var req initiativeReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid JSON"})
		return
	}

	type scoredCombatant struct {
		name  string
		dex   int
		score int
	}
	scored := make([]scoredCombatant, len(req.Combatants))
	for i, c := range req.Combatants {
		scored[i] = scoredCombatant{name: c.Name, dex: c.Dex, score: c.Roll + c.Dex}
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].score != scored[j].score {
			return scored[i].score > scored[j].score
		}
		if scored[i].dex != scored[j].dex {
			return scored[i].dex > scored[j].dex
		}
		return scored[i].name < scored[j].name
	})

	order := make([]orderEntry, len(scored))
	for i, s := range scored {
		order[i] = orderEntry{Name: s.name, Score: s.score}
	}

	respondJSON(w, http.StatusOK, initiativeResp{Order: order})
}
