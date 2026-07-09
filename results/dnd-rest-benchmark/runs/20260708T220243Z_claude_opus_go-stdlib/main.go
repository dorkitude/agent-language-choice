package main

import (
	"encoding/json"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func badRequest(w http.ResponseWriter) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request"})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

var diceRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
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
		badRequest(w)
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

	multiplier := countMultiplier(monsterCount)
	adjustedXP := int(float64(baseXP) * multiplier)

	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, member := range req.Party {
		t, ok := levelThresholds[member.Level]
		if !ok {
			badRequest(w)
			return
		}
		thresholds["easy"] += t["easy"]
		thresholds["medium"] += t["medium"]
		thresholds["hard"] += t["hard"]
		thresholds["deadly"] += t["deadly"]
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
		badRequest(w)
		return
	}

	type entry struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}
	order := make([]entry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, entry{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex})
	}

	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	writeJSON(w, http.StatusOK, map[string]any{"order": order})
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
	mux.HandleFunc("POST /v1/initiative/order", initiativeHandler)

	server := &http.Server{
		Addr:    "127.0.0.1:" + port,
		Handler: mux,
	}
	if err := server.ListenAndServe(); err != nil {
		panic(err)
	}
}
