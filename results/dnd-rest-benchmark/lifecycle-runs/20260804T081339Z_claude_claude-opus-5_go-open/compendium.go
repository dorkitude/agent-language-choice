package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
)

// The compendium holds the static game world: monster stat blocks and item
// entries, both keyed by a human-readable slug and stored in SQLite.
//
// Both families follow the same create/read shape. Fields other than slug and
// name are optional and fall back to a zero value rather than a 400, because
// the compendium is a scratchpad a DM fills in over time. Slugs are trimmed;
// names are stored exactly as sent.

// ---------- monsters ----------

type monsterRequest struct {
	Slug       *string     `json:"slug"`
	Name       *string     `json:"name"`
	CR         *flexString `json:"cr"`
	ArmorClass *int        `json:"armor_class"`
	HitPoints  *int        `json:"hit_points"`
	Tags       []string    `json:"tags"`
}

// monsterCreated is the create response, which reports the stat block without
// echoing the tag list.
type monsterCreated struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
}

// monsterFull is the read response and does include the tags.
type monsterFull struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

// POST /v1/compendium/monsters
func handleMonsters(w http.ResponseWriter, r *http.Request) {
	var req monsterRequest
	if !decodeBody(w, r, &req) {
		return
	}
	slug, ok := requireField(w, req.Slug, "slug")
	if !ok {
		return
	}
	if _, ok := requireField(w, req.Name, "name"); !ok {
		return
	}
	out := monsterCreated{Slug: slug, Name: *req.Name}
	if req.CR != nil {
		out.CR = string(*req.CR)
	}
	if req.ArmorClass != nil {
		out.ArmorClass = *req.ArmorClass
	}
	if req.HitPoints != nil {
		out.HitPoints = *req.HitPoints
	}

	// Tags round-trip as a JSON array in a TEXT column; a missing list stores [].
	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}
	encoded, err := json.Marshal(tags)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid tags")
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if exists, err := slugExists("monsters", slug); err != nil {
		writeStorageFailure(w, "monster lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}
	if _, err := db.Exec(
		`INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)`,
		out.Slug, out.Name, out.CR, out.ArmorClass, out.HitPoints, string(encoded),
	); err != nil {
		// The realistic failure is a primary-key collision that raced the check
		// above, so it reports as a conflict rather than a server fault.
		log.Printf("monster insert failed: %v", err)
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// GET /v1/compendium/monsters/{slug}
func handleMonsterBySlug(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	slug, ok := requirePathValue(w, r, "slug", "slug")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var out monsterFull
	var rawTags string
	err := db.QueryRow(
		`SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?`, slug,
	).Scan(&out.Slug, &out.Name, &out.CR, &out.ArmorClass, &out.HitPoints, &rawTags)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "monster read failed", err)
		return
	}
	out.Tags = decodeTags(rawTags)
	writeJSON(w, http.StatusOK, out)
}

// ---------- items ----------

type itemRequest struct {
	Slug   *string  `json:"slug"`
	Name   *string  `json:"name"`
	Type   *string  `json:"type"`
	Rarity *string  `json:"rarity"`
	CostGP *float64 `json:"cost_gp"`
}

// itemResponse serves as both the create and the read response.
type itemResponse struct {
	Slug   string  `json:"slug"`
	Name   string  `json:"name"`
	Type   string  `json:"type"`
	Rarity string  `json:"rarity"`
	CostGP float64 `json:"cost_gp"`
}

// POST /v1/compendium/items
func handleItems(w http.ResponseWriter, r *http.Request) {
	var req itemRequest
	if !decodeBody(w, r, &req) {
		return
	}
	slug, ok := requireField(w, req.Slug, "slug")
	if !ok {
		return
	}
	if _, ok := requireField(w, req.Name, "name"); !ok {
		return
	}
	out := itemResponse{Slug: slug, Name: *req.Name}
	if req.Type != nil {
		out.Type = *req.Type
	}
	if req.Rarity != nil {
		out.Rarity = *req.Rarity
	}
	if req.CostGP != nil {
		out.CostGP = *req.CostGP
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if exists, err := slugExists("items", slug); err != nil {
		writeStorageFailure(w, "item lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "item slug already exists")
		return
	}
	if _, err := db.Exec(
		`INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)`,
		out.Slug, out.Name, out.Type, out.Rarity, out.CostGP,
	); err != nil {
		log.Printf("item insert failed: %v", err)
		writeError(w, http.StatusConflict, "item slug already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// GET /v1/compendium/items/{slug}
func handleItemBySlug(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	slug, ok := requirePathValue(w, r, "slug", "slug")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var out itemResponse
	err := db.QueryRow(
		`SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?`, slug,
	).Scan(&out.Slug, &out.Name, &out.Type, &out.Rarity, &out.CostGP)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "item read failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// ---------- shared helpers ----------

// slugExists reports whether table already holds the slug. table is a literal
// from this file only, never request data, so interpolating it is safe.
func slugExists(table, slug string) (bool, error) {
	return rowExists(`SELECT 1 FROM `+table+` WHERE slug = ?`, slug)
}

// decodeTags reads the stored tags column, degrading to an empty list rather
// than an error so one malformed row cannot make a monster unreadable.
func decodeTags(raw string) []string {
	tags := []string{}
	if raw == "" {
		return tags
	}
	if err := json.Unmarshal([]byte(raw), &tags); err != nil || tags == nil {
		return []string{}
	}
	return tags
}
