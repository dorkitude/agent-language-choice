package main

import (
	"encoding/json"
	"net/http"
	"sort"
)

func handleInitiativeOrder(w http.ResponseWriter, r *http.Request) {
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

	type ordered struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}

	order := make([]ordered, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, ordered{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex})
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

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"order": order,
	})
}
