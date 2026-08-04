package main

import (
	"encoding/json"
	"net/http"
	"sync"
)

// Game-world compendium: monsters and items, each keyed by a caller-supplied
// slug. Entries are create-and-read only — there is no update or delete — so a
// slug that exists is a permanent conflict until storage is reset.
//
// Entries live in memory and are mirrored to SQLite after each write; the
// in-memory maps are authoritative for reads (see store.go).

type monsterEntry struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type itemEntry struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

type compendiumStore struct {
	mu       sync.Mutex
	monsters map[string]*monsterEntry
	items    map[string]*itemEntry
}

var compendium = &compendiumStore{
	monsters: map[string]*monsterEntry{},
	items:    map[string]*itemEntry{},
}

// ---------- request payloads ----------

type monsterRequest struct {
	Slug       *string          `json:"slug"`
	Name       *string          `json:"name"`
	CR         *json.RawMessage `json:"cr"`
	ArmorClass *json.RawMessage `json:"armor_class"`
	HitPoints  *json.RawMessage `json:"hit_points"`
	Tags       []string         `json:"tags"`
}

type itemRequest struct {
	Slug   *string          `json:"slug"`
	Name   *string          `json:"name"`
	Type   *string          `json:"type"`
	Rarity *string          `json:"rarity"`
	CostGP *json.RawMessage `json:"cost_gp"`
}

// ---------- POST /v1/compendium/monsters ----------

func handleCreateMonster(w http.ResponseWriter, r *http.Request) {
	var req monsterRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	slug, ok := requiredString(req.Slug)
	if !ok {
		writeError(w, http.StatusBadRequest, "slug is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	cr, ok := crKey(req.CR)
	if !ok || cr == "" {
		writeError(w, http.StatusBadRequest, "cr is required")
		return
	}
	ac, ok := asInt(req.ArmorClass)
	if !ok {
		writeError(w, http.StatusBadRequest, "armor_class must be an integer")
		return
	}
	hp, ok := asInt(req.HitPoints)
	if !ok {
		writeError(w, http.StatusBadRequest, "hit_points must be an integer")
		return
	}

	entry := &monsterEntry{
		Slug:       slug,
		Name:       name,
		CR:         cr,
		ArmorClass: ac,
		HitPoints:  hp,
		Tags:       append([]string{}, req.Tags...),
	}

	compendium.mu.Lock()
	if _, exists := compendium.monsters[slug]; exists {
		compendium.mu.Unlock()
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}
	compendium.monsters[slug] = entry
	compendium.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, entry)
}

// ---------- GET /v1/compendium/monsters/{slug} ----------

func handleGetMonster(w http.ResponseWriter, r *http.Request) {
	compendium.mu.Lock()
	entry, ok := compendium.monsters[r.PathValue("slug")]
	compendium.mu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}
	writeJSON(w, http.StatusOK, entry)
}

// ---------- POST /v1/compendium/items ----------

func handleCreateItem(w http.ResponseWriter, r *http.Request) {
	var req itemRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	slug, ok := requiredString(req.Slug)
	if !ok {
		writeError(w, http.StatusBadRequest, "slug is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	typ, ok := requiredString(req.Type)
	if !ok {
		writeError(w, http.StatusBadRequest, "type is required")
		return
	}
	rarity, ok := requiredString(req.Rarity)
	if !ok {
		writeError(w, http.StatusBadRequest, "rarity is required")
		return
	}
	cost, ok := asInt(req.CostGP)
	if !ok {
		writeError(w, http.StatusBadRequest, "cost_gp must be an integer")
		return
	}

	entry := &itemEntry{Slug: slug, Name: name, Type: typ, Rarity: rarity, CostGP: cost}

	compendium.mu.Lock()
	if _, exists := compendium.items[slug]; exists {
		compendium.mu.Unlock()
		writeError(w, http.StatusConflict, "item slug already exists")
		return
	}
	compendium.items[slug] = entry
	compendium.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, entry)
}

// ---------- GET /v1/compendium/items/{slug} ----------

func handleGetItem(w http.ResponseWriter, r *http.Request) {
	compendium.mu.Lock()
	entry, ok := compendium.items[r.PathValue("slug")]
	compendium.mu.Unlock()
	if !ok {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}
	writeJSON(w, http.StatusOK, entry)
}
