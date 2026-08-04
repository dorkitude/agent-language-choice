package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type createMonsterRequest struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type monsterCreateResponse struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
}

type monsterResponse struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

// dbMonster is the raw row shape returned by sqlite3 for compendium_monsters.
// Tags are stored as a JSON string.
type dbMonster struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
	Tags       string `json:"tags"`
}

// itemRecord is both the request and response shape for compendium items.
type itemRecord struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

// queryMonsterExists returns true when a monster with the given slug exists.
func queryMonsterExists(slug string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM compendium_monsters WHERE slug=%s LIMIT 1;", sq(slug)))
}

// queryMonster loads a single monster by slug, parsing its stored tags JSON.
// It returns nil when the monster is not found.
func queryMonster(slug string) (*monsterResponse, error) {
	var rows []dbMonster
	if err := queryRows(fmt.Sprintf("SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug=%s LIMIT 1;", sq(slug)), &rows); err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, nil
	}
	r := rows[0]
	tags := []string{}
	if r.Tags != "" && r.Tags != "null" {
		if err := json.Unmarshal([]byte(r.Tags), &tags); err != nil {
			return nil, err
		}
	}
	return &monsterResponse{
		Slug:       r.Slug,
		Name:       r.Name,
		CR:         r.CR,
		ArmorClass: r.ArmorClass,
		HitPoints:  r.HitPoints,
		Tags:       tags,
	}, nil
}

// queryItemExists returns true when an item with the given slug exists.
func queryItemExists(slug string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM compendium_items WHERE slug=%s LIMIT 1;", sq(slug)))
}

// createMonsterHandler stores a new monster entry in the compendium. The slug
// must be unique, and the response omits the tags list to match the original
// contract.
func createMonsterHandler(w http.ResponseWriter, r *http.Request) {
	var req createMonsterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.CR == "" || req.ArmorClass <= 0 || req.HitPoints <= 0 {
		writeError(w, http.StatusBadRequest, "invalid monster")
		return
	}
	if req.Tags == nil {
		req.Tags = []string{}
	}
	tagsJSON, err := json.Marshal(req.Tags)
	if err != nil {
		log.Printf("monster tags marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryMonsterExists(req.Slug)
	if err != nil {
		log.Printf("monster exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "monster already exists")
		return
	}

	insertSQL := fmt.Sprintf("INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (%s, %s, %s, %d, %d, %s);",
		sq(req.Slug), sq(req.Name), sq(req.CR), req.ArmorClass, req.HitPoints, sq(string(tagsJSON)))
	if err := dbExec(insertSQL); err != nil {
		log.Printf("monster insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, monsterCreateResponse{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: req.ArmorClass,
		HitPoints:  req.HitPoints,
	})
}

// getMonsterHandler reads a single monster from the compendium.
func getMonsterHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if slug == "" {
		writeError(w, http.StatusBadRequest, "missing slug")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	monster, err := queryMonster(slug)
	if err != nil {
		log.Printf("monster get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if monster == nil {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}

	writeJSON(w, http.StatusOK, monster)
}

// createItemHandler stores a new item entry in the compendium. The slug must
// be unique and all fields must be positive/non-empty.
func createItemHandler(w http.ResponseWriter, r *http.Request) {
	var req itemRecord
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.Type == "" || req.Rarity == "" || req.CostGP <= 0 {
		writeError(w, http.StatusBadRequest, "invalid item")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryItemExists(req.Slug)
	if err != nil {
		log.Printf("item exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "item already exists")
		return
	}

	insertSQL := fmt.Sprintf("INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (%s, %s, %s, %s, %d);",
		sq(req.Slug), sq(req.Name), sq(req.Type), sq(req.Rarity), req.CostGP)
	if err := dbExec(insertSQL); err != nil {
		log.Printf("item insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, itemRecord{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: req.CostGP,
	})
}

// getItemHandler reads a single item from the compendium.
func getItemHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if slug == "" {
		writeError(w, http.StatusBadRequest, "missing slug")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	var items []itemRecord
	if err := queryRows(fmt.Sprintf("SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug=%s LIMIT 1;", sq(slug)), &items); err != nil {
		log.Printf("item get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(items) == 0 {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}

	writeJSON(w, http.StatusOK, items[0])
}
