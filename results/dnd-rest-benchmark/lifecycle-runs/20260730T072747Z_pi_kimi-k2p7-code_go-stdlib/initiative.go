package main

import (
	"encoding/json"
	"net/http"
	"sort"
)

type combatant struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

type initiativeRequest struct {
	Combatants []combatant `json:"combatants"`
}

type initiativeResult struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	Dex   int    `json:"-"`
}

type initiativeResponse struct {
	Order []initiativeResult `json:"order"`
}

// initiativeHandler sorts combatants by initiative score (roll + dex), then by
// dexterity score, and finally by name for deterministic tie-breaking.
func initiativeHandler(w http.ResponseWriter, r *http.Request) {
	var req initiativeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	results := make([]initiativeResult, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		results = append(results, initiativeResult{Name: c.Name, Score: c.Roll + c.Dex, Dex: c.Dex})
	}

	sort.Slice(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		if results[i].Dex != results[j].Dex {
			return results[i].Dex > results[j].Dex
		}
		return results[i].Name < results[j].Name
	})

	writeJSON(w, http.StatusOK, initiativeResponse{Order: results})
}
