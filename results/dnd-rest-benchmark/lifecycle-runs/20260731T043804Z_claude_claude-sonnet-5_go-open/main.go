// Command dndrest is an HTTP API for running Dungeons & Dragons 5e tabletop
// sessions: dice/rules math, character derivation, combat tracking, a
// monster/item compendium, campaign logs, and small DM-facing helpers.
//
// See CODEBASE.md for a map of the modules and how to extend them safely.
package main

import (
	"log"
	"net/http"
	"os"
)

// recoverMiddleware ensures a panic in any handler is turned into a 500
// response and a logged stack trace instead of silently killing the
// in-flight connection (which manifests to clients as an EOF) or, for a
// panic outside a recoverable request goroutine, the whole process.
func recoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("recovered panic serving %s %s: %v", r.Method, r.URL.Path, rec)
				writeError(w, http.StatusInternalServerError, "internal server error")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// newRouter builds the full HTTP route table. Routes that need a path
// parameter (session/campaign id, monster/item slug) are registered on
// their prefix and dispatched by a small per-group router, since
// http.ServeMux only supports prefix matching, not path templates.
func newRouter() *http.ServeMux {
	mux := http.NewServeMux()

	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/schema", schemaHandler)
	mux.HandleFunc("/healthz", livezHandler)
	mux.HandleFunc("/readyz", readyzHandler)

	// Core rules math.
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)

	// Character derivation.
	mux.HandleFunc("/v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("/v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("/v1/characters/derived-stats", derivedStatsHandler)

	// Combat session state.
	mux.HandleFunc("/v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("/v1/combat/sessions/", combatSessionsRouter)

	// Auth.
	mux.HandleFunc("/v1/auth/register", registerHandler)
	mux.HandleFunc("/v1/auth/login", loginHandler)

	// Storage introspection/admin.
	mux.HandleFunc("/v1/storage/status", storageStatusHandler)
	mux.HandleFunc("/v1/storage/reset", storageResetHandler)

	// Compendium (monsters, items).
	mux.HandleFunc("/v1/compendium/monsters", monstersRouter)
	mux.HandleFunc("/v1/compendium/monsters/", monstersRouter)
	mux.HandleFunc("/v1/compendium/items", itemsRouter)
	mux.HandleFunc("/v1/compendium/items/", itemsRouter)

	// Campaigns.
	mux.HandleFunc("/v1/campaigns", campaignsRouter)
	mux.HandleFunc("/v1/campaigns/", campaignsRouter)

	// Player's Handbook rules helpers.
	mux.HandleFunc("/v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("/v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("/v1/phb/equipment-load", equipmentLoadHandler)

	// DM tools.
	mux.HandleFunc("/v1/dm/encounter-builder", encounterBuilderHandler)
	mux.HandleFunc("/v1/dm/loot-parcel", lootParcelHandler)
	mux.HandleFunc("/v1/dm/session-recap", sessionRecapHandler)

	// Protected campaign-play surface.
	mux.HandleFunc("/v1/play/campaigns", playRouter)
	mux.HandleFunc("/v1/play/campaigns/", playRouter)

	return mux
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	initStorage()

	addr := "127.0.0.1:" + port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, recoverMiddleware(newRouter())); err != nil {
		log.Fatal(err)
	}
}
