package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
)

type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

var (
	compendiumMu sync.Mutex
	monsterStore = map[string]*monster{}
	itemStore    = map[string]*item{}
)

func monsterCreateResponse(m *monster) map[string]interface{} {
	return map[string]interface{}{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
	}
}

func monsterReadResponse(m *monster) map[string]interface{} {
	tags := m.Tags
	if tags == nil {
		tags = []string{}
	}
	return map[string]interface{}{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
		"tags":        tags,
	}
}

func itemResponse(it *item) map[string]interface{} {
	return map[string]interface{}{
		"slug":    it.Slug,
		"name":    it.Name,
		"type":    it.Type,
		"rarity":  it.Rarity,
		"cost_gp": it.CostGP,
	}
}

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
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.CR == "" {
		writeError(w, http.StatusBadRequest, "slug, name, and cr are required")
		return
	}
	if req.ArmorClass == nil || req.HitPoints == nil {
		writeError(w, http.StatusBadRequest, "armor_class and hit_points are required")
		return
	}

	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}

	compendiumMu.Lock()
	if _, exists := monsterStore[req.Slug]; exists {
		compendiumMu.Unlock()
		writeError(w, http.StatusConflict, "monster slug already exists")
		return
	}
	m := &monster{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: *req.ArmorClass,
		HitPoints:  *req.HitPoints,
		Tags:       tags,
	}
	monsterStore[req.Slug] = m
	compendiumMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, monsterCreateResponse(m))
}

func handleReadMonster(w http.ResponseWriter, r *http.Request) {
	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/monsters/")
	if slug == "" {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}

	compendiumMu.Lock()
	m, exists := monsterStore[slug]
	compendiumMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "monster not found")
		return
	}

	writeJSON(w, http.StatusOK, monsterReadResponse(m))
}

func handleMonstersCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleCreateMonster(w, r)
}

func handleMonstersItem(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleReadMonster(w, r)
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
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Slug == "" || req.Name == "" || req.Type == "" || req.Rarity == "" {
		writeError(w, http.StatusBadRequest, "slug, name, type, and rarity are required")
		return
	}
	if req.CostGP == nil || *req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "cost_gp must be a non-negative integer")
		return
	}

	compendiumMu.Lock()
	if _, exists := itemStore[req.Slug]; exists {
		compendiumMu.Unlock()
		writeError(w, http.StatusConflict, "item slug already exists")
		return
	}
	it := &item{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: *req.CostGP,
	}
	itemStore[req.Slug] = it
	compendiumMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, itemResponse(it))
}

func handleReadItem(w http.ResponseWriter, r *http.Request) {
	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/items/")
	if slug == "" {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}

	compendiumMu.Lock()
	it, exists := itemStore[slug]
	compendiumMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "item not found")
		return
	}

	writeJSON(w, http.StatusOK, itemResponse(it))
}

func handleItemsCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleCreateItem(w, r)
}

func handleItemsItem(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleReadItem(w, r)
}
