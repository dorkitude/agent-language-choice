package main

import (
	"net/http"
	"regexp"
	"sync"
)

// slugRe validates the URL-safe slug format shared by monsters and items.
var slugRe = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)

type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

// monstersMu guards monsters, the in-memory index mirroring the monsters table.
var (
	monstersMu sync.Mutex
	monsters   = map[string]*monster{}
)

type createMonsterRequest struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass *int     `json:"armor_class"`
	HitPoints  *int     `json:"hit_points"`
	Tags       []string `json:"tags"`
}

func createMonsterHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createMonsterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be lowercase alphanumeric with hyphen separators")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.CR == "" {
		writeError(w, http.StatusBadRequest, "cr is required")
		return
	}
	if req.ArmorClass == nil || *req.ArmorClass < 0 {
		writeError(w, http.StatusBadRequest, "armor_class must be a non-negative integer")
		return
	}
	if req.HitPoints == nil || *req.HitPoints < 0 {
		writeError(w, http.StatusBadRequest, "hit_points must be a non-negative integer")
		return
	}
	tags := req.Tags
	if tags == nil {
		tags = []string{}
	}

	monstersMu.Lock()
	defer monstersMu.Unlock()

	if _, exists := monsters[req.Slug]; exists {
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
	if err := saveMonsterToDB(m); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save monster")
		return
	}
	monsters[m.Slug] = m

	writeJSON(w, http.StatusCreated, map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
	})
}

func getMonsterHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	slug, ok := extractSessionID(r.URL.Path, "/v1/compendium/monsters/", "")
	if !ok || slug == "" {
		writeError(w, http.StatusNotFound, "unknown monster slug")
		return
	}

	monstersMu.Lock()
	m, exists := monsters[slug]
	monstersMu.Unlock()

	if !exists {
		writeError(w, http.StatusNotFound, "unknown monster slug")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
		"tags":        m.Tags,
	})
}

func monstersRouter(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/v1/compendium/monsters" {
		createMonsterHandler(w, r)
		return
	}
	getMonsterHandler(w, r)
}

type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

// itemsMu guards items, the in-memory index mirroring the items table.
var (
	itemsMu sync.Mutex
	items   = map[string]*item{}
)

type createItemRequest struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP *int   `json:"cost_gp"`
}

func createItemHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createItemRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !slugRe.MatchString(req.Slug) {
		writeError(w, http.StatusBadRequest, "slug must be lowercase alphanumeric with hyphen separators")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Type == "" {
		writeError(w, http.StatusBadRequest, "type is required")
		return
	}
	if req.Rarity == "" {
		writeError(w, http.StatusBadRequest, "rarity is required")
		return
	}
	if req.CostGP == nil || *req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "cost_gp must be a non-negative integer")
		return
	}

	itemsMu.Lock()
	defer itemsMu.Unlock()

	if _, exists := items[req.Slug]; exists {
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
	if err := saveItemToDB(it); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save item")
		return
	}
	items[it.Slug] = it

	writeJSON(w, http.StatusCreated, map[string]any{
		"slug":    it.Slug,
		"name":    it.Name,
		"type":    it.Type,
		"rarity":  it.Rarity,
		"cost_gp": it.CostGP,
	})
}

func getItemHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	slug, ok := extractSessionID(r.URL.Path, "/v1/compendium/items/", "")
	if !ok || slug == "" {
		writeError(w, http.StatusNotFound, "unknown item slug")
		return
	}

	itemsMu.Lock()
	it, exists := items[slug]
	itemsMu.Unlock()

	if !exists {
		writeError(w, http.StatusNotFound, "unknown item slug")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"slug":    it.Slug,
		"name":    it.Name,
		"type":    it.Type,
		"rarity":  it.Rarity,
		"cost_gp": it.CostGP,
	})
}

func itemsRouter(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/v1/compendium/items" {
		createItemHandler(w, r)
		return
	}
	getItemHandler(w, r)
}
