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

var diceExprRe = regexp.MustCompile(`^(\d+)d(\d+)(?:([+-])(\d+))?$`)

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
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	count, err := strconv.Atoi(m[1])
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}
	sides, err := strconv.Atoi(m[2])
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}
	if count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "count and sides must be positive")
		return
	}

	modifier := 0
	if m[3] != "" {
		mod, err := strconv.Atoi(m[4])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid expression")
			return
		}
		if m[3] == "-" {
			modifier = -mod
		} else {
			modifier = mod
		}
	}

	min := count*1 + modifier
	max := count*sides + modifier
	average := (float64(count)*(float64(sides)+1)/2.0 + float64(modifier))

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

var levelThresholds = map[int]map[string]float64{
	3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
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
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp * float64(m.Count)
		monsterCount += m.Count
	}

	multiplier := countMultiplier(monsterCount)
	adjustedXP := baseXP * multiplier

	thresholds := map[string]float64{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, p := range req.Party {
		lt, ok := levelThresholds[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported party level")
			return
		}
		thresholds["easy"] += lt["easy"]
		thresholds["medium"] += lt["medium"]
		thresholds["hard"] += lt["hard"]
		thresholds["deadly"] += lt["deadly"]
	}

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

	writeJSON(w, http.StatusOK, map[string]any{
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   adjustedXP,
		"difficulty":    difficulty,
		"thresholds":    thresholds,
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

	sort.SliceStable(entries, func(i, j int) bool {
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

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)

	addr := "127.0.0.1:" + port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
