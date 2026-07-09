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

var diceRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

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

type thresholds struct {
	Easy    int `json:"easy"`
	Medium  int `json:"medium"`
	Hard    int `json:"hard"`
	Deadly  int `json:"deadly"`
}

var levelThresholds = map[int]thresholds{
	3: {Easy: 75, Medium: 150, Hard: 225, Deadly: 400},
}

type initiativeEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

type initiativeResp struct {
	Order []initiativeEntry `json:"order"`
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
	log.Printf("listening on 127.0.0.1:%s", port)
	log.Fatal(http.ListenAndServe("127.0.0.1:"+port, mux))
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": "bad request"})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func parseDice(expr string) (count, sides, modifier int, ok bool) {
	m := diceRe.FindStringSubmatch(expr)
	if m == nil {
		return 0, 0, 0, false
	}
	count, err1 := strconv.Atoi(m[1])
	sides, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil {
		return 0, 0, 0, false
	}
	if count <= 0 || sides <= 0 {
		return 0, 0, 0, false
	}
	modifier = 0
	if m[3] != "" {
		mod, err := strconv.Atoi(m[3])
		if err != nil {
			return 0, 0, 0, false
		}
		modifier = mod
	}
	return count, sides, modifier, true
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}
	count, sides, modifier, ok := parseDice(req.Expression)
	if !ok {
		writeError(w, http.StatusBadRequest)
		return
	}
	min := count + modifier
	max := count*sides + modifier
	avg := float64(count)*float64(sides+1)/2 + float64(modifier)
	resp := struct {
		DiceCount int     `json:"dice_count"`
		Sides     int     `json:"sides"`
		Modifier  int     `json:"modifier"`
		Min       int     `json:"min"`
		Max       int     `json:"max"`
		Average   float64 `json:"average"`
	}{count, sides, modifier, min, max, avg}
	writeJSON(w, http.StatusOK, resp)
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}
	total := req.Roll + req.Modifier
	resp := struct {
		Total   int  `json:"total"`
		Success bool `json:"success"`
		Margin  int  `json:"margin"`
	}{total, total >= req.DC, total - req.DC}
	writeJSON(w, http.StatusOK, resp)
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
		writeError(w, http.StatusBadRequest)
		return
	}
	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			writeError(w, http.StatusBadRequest)
			return
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}
	mult := monsterMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * mult

	var t thresholds
	for _, p := range req.Party {
		pt, ok := levelThresholds[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest)
			return
		}
		t.Easy += pt.Easy
		t.Medium += pt.Medium
		t.Hard += pt.Hard
		t.Deadly += pt.Deadly
	}

	difficulty := "trivial"
	switch {
	case adjustedXP >= float64(t.Deadly):
		difficulty = "deadly"
	case adjustedXP >= float64(t.Hard):
		difficulty = "hard"
	case adjustedXP >= float64(t.Medium):
		difficulty = "medium"
	case adjustedXP >= float64(t.Easy):
		difficulty = "easy"
	}

	resp := struct {
		BaseXP       int         `json:"base_xp"`
		MonsterCount int         `json:"monster_count"`
		Multiplier   float64     `json:"multiplier"`
		AdjustedXP   float64     `json:"adjusted_xp"`
		Difficulty   string      `json:"difficulty"`
		Thresholds   thresholds  `json:"thresholds"`
	}{baseXP, monsterCount, mult, adjustedXP, difficulty, t}
	writeJSON(w, http.StatusOK, resp)
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
		writeError(w, http.StatusBadRequest)
		return
	}
	type combatant struct {
		Name  string
		Dex   int
		Score int
	}
	cs := make([]combatant, len(req.Combatants))
	for i, c := range req.Combatants {
		cs[i] = combatant{c.Name, c.Dex, c.Roll + c.Dex}
	}
	sort.SliceStable(cs, func(i, j int) bool {
		a, b := cs[i], cs[j]
		if a.Score != b.Score {
			return a.Score > b.Score
		}
		if a.Dex != b.Dex {
			return a.Dex > b.Dex
		}
		return a.Name < b.Name
	})
	order := make([]initiativeEntry, len(cs))
	for i, c := range cs {
		order[i] = initiativeEntry{c.Name, c.Score}
	}
	writeJSON(w, http.StatusOK, initiativeResp{order})
}
