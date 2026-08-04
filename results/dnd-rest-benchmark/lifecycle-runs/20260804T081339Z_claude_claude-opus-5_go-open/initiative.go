package main

import (
	"net/http"
	"sort"
)

// Initiative ordering, shared by the stateless POST /v1/initiative/order and by
// combat session creation, which freezes the same order into SQLite.

// combatantIn is the wire shape for a combatant. dex is optional and defaults
// to 0; name and roll are required, though how strictly is per-endpoint.
type combatantIn struct {
	Name *string `json:"name"`
	Dex  *int    `json:"dex"`
	Roll *int    `json:"roll"`
}

// combatantOut is the wire shape of an ordered combatant. Dex is an ordering
// input only and is deliberately not echoed back.
type combatantOut struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

// combatant is the resolved form: score is roll+dex, computed once so that
// re-sorting a persisted session cannot drift from the original ranking.
type combatant struct {
	Name  string
	Dex   int
	Score int
}

// resolveCombatant folds the optional dex into a total initiative score.
func resolveCombatant(name string, dex, roll int) combatant {
	return combatant{Name: name, Dex: dex, Score: roll + dex}
}

// sortInitiative ranks combatants by score descending, breaking ties by higher
// dexterity and then by name ascending. The name tiebreak makes the result a
// total order, so identical input always yields identical output.
func sortInitiative(entries []combatant) {
	sort.SliceStable(entries, func(i, j int) bool {
		a, b := entries[i], entries[j]
		if a.Score != b.Score {
			return a.Score > b.Score
		}
		if a.Dex != b.Dex {
			return a.Dex > b.Dex
		}
		return a.Name < b.Name
	})
}

// combatantsOut projects the ordered slice onto the wire shape, always as a
// list (never null) so an empty order renders as [].
func combatantsOut(entries []combatant) []combatantOut {
	out := make([]combatantOut, 0, len(entries))
	for _, c := range entries {
		out = append(out, combatantOut{Name: c.Name, Score: c.Score})
	}
	return out
}

// ---------- POST /v1/initiative/order ----------

type initiativeRequest struct {
	Combatants []combatantIn `json:"combatants"`
}

type initiativeResponse struct {
	Order []combatantOut `json:"order"`
}

// handleInitiative ranks a one-off list without storing anything. Unlike
// combat session creation it accepts an empty name and duplicate names, since
// there is no session state for a name to key into afterwards.
func handleInitiative(w http.ResponseWriter, r *http.Request) {
	var req initiativeRequest
	if !decodeBody(w, r, &req) {
		return
	}

	entries := make([]combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == nil || c.Roll == nil {
			writeError(w, http.StatusBadRequest, "combatant name and roll are required")
			return
		}
		dex := 0
		if c.Dex != nil {
			dex = *c.Dex
		}
		entries = append(entries, resolveCombatant(*c.Name, dex, *c.Roll))
	}

	sortInitiative(entries)
	writeJSON(w, http.StatusOK, initiativeResponse{Order: combatantsOut(entries)})
}
