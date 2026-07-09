package main

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
)

var dicePattern = regexp.MustCompile(`^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$`)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	addr := "127.0.0.1:" + port
	log.Fatal(http.ListenAndServe(addr, mux))
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	var req struct {
		Expression string `json:"expression"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	count, sides, modifier, err := parseDice(req.Expression)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	minimum := count + modifier
	maximum := count*sides + modifier
	average := float64(count*(1+sides))/2.0 + float64(modifier)

	writeJSON(w, http.StatusOK, struct {
		DiceCount int     `json:"dice_count"`
		Sides     int     `json:"sides"`
		Modifier  int     `json:"modifier"`
		Min       int     `json:"min"`
		Max       int     `json:"max"`
		Average   float64 `json:"average"`
	}{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       minimum,
		Max:       maximum,
		Average:   average,
	})
}

func parseDice(expression string) (int, int, int, error) {
	matches := dicePattern.FindStringSubmatch(expression)
	if matches == nil {
		return 0, 0, 0, errors.New("invalid dice expression")
	}

	count, err := strconv.Atoi(matches[1])
	if err != nil || count <= 0 {
		return 0, 0, 0, errors.New("invalid dice count")
	}

	sides, err := strconv.Atoi(matches[2])
	if err != nil || sides <= 0 {
		return 0, 0, 0, errors.New("invalid dice sides")
	}

	modifier := 0
	if matches[4] != "" {
		modifier, err = strconv.Atoi(matches[4])
		if err != nil {
			return 0, 0, 0, errors.New("invalid dice modifier")
		}
		if matches[3] == "-" {
			modifier = -modifier
		}
	}

	return count, sides, modifier, nil
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, struct {
		Total   int  `json:"total"`
		Success bool `json:"success"`
		Margin  int  `json:"margin"`
	}{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	var req struct {
		Party []struct {
			Level int `json:"level"`
		} `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, monster := range req.Monsters {
		xp, ok := monsterXP[monster.CR]
		if !ok || monster.Count < 0 {
			writeError(w, http.StatusBadRequest, "invalid monster")
			return
		}
		baseXP += xp * monster.Count
		monsterCount += monster.Count
	}

	thresholds := encounterThresholds{}
	for _, member := range req.Party {
		levelThresholds, ok := levelThresholds[member.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "invalid party level")
			return
		}
		thresholds.Easy += levelThresholds.Easy
		thresholds.Medium += levelThresholds.Medium
		thresholds.Hard += levelThresholds.Hard
		thresholds.Deadly += levelThresholds.Deadly
	}

	multiplier := monsterMultiplier(monsterCount)
	adjustedXP := int(math.Round(float64(baseXP) * multiplier))

	writeJSON(w, http.StatusOK, struct {
		BaseXP       int                 `json:"base_xp"`
		MonsterCount int                 `json:"monster_count"`
		Multiplier   float64             `json:"multiplier"`
		AdjustedXP   int                 `json:"adjusted_xp"`
		Difficulty   string              `json:"difficulty"`
		Thresholds   encounterThresholds `json:"thresholds"`
	}{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty(adjustedXP, thresholds),
		Thresholds:   thresholds,
	})
}

type encounterThresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
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

var levelThresholds = map[int]encounterThresholds{
	3: {Easy: 75, Medium: 150, Hard: 225, Deadly: 400},
}

func monsterMultiplier(count int) float64 {
	switch {
	case count <= 0:
		return 1
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

func difficulty(adjustedXP int, thresholds encounterThresholds) string {
	switch {
	case adjustedXP >= thresholds.Deadly:
		return "deadly"
	case adjustedXP >= thresholds.Hard:
		return "hard"
	case adjustedXP >= thresholds.Medium:
		return "medium"
	case adjustedXP >= thresholds.Easy:
		return "easy"
	default:
		return "trivial"
	}
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}

	type combatantOrder struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}

	order := make([]combatantOrder, 0, len(req.Combatants))
	for _, combatant := range req.Combatants {
		order = append(order, combatantOrder{
			Name:  combatant.Name,
			Score: combatant.Roll + combatant.Dex,
			dex:   combatant.Dex,
		})
	}

	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	writeJSON(w, http.StatusOK, struct {
		Order []combatantOrder `json:"order"`
	}{Order: order})
}

func decodeJSON(r *http.Request, target any) error {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("multiple json values")
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
	writeJSON(w, status, map[string]string{"error": message})
}
