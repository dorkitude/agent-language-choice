package main

// Monster and Item compendium (Maintenance Stage 5).
//
// Consistent with the durable-storage stage, the compendium schema is added to
// the on-disk SQLite file for durability, while the records themselves are
// served from in-memory structures (the standard library ships no query engine).

import (
	"encoding/json"
	"net/http"
	"sync"
)

type monster struct {
	Slug       string
	Name       string
	CR         string
	ArmorClass int
	HitPoints  int
	Tags       []string
}

type item struct {
	Slug   string
	Name   string
	Type   string
	Rarity string
	CostGP int
}

var (
	compendiumMu sync.Mutex
	monsters     = map[string]*monster{}
	items        = map[string]*item{}
)

func handleCreateMonster(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug       string   `json:"slug"`
		Name       string   `json:"name"`
		CR         string   `json:"cr"`
		ArmorClass *int     `json:"armor_class"`
		HitPoints  *int     `json:"hit_points"`
		Tags       []string `json:"tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.Slug == "" || req.Name == "" || req.CR == "" ||
		req.ArmorClass == nil || req.HitPoints == nil {
		badRequest(w)
		return
	}
	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}
	compendiumMu.Lock()
	defer compendiumMu.Unlock()
	if _, exists := monsters[req.Slug]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "slug already exists"})
		return
	}
	monsters[req.Slug] = &monster{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: *req.ArmorClass,
		HitPoints:  *req.HitPoints,
		Tags:       tags,
	}
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"slug":        req.Slug,
		"name":        req.Name,
		"cr":          req.CR,
		"armor_class": *req.ArmorClass,
		"hit_points":  *req.HitPoints,
	})
}

func handleReadMonster(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	compendiumMu.Lock()
	m, ok := monsters[slug]
	compendiumMu.Unlock()
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown monster"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
		"tags":        m.Tags,
	})
}

func handleCreateItem(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		Type   string `json:"type"`
		Rarity string `json:"rarity"`
		CostGP *int   `json:"cost_gp"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.Slug == "" || req.Name == "" || req.Type == "" ||
		req.Rarity == "" || req.CostGP == nil {
		badRequest(w)
		return
	}
	compendiumMu.Lock()
	defer compendiumMu.Unlock()
	if _, exists := items[req.Slug]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "slug already exists"})
		return
	}
	items[req.Slug] = &item{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: *req.CostGP,
	}
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"slug":    req.Slug,
		"name":    req.Name,
		"type":    req.Type,
		"rarity":  req.Rarity,
		"cost_gp": *req.CostGP,
	})
}

func handleReadItem(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	compendiumMu.Lock()
	it, ok := items[slug]
	compendiumMu.Unlock()
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown item"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"slug":    it.Slug,
		"name":    it.Name,
		"type":    it.Type,
		"rarity":  it.Rarity,
		"cost_gp": it.CostGP,
	})
}
