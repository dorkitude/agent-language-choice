package main

import (
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

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req initiativeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	type scored struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		Dex   int    `json:"-"`
	}

	results := make([]scored, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		results = append(results, scored{Name: c.Name, Score: c.Roll + c.Dex, Dex: c.Dex})
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

	writeJSON(w, http.StatusOK, map[string]any{"order": results})
}
