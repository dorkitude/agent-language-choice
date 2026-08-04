package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createMonsterHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug       string   `json:"slug"`
		Name       string   `json:"name"`
		CR         string   `json:"cr"`
		ArmorClass int      `json:"armor_class"`
		HitPoints  int      `json:"hit_points"`
		Tags       []string `json:"tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Slug) == "" {
		badRequest(w, "slug is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if strings.TrimSpace(req.CR) == "" {
		badRequest(w, "cr is required")
		return
	}
	if req.ArmorClass < 0 {
		badRequest(w, "armor_class must be non-negative")
		return
	}
	if req.HitPoints <= 0 {
		badRequest(w, "hit_points must be positive")
		return
	}

	m := &monster{
		Slug:       req.Slug,
		Name:       req.Name,
		CR:         req.CR,
		ArmorClass: req.ArmorClass,
		HitPoints:  req.HitPoints,
		Tags:       req.Tags,
	}

	if err := dbCreateMonster(m); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "monster slug already exists")
			return
		}
		log.Printf("create monster: %v", err)
		badRequest(w, "failed to create monster")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"slug":        m.Slug,
		"name":        m.Name,
		"cr":          m.CR,
		"armor_class": m.ArmorClass,
		"hit_points":  m.HitPoints,
	})
}

func getMonsterHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if slug == "" {
		notFound(w, "monster not found")
		return
	}

	m, err := dbGetMonster(slug)
	if err != nil {
		log.Printf("get monster: %v", err)
		notFound(w, "monster not found")
		return
	}
	if m == nil {
		notFound(w, "monster not found")
		return
	}

	writeJSON(w, http.StatusOK, m)
}

func createItemHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		Type   string `json:"type"`
		Rarity string `json:"rarity"`
		CostGP int    `json:"cost_gp"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Slug) == "" {
		badRequest(w, "slug is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if strings.TrimSpace(req.Type) == "" {
		badRequest(w, "type is required")
		return
	}
	if strings.TrimSpace(req.Rarity) == "" {
		badRequest(w, "rarity is required")
		return
	}
	if req.CostGP < 0 {
		badRequest(w, "cost_gp must be non-negative")
		return
	}

	i := &item{
		Slug:   req.Slug,
		Name:   req.Name,
		Type:   req.Type,
		Rarity: req.Rarity,
		CostGP: req.CostGP,
	}

	if err := dbCreateItem(i); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "item slug already exists")
			return
		}
		log.Printf("create item: %v", err)
		badRequest(w, "failed to create item")
		return
	}

	writeJSON(w, http.StatusCreated, i)
}

func getItemHandler(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if slug == "" {
		notFound(w, "item not found")
		return
	}

	i, err := dbGetItem(slug)
	if err != nil {
		log.Printf("get item: %v", err)
		notFound(w, "item not found")
		return
	}
	if i == nil {
		notFound(w, "item not found")
		return
	}

	writeJSON(w, http.StatusOK, i)
}
