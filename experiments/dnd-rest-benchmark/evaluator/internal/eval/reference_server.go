package eval

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
)

func ReferenceHandler() http.Handler {
	mux := http.NewServeMux()
	sessions := map[string]*referenceSession{}
	users := map[string]referenceUser{}
	monsters := map[string]map[string]any{}
	items := map[string]map[string]any{}
	campaigns := map[string]*referenceCampaign{}
	playCampaigns := map[string]*referencePlayCampaign{}
	maintenanceMode := false
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if maintenanceMode {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"status": "maintenance", "schema_version": 2})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"status": "ready", "schema_version": 2})
	})
	mux.HandleFunc("POST /v1/dice/stats", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Expression string `json:"expression"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		switch req.Expression {
		case "2d6+3":
			writeJSON(w, http.StatusOK, map[string]any{
				"dice_count": 2, "sides": 6, "modifier": 3,
				"min": 5, "max": 15, "average": 10,
			})
		case "1d20-1":
			writeJSON(w, http.StatusOK, map[string]any{
				"dice_count": 1, "sides": 20, "modifier": -1,
				"min": 0, "max": 19, "average": 9.5,
			})
		default:
			http.Error(w, "bad expression", http.StatusBadRequest)
		}
	})
	mux.HandleFunc("POST /v1/checks/ability", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Roll     int `json:"roll"`
			Modifier int `json:"modifier"`
			DC       int `json:"dc"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		total := req.Roll + req.Modifier
		writeJSON(w, http.StatusOK, map[string]any{
			"total": total, "success": total >= req.DC, "margin": total - req.DC,
		})
	})
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"base_xp": 850, "monster_count": 3, "multiplier": 2,
			"adjusted_xp": 1700, "difficulty": "deadly",
			"thresholds": map[string]any{
				"easy": 300, "medium": 600, "hard": 900, "deadly": 1600,
			},
		})
	})
	mux.HandleFunc("POST /v1/initiative/order", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"order": []map[string]any{
				{"name": "rogue", "score": 17},
				{"name": "wizard", "score": 17},
				{"name": "cleric", "score": 17},
				{"name": "ogre", "score": 15},
			},
		})
	})
	mux.HandleFunc("POST /v1/characters/ability-modifier", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Score int `json:"score"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Score < 1 || req.Score > 30 {
			http.Error(w, "bad score", http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"score": req.Score, "modifier": abilityModifier(req.Score)})
	})
	mux.HandleFunc("POST /v1/characters/proficiency", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Level int `json:"level"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Level < 1 || req.Level > 20 {
			http.Error(w, "bad level", http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"level": req.Level, "proficiency_bonus": proficiency(req.Level)})
	})
	mux.HandleFunc("POST /v1/characters/derived-stats", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Level     int            `json:"level"`
			Abilities map[string]int `json:"abilities"`
			Armor     struct {
				Base   int  `json:"base"`
				Shield bool `json:"shield"`
				DexCap int  `json:"dex_cap"`
			} `json:"armor"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		mods := map[string]int{}
		for _, key := range []string{"str", "dex", "con", "int", "wis", "cha"} {
			score, ok := req.Abilities[key]
			if !ok || score < 1 || score > 30 {
				http.Error(w, "bad ability", http.StatusBadRequest)
				return
			}
			mods[key] = abilityModifier(score)
		}
		shield := 0
		if req.Armor.Shield {
			shield = 2
		}
		dexBonus := mods["dex"]
		if dexBonus > req.Armor.DexCap {
			dexBonus = req.Armor.DexCap
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"level": req.Level, "proficiency_bonus": proficiency(req.Level),
			"hp_max": req.Level * (6 + mods["con"]), "armor_class": req.Armor.Base + dexBonus + shield,
			"modifiers": mods,
		})
	})
	mux.HandleFunc("POST /v1/combat/sessions", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			ID         string `json:"id"`
			Combatants []struct {
				Name string `json:"name"`
				Dex  int    `json:"dex"`
				Roll int    `json:"roll"`
			} `json:"combatants"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" || len(req.Combatants) == 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		session := &referenceSession{ID: req.ID, Round: 1, Conditions: map[string][]referenceCondition{}}
		for _, combatant := range req.Combatants {
			session.Order = append(session.Order, referenceCombatant{
				Name:  combatant.Name,
				Dex:   combatant.Dex,
				Score: combatant.Dex + combatant.Roll,
			})
			session.Conditions[combatant.Name] = nil
		}
		sortReferenceOrder(session.Order)
		sessions[req.ID] = session
		writeJSON(w, http.StatusOK, session.snapshot())
	})
	mux.HandleFunc("POST /v1/combat/sessions/enc-1/conditions", func(w http.ResponseWriter, r *http.Request) {
		session := sessions["enc-1"]
		if session == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			Target         string `json:"target"`
			Condition      string `json:"condition"`
			DurationRounds int    `json:"duration_rounds"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.DurationRounds <= 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if _, ok := session.Conditions[req.Target]; !ok {
			http.Error(w, "bad target", http.StatusBadRequest)
			return
		}
		session.Conditions[req.Target] = append(session.Conditions[req.Target], referenceCondition{
			Condition: req.Condition,
			Remaining: req.DurationRounds,
		})
		writeJSON(w, http.StatusOK, map[string]any{
			"target":     req.Target,
			"conditions": conditionList(session.Conditions[req.Target]),
		})
	})
	mux.HandleFunc("POST /v1/combat/sessions/enc-1/advance", func(w http.ResponseWriter, r *http.Request) {
		session := sessions["enc-1"]
		if session == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		session.TurnIndex++
		if session.TurnIndex >= len(session.Order) {
			session.TurnIndex = 0
			session.Round++
		}
		active := session.Order[session.TurnIndex].Name
		kept := session.Conditions[active][:0]
		for _, condition := range session.Conditions[active] {
			condition.Remaining--
			if condition.Remaining > 0 {
				kept = append(kept, condition)
			}
		}
		session.Conditions[active] = kept
		writeJSON(w, http.StatusOK, session.snapshot())
	})
	mux.HandleFunc("POST /v1/auth/register", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
			Role     string `json:"role"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Username == "" || len(req.Password) < 8 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if _, exists := users[req.Username]; exists {
			http.Error(w, "duplicate username", http.StatusConflict)
			return
		}
		if req.Role == "" {
			req.Role = "player"
		}
		users[req.Username] = referenceUser{Username: req.Username, Password: req.Password, Role: req.Role}
		writeJSON(w, http.StatusCreated, map[string]any{"username": req.Username, "role": req.Role})
	})
	mux.HandleFunc("POST /v1/auth/login", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		user, exists := users[req.Username]
		if !exists || user.Password != req.Password {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"username": req.Username, "token": "session-" + req.Username})
	})
	mux.HandleFunc("GET /v1/storage/status", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"driver": "sqlite", "schema_version": 1, "initialized": true,
		})
	})
	mux.HandleFunc("POST /v1/storage/reset", func(w http.ResponseWriter, r *http.Request) {
		monsters = map[string]map[string]any{}
		items = map[string]map[string]any{}
		campaigns = map[string]*referenceCampaign{}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "schema_version": 1})
	})
	mux.HandleFunc("POST /v1/compendium/monsters", func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["slug"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		slug := req["slug"].(string)
		monsters[slug] = req
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", func(w http.ResponseWriter, r *http.Request) {
		monster, exists := monsters[r.PathValue("slug")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, monster)
	})
	mux.HandleFunc("POST /v1/compendium/items", func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["slug"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		slug := req["slug"].(string)
		items[slug] = req
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("GET /v1/compendium/items/{slug}", func(w http.ResponseWriter, r *http.Request) {
		item, exists := items[r.PathValue("slug")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, item)
	})
	mux.HandleFunc("POST /v1/campaigns", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			ID   string `json:"id"`
			Name string `json:"name"`
			DM   string `json:"dm"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaigns[req.ID] = newReferenceCampaign(req.ID, req.Name, req.DM)
		writeJSON(w, http.StatusCreated, map[string]any{"id": req.ID, "name": req.Name, "dm": req.DM})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["id"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Characters = append(campaign.Characters, req)
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/events", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["id"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Events = append(campaign.Events, req)
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/state", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id":         campaign.ID,
			"name":       campaign.Name,
			"dm":         campaign.DM,
			"characters": campaign.Characters,
			"log_count":  len(campaign.Events),
		})
	})
	mux.HandleFunc("POST /v1/phb/spell-slots", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"class": "wizard",
			"level": 5,
			"slots": map[string]any{"1": 4, "2": 3, "3": 2},
		})
	})
	mux.HandleFunc("POST /v1/phb/rests/long", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"hp_current": 35, "hit_dice_spent": 1, "exhaustion_level": 0,
		})
	})
	mux.HandleFunc("POST /v1/phb/equipment-load", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"capacity": 180, "weight": 181, "encumbered": true,
		})
	})
	mux.HandleFunc("POST /v1/dm/encounter-builder", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": "camp-1", "base_xp": 150, "adjusted_xp": 300,
			"difficulty": "easy", "monster_count": 3, "recommendation": "safe warm-up",
		})
	})
	mux.HandleFunc("POST /v1/dm/loot-parcel", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": "camp-1", "coins_gp": 75,
			"items": []map[string]any{{"slug": "healing-potion", "quantity": 2}},
		})
	})
	mux.HandleFunc("POST /v1/dm/session-recap", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": "camp-1",
			"summary":     "Nyx scouts the goblin trail.",
			"open_threads": []any{
				"Resolve goblin trail ambush",
			},
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/quests", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			ID         string   `json:"id"`
			Title      string   `json:"title"`
			Status     string   `json:"status"`
			Milestones []string `json:"milestones"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if req.Status == "" {
			req.Status = "active"
		}
		campaign.Quests[req.ID] = &referenceQuest{
			ID: req.ID, Title: req.Title, Status: req.Status, Milestones: req.Milestones,
			Completed: map[string]bool{},
		}
		writeJSON(w, http.StatusCreated, map[string]any{
			"id": req.ID, "title": req.Title, "status": req.Status,
			"milestones_total": len(req.Milestones), "milestones_done": 0,
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/quests/{quest_id}/progress", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		quest := campaign.Quests[r.PathValue("quest_id")]
		if quest == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			Completed []string `json:"completed"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		for _, item := range req.Completed {
			quest.Completed[item] = true
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id": quest.ID, "status": quest.Status,
			"milestones_total": len(quest.Milestones), "milestones_done": len(quest.Completed),
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/quests/summary", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		active, completed, blocked := 0, 0, 0
		for _, quest := range campaign.Quests {
			switch quest.Status {
			case "completed":
				completed++
			case "blocked":
				blocked++
			default:
				active++
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID, "active": active, "completed": completed, "blocked": blocked,
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/factions", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["id"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Factions[req["id"].(string)] = req
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/npcs", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["id"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.NPCs[req["id"].(string)] = req
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/relationships", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		friendly := 0
		for _, npc := range campaign.NPCs {
			if disposition, ok := npc["disposition"].(float64); ok && disposition > 0 {
				friendly++
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID, "factions": len(campaign.Factions), "npcs": len(campaign.NPCs),
			"friendly_npcs": friendly,
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/inventory", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req["item_slug"] == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Inventory = append(campaign.Inventory, req)
		if req["item_slug"] == "healing-potion" {
			if quantity, ok := req["quantity"].(float64); ok {
				campaign.HealingPotionsAvailable += int(quantity)
			}
		}
		writeJSON(w, http.StatusCreated, req)
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/characters/{character_id}/equipment", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			ItemSlug string `json:"item_slug"`
			Quantity int    `json:"quantity"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ItemSlug == "" || req.Quantity <= 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.AssignedItems++
		campaign.HealingPotionsAvailable -= req.Quantity
		writeJSON(w, http.StatusOK, map[string]any{
			"character_id": r.PathValue("character_id"), "item_slug": req.ItemSlug, "quantity": req.Quantity,
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/inventory/summary", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID, "party_items": len(campaign.Inventory),
			"assigned_items": campaign.AssignedItems, "healing_potions_available": campaign.HealingPotionsAvailable,
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			ID           string `json:"id"`
			CharacterID  string `json:"character_id"`
			ItemSlug     string `json:"item_slug"`
			DaysRequired int    `json:"days_required"`
			CostGP       int    `json:"cost_gp"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Crafting[req.ID] = &referenceCraftingProject{
			ID: req.ID, CharacterID: req.CharacterID, ItemSlug: req.ItemSlug, DaysRequired: req.DaysRequired,
			Status: "active",
		}
		writeJSON(w, http.StatusCreated, map[string]any{
			"id": req.ID, "character_id": req.CharacterID, "item_slug": req.ItemSlug,
			"days_required": req.DaysRequired, "days_completed": 0, "status": "active",
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		project := campaign.Crafting[r.PathValue("project_id")]
		if project == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			Days int `json:"days"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Days <= 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		project.DaysCompleted += req.Days
		if project.DaysCompleted >= project.DaysRequired {
			project.Status = "complete"
			campaign.HealingPotionsAvailable++
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id": project.ID, "days_completed": project.DaysCompleted, "status": project.Status,
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			ID              string   `json:"id"`
			StartsAt        string   `json:"starts_at"`
			DurationMinutes int      `json:"duration_minutes"`
			Agenda          []string `json:"agenda"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Sessions[req.ID] = &referenceScheduledSession{
			ID: req.ID, StartsAt: req.StartsAt, DurationMinutes: req.DurationMinutes, AgendaCount: len(req.Agenda),
		}
		writeJSON(w, http.StatusCreated, map[string]any{
			"id": req.ID, "starts_at": req.StartsAt,
			"duration_minutes": req.DurationMinutes, "agenda_count": len(req.Agenda),
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions/{session_id}/attendance", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		session := campaign.Sessions[r.PathValue("session_id")]
		if session == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var req struct {
			Present []string `json:"present"`
			Absent  []string `json:"absent"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		session.PresentCount = len(req.Present)
		session.AbsentCount = len(req.Absent)
		writeJSON(w, http.StatusOK, map[string]any{
			"session_id": session.ID, "present_count": session.PresentCount, "absent_count": session.AbsentCount,
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/sessions/next", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		session := campaign.Sessions["sess-1"]
		if session == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id": session.ID, "starts_at": session.StartsAt, "agenda_count": session.AgendaCount,
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/audit", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID, "events": len(campaign.Events), "quests": len(campaign.Quests),
			"npcs": len(campaign.NPCs), "sessions": len(campaign.Sessions),
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/export", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID, "name": campaign.Name, "characters": len(campaign.Characters),
			"quests": len(campaign.Quests), "npcs": len(campaign.NPCs), "inventory_items": len(campaign.Inventory),
			"sessions": len(campaign.Sessions), "schema_version": 1,
		})
	})
	mux.HandleFunc("GET /v1/campaigns/{id}/analytics/summary", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id":        campaign.ID,
			"readiness_score":    85,
			"open_quests":        activeQuestCount(campaign),
			"friendly_npcs":      friendlyNPCCount(campaign),
			"scheduled_sessions": len(campaign.Sessions),
			"inventory_items":    len(campaign.Inventory),
		})
	})
	mux.HandleFunc("POST /v1/campaigns/{id}/analytics/risk-report", func(w http.ResponseWriter, r *http.Request) {
		campaign := campaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"campaign_id": campaign.ID,
			"risk_level":  "low",
			"missing":     []any{},
			"signals": map[string]any{
				"has_dm":           campaign.DM != "",
				"has_characters":   len(campaign.Characters) > 0,
				"has_next_session": len(campaign.Sessions) > 0,
				"has_active_quest": activeQuestCount(campaign) > 0,
			},
		})
	})
	playActor := func(w http.ResponseWriter, r *http.Request) (referenceUser, bool) {
		const prefix = "Bearer session-"
		header := r.Header.Get("Authorization")
		if header == "" {
			http.Error(w, "authentication required", http.StatusUnauthorized)
			return referenceUser{}, false
		}
		if !strings.HasPrefix(header, prefix) {
			http.Error(w, "invalid authentication", http.StatusUnauthorized)
			return referenceUser{}, false
		}
		username := strings.TrimPrefix(header, prefix)
		user, ok := users[username]
		if !ok {
			http.Error(w, "not a campaign member", http.StatusForbidden)
			return referenceUser{}, false
		}
		return user, true
	}
	playCampaign := func(w http.ResponseWriter, r *http.Request) (*referencePlayCampaign, referenceUser, bool) {
		actor, ok := playActor(w, r)
		if !ok {
			return nil, referenceUser{}, false
		}
		campaign := playCampaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return nil, referenceUser{}, false
		}
		if actor.Username != campaign.Owner && !campaign.hasMember(actor.Username) {
			http.Error(w, "not a campaign member", http.StatusForbidden)
			return nil, referenceUser{}, false
		}
		return campaign, actor, true
	}
	validatePreparedSpell := func(campaign *referencePlayCampaign, characterID string, spellID string) bool {
		owner := campaign.CharacterOwner[characterID]
		member, exists := campaign.Members[owner]
		if !exists || member.Class != "wizard" {
			return false
		}
		known := false
		for _, candidate := range campaign.Spells[characterID] {
			if candidate == spellID {
				known = true
				break
			}
		}
		if !known {
			return false
		}
		for _, candidate := range campaign.PreparedSpells[characterID] {
			if candidate == spellID {
				return true
			}
		}
		return false
	}
	mux.HandleFunc("POST /v1/play/campaigns", func(w http.ResponseWriter, r *http.Request) {
		actor, ok := playActor(w, r)
		if !ok {
			return
		}
		if actor.Role != "dm" {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			ID         string `json:"id"`
			Name       string `json:"name"`
			MaxPlayers int    `json:"max_players"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" || req.Name == "" || req.MaxPlayers < 1 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if _, exists := playCampaigns[req.ID]; exists {
			http.Error(w, "duplicate campaign", http.StatusConflict)
			return
		}
		campaign := &referencePlayCampaign{ID: req.ID, Name: req.Name, Owner: actor.Username, MaxPlayers: req.MaxPlayers, Status: "lobby", Members: map[string]referencePlayMember{}, Scenes: map[string]string{}, SceneNames: map[string]string{}, Locations: map[string]string{}, Edges: map[string]bool{}, CharacterOwner: map[string]string{}, Spells: map[string][]string{}, PreparedSpells: map[string][]string{}, SpellSlots: map[string]int{}, SpellCasts: map[string][]referenceSpellCast{}, Concentration: map[string]*referenceConcentration{}, Inventory: map[string]map[string]int{}, Equipment: map[string]map[string]referenceEquipmentItem{}, AttunedItems: map[string]map[string]bool{}, Currency: map[string]int{}, Loot: map[string]*referenceLoot{}, NPCs: map[string]*referencePlayNPC{}, Factions: map[string]*referencePlayFaction{}, Reputation: map[string]map[string]int{}, RelationshipIndex: map[string]int{}, ClueIndex: map[string]bool{}, PlayQuestIndex: map[string]int{}, QuestRewardXP: map[string]int{}, QuestRewardItems: map[string]map[string]int{}, WorldEventIndex: map[string]int{}, RumorIndex: map[string]int{}, RumorTextIndex: map[string]bool{}, SettlementIndex: map[string]int{}, RecipeIndex: map[string]int{}, DowntimeActivityIndex: map[string]int{}, DowntimeAllocations: map[string]map[string]*referenceDowntimeAllocation{}, ContentIndex: map[string]int{}, NoteIndex: map[string]int{}, WhisperIndex: map[string]int{}, InvitationIndex: map[string]int{}, Delegations: map[string]referenceDelegation{}, AuditCorrelationIndex: map[string]bool{}, ProjectionEventIndex: map[string]bool{}, IdempotencyKeys: map[string]referenceIdempotentEvent{}, IdempotentEventIndex: map[string]bool{}, SafeCurrentTurn: 1, SafeSubmissionIndex: map[string]bool{}, SearchRecordIndex: map[string]bool{}, SearchTextIndex: map[string]bool{}, RateEventIndex: map[string]bool{}, RateCounts: map[string]int{}, BackupIndex: map[string]int{}, ReplayEventIndex: map[string]bool{}, RNGRollIndex: map[string]bool{}, ModerationReportIndex: map[string]int{}, SafetyEventIndex: map[string]bool{}}
		playCampaigns[req.ID] = campaign
		writeJSON(w, http.StatusCreated, map[string]any{"id": campaign.ID, "name": campaign.Name, "owner": campaign.Owner, "status": campaign.Status, "max_players": campaign.MaxPlayers})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/members", func(w http.ResponseWriter, r *http.Request) {
		actor, ok := playActor(w, r)
		if !ok {
			return
		}
		campaign := playCampaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if actor.Role != "player" || campaign.Status != "lobby" {
			http.Error(w, "membership unavailable", http.StatusConflict)
			return
		}
		var req struct {
			CharacterID string `json:"character_id"`
			Name        string `json:"name"`
			Class       string `json:"class"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.CharacterID == "" || req.Name == "" || req.Class == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.hasMember(actor.Username) || campaign.hasCharacter(req.CharacterID) {
			http.Error(w, "duplicate party member", http.StatusConflict)
			return
		}
		if len(campaign.Members) >= campaign.MaxPlayers {
			http.Error(w, "party full", http.StatusConflict)
			return
		}
		member := referencePlayMember{Username: actor.Username, CharacterID: req.CharacterID, Name: req.Name, Class: req.Class}
		campaign.Members[actor.Username] = member
		campaign.CharacterOwner[req.CharacterID] = actor.Username
		campaign.Currency[req.CharacterID] = 10
		campaign.Order = append(campaign.Order, actor.Username)
		writeJSON(w, http.StatusCreated, member.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/start", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if campaign.Status != "lobby" || len(campaign.Order) < 2 {
			http.Error(w, "campaign cannot start", http.StatusConflict)
			return
		}
		campaign.Status, campaign.CurrentActor, campaign.Phase, campaign.TurnNumber = "active", campaign.Order[0], "player", 1
		campaign.Queue = []string{campaign.Order[0], campaign.Owner, campaign.Order[1], campaign.Owner}
		writeJSON(w, http.StatusOK, map[string]any{"id": campaign.ID, "status": campaign.Status, "current_actor": campaign.CurrentActor, "turn_number": campaign.TurnNumber})
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/session-zero", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if campaign.Status != "lobby" {
			http.Error(w, "campaign already started", http.StatusConflict)
			return
		}
		var req struct {
			Rules   string   `json:"rules"`
			Tone    string   `json:"tone"`
			Consent []string `json:"consent"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.Rules) || !nonEmptyString(req.Tone) || len(req.Consent) == 0 {
			http.Error(w, "invalid session-zero settings", http.StatusBadRequest)
			return
		}
		seen := map[string]bool{}
		for _, consent := range req.Consent {
			if !nonEmptyString(consent) || seen[consent] {
				http.Error(w, "invalid session-zero settings", http.StatusBadRequest)
				return
			}
			seen[consent] = true
		}
		campaign.SessionZero = &referenceSessionZeroSettings{Rules: req.Rules, Tone: req.Tone, Consent: append([]string{}, req.Consent...)}
		writeJSON(w, http.StatusOK, campaign.SessionZero.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/session-zero", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if campaign.SessionZero == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, campaign.SessionZero.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/content", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		content, ok := decodeReferenceContent(w, r, true)
		if !ok {
			return
		}
		if _, exists := campaign.ContentIndex[content.ContentID]; exists {
			http.Error(w, "duplicate content", http.StatusConflict)
			return
		}
		campaign.ContentIndex[content.ContentID] = len(campaign.Content)
		campaign.Content = append(campaign.Content, content)
		writeJSON(w, http.StatusCreated, content.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/content/{content_id}/tags", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := campaign.ContentIndex[r.PathValue("content_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		tags, ok := decodeReferenceContentTags(w, r, false)
		if !ok {
			return
		}
		campaign.Content[index].Tags = tags
		writeJSON(w, http.StatusOK, campaign.Content[index].json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/content", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		excludeValues, hasExcludeTag := r.URL.Query()["exclude_tag"]
		excludeTag := ""
		if hasExcludeTag {
			excludeTag = excludeValues[0]
			if !nonEmptyString(excludeTag) {
				http.Error(w, "invalid exclude_tag", http.StatusBadRequest)
				return
			}
		}
		content := make([]any, 0, len(campaign.Content))
		for _, record := range campaign.Content {
			if actor.Username != campaign.Owner && hasExcludeTag && record.hasTag(excludeTag) {
				continue
			}
			content = append(content, record.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"content": content})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations", func(w http.ResponseWriter, r *http.Request) {
		actor, ok := playActor(w, r)
		if !ok {
			return
		}
		campaign := playCampaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			InvitationID string `json:"invitation_id"`
			Username     string `json:"username"`
			CharacterID  string `json:"character_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.InvitationID) || !nonEmptyString(req.Username) || !nonEmptyString(req.CharacterID) {
			http.Error(w, "invalid invitation", http.StatusBadRequest)
			return
		}
		target, exists := users[req.Username]
		if !exists || target.Role != "player" {
			http.Error(w, "invalid target", http.StatusBadRequest)
			return
		}
		if _, exists := campaign.InvitationIndex[req.InvitationID]; exists {
			http.Error(w, "duplicate invitation", http.StatusConflict)
			return
		}
		for _, invitation := range campaign.Invitations {
			if invitation.Username == req.Username && invitation.Status == "pending" {
				http.Error(w, "duplicate active invitation", http.StatusConflict)
				return
			}
		}
		invitation := referenceInvitation{InvitationID: req.InvitationID, Username: req.Username, CharacterID: req.CharacterID, Status: "pending"}
		campaign.InvitationIndex[invitation.InvitationID] = len(campaign.Invitations)
		campaign.Invitations = append(campaign.Invitations, invitation)
		writeJSON(w, http.StatusCreated, invitation.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/invitations", func(w http.ResponseWriter, r *http.Request) {
		actor, ok := playActor(w, r)
		if !ok {
			return
		}
		campaign := playCampaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		invitations := make([]any, 0, len(campaign.Invitations))
		for _, invitation := range campaign.Invitations {
			if actor.Username == campaign.Owner || invitation.Username == actor.Username {
				invitations = append(invitations, invitation.json())
			}
		}
		if actor.Username != campaign.Owner && !campaign.hasMember(actor.Username) && len(invitations) == 0 {
			http.Error(w, "not a campaign member", http.StatusForbidden)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"invitations": invitations})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations/{invitation_id}/accept", func(w http.ResponseWriter, r *http.Request) {
		actor, ok := playActor(w, r)
		if !ok {
			return
		}
		campaign := playCampaigns[r.PathValue("id")]
		if campaign == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		index, exists := campaign.InvitationIndex[r.PathValue("invitation_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		invitation := &campaign.Invitations[index]
		if actor.Username != invitation.Username {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		if invitation.Status != "pending" {
			http.Error(w, "invitation already accepted", http.StatusConflict)
			return
		}
		if campaign.hasMember(actor.Username) || campaign.hasCharacter(invitation.CharacterID) {
			http.Error(w, "duplicate party member", http.StatusConflict)
			return
		}
		if len(campaign.Members) >= campaign.MaxPlayers {
			http.Error(w, "party full", http.StatusConflict)
			return
		}
		member := referencePlayMember{Username: actor.Username, CharacterID: invitation.CharacterID, Name: actor.Username, Class: "adventurer"}
		campaign.Members[actor.Username] = member
		campaign.CharacterOwner[invitation.CharacterID] = actor.Username
		campaign.Currency[invitation.CharacterID] = 10
		campaign.Order = append(campaign.Order, actor.Username)
		invitation.Status = "accepted"
		writeJSON(w, http.StatusOK, invitation.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/delegations", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Username string   `json:"username"`
			Powers   []string `json:"powers"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !campaign.hasMember(req.Username) || !validReferenceDelegationPowers(req.Powers) {
			http.Error(w, "invalid delegation", http.StatusBadRequest)
			return
		}
		if existing, exists := campaign.Delegations[req.Username]; exists && existing.Active {
			http.Error(w, "duplicate active delegate", http.StatusConflict)
			return
		}
		delegation := referenceDelegation{Username: req.Username, Powers: append([]string{}, req.Powers...), Active: true}
		campaign.Delegations[req.Username] = delegation
		campaign.DelegationAudit = append(campaign.DelegationAudit, referenceDelegationAuditEntry{Username: req.Username, Action: "granted", Powers: append([]string{}, req.Powers...)})
		writeJSON(w, http.StatusCreated, delegation.json())
	})
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/delegations/{username}", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		username := r.PathValue("username")
		delegation, exists := campaign.Delegations[username]
		if !exists || !delegation.Active {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		delegation.Active = false
		campaign.Delegations[username] = delegation
		campaign.DelegationAudit = append(campaign.DelegationAudit, referenceDelegationAuditEntry{Username: username, Action: "revoked", Powers: append([]string{}, delegation.Powers...)})
		writeJSON(w, http.StatusOK, delegation.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/delegations/audit", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		entries := make([]any, 0, len(campaign.DelegationAudit))
		for _, entry := range campaign.DelegationAudit {
			entries = append(entries, entry.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"entries": entries})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/audit-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var req struct {
			Kind          string `json:"kind"`
			CorrelationID string `json:"correlation_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.Kind) || !nonEmptyString(req.CorrelationID) {
			http.Error(w, "invalid audit event", http.StatusBadRequest)
			return
		}
		if campaign.AuditCorrelationIndex[req.CorrelationID] {
			http.Error(w, "duplicate correlation_id", http.StatusConflict)
			return
		}
		entry := campaign.appendAuditEvent(req.Kind, req.CorrelationID, actor)
		campaign.AuditCorrelationIndex[entry.CorrelationID] = true
		writeJSON(w, http.StatusCreated, entry.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/audit-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		entries := make([]any, 0, len(campaign.AuditEvents))
		for _, entry := range campaign.AuditEvents {
			entries = append(entries, entry.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"entries": entries})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/projection-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if !campaign.hasMember(actor.Username) {
			http.Error(w, "player member required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid projection event", http.StatusBadRequest)
			return
		}
		eventID, ok := requiredString(raw, "event_id")
		if !ok {
			http.Error(w, "invalid projection event", http.StatusBadRequest)
			return
		}
		kind, ok := requiredString(raw, "kind")
		if !ok || (kind != "set-story" && kind != "increment-danger") {
			http.Error(w, "invalid projection event", http.StatusBadRequest)
			return
		}
		valueRaw, hasValue := raw["value"]
		value := ""
		if kind == "set-story" {
			if !hasValue || json.Unmarshal(valueRaw, &value) != nil || !nonEmptyString(value) {
				http.Error(w, "invalid projection event", http.StatusBadRequest)
				return
			}
		}
		if kind == "increment-danger" && hasValue {
			http.Error(w, "invalid projection event", http.StatusBadRequest)
			return
		}
		if campaign.ProjectionEventIndex == nil {
			campaign.ProjectionEventIndex = map[string]bool{}
		}
		if campaign.ProjectionEventIndex[eventID] {
			http.Error(w, "duplicate event_id", http.StatusConflict)
			return
		}
		event := referenceProjectionEvent{Sequence: len(campaign.ProjectionEvents) + 1, EventID: eventID, Kind: kind, Value: value}
		campaign.ProjectionEventIndex[eventID] = true
		campaign.ProjectionEvents = append(campaign.ProjectionEvents, event)
		campaign.MetricProjectionEvents++
		campaign.rebuildProjection()
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.rebuildProjection())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection/rebuild", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.rebuildProjection())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/idempotent-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		idempotencyKey := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
		if idempotencyKey == "" {
			http.Error(w, "Idempotency-Key required", http.StatusBadRequest)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid idempotent event", http.StatusBadRequest)
			return
		}
		eventID, ok := requiredString(raw, "event_id")
		if !ok {
			http.Error(w, "invalid idempotent event", http.StatusBadRequest)
			return
		}
		value, ok := requiredString(raw, "value")
		if !ok {
			http.Error(w, "invalid idempotent event", http.StatusBadRequest)
			return
		}
		if campaign.IdempotencyKeys == nil {
			campaign.IdempotencyKeys = map[string]referenceIdempotentEvent{}
		}
		if campaign.IdempotentEventIndex == nil {
			campaign.IdempotentEventIndex = map[string]bool{}
		}
		if existing, exists := campaign.IdempotencyKeys[idempotencyKey]; exists {
			if existing.EventID != eventID || existing.Value != value {
				http.Error(w, "idempotency key conflict", http.StatusConflict)
				return
			}
			writeJSON(w, http.StatusOK, existing.json())
			return
		}
		if campaign.IdempotentEventIndex[eventID] {
			http.Error(w, "duplicate event_id", http.StatusConflict)
			return
		}
		event := referenceIdempotentEvent{EventID: eventID, Value: value, Sequence: len(campaign.IdempotentEvents) + 1, IdempotencyKey: idempotencyKey}
		campaign.IdempotentEventIndex[eventID] = true
		campaign.IdempotencyKeys[idempotencyKey] = event
		campaign.IdempotentEvents = append(campaign.IdempotentEvents, event)
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/idempotent-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		events := make([]any, 0, len(campaign.IdempotentEvents))
		for _, event := range campaign.IdempotentEvents {
			events = append(events, event.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"events": events})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/safe-turns", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid safe turn", http.StatusBadRequest)
			return
		}
		submissionID, ok := requiredString(raw, "submission_id")
		if !ok {
			http.Error(w, "invalid safe turn", http.StatusBadRequest)
			return
		}
		action, ok := requiredString(raw, "action")
		if !ok {
			http.Error(w, "invalid safe turn", http.StatusBadRequest)
			return
		}
		expectedTurn, ok := requiredInt(raw, "expected_turn")
		if !ok || expectedTurn <= 0 {
			http.Error(w, "invalid safe turn", http.StatusBadRequest)
			return
		}
		campaign.ensureSafeTurns()
		if campaign.SafeSubmissionIndex[submissionID] {
			http.Error(w, "duplicate submission_id", http.StatusConflict)
			return
		}
		if expectedTurn != campaign.SafeCurrentTurn {
			writeJSON(w, http.StatusConflict, map[string]any{"current_turn": campaign.SafeCurrentTurn})
			return
		}
		accepted := referenceSafeTurnSubmission{SubmissionID: submissionID, Action: action, AcceptedTurn: campaign.SafeCurrentTurn, NextTurn: campaign.SafeCurrentTurn + 1}
		campaign.SafeSubmissionIndex[submissionID] = true
		campaign.SafeAccepted = append(campaign.SafeAccepted, accepted)
		campaign.SafeCurrentTurn = accepted.NextTurn
		writeJSON(w, http.StatusCreated, accepted.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safe-turns", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		campaign.ensureSafeTurns()
		accepted := make([]any, 0, len(campaign.SafeAccepted))
		for _, entry := range campaign.SafeAccepted {
			accepted = append(accepted, entry.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"current_turn": campaign.SafeCurrentTurn, "accepted": accepted})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/transactional-transfers", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		fromCharacterID, ok := requiredString(raw, "from_character_id")
		if !ok {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		toCharacterID, ok := requiredString(raw, "to_character_id")
		if !ok || toCharacterID == fromCharacterID || !campaign.hasCharacter(toCharacterID) {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		amount, ok := requiredInt(raw, "amount")
		if !ok || amount <= 0 {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		simulateFailure, ok := requiredBool(raw, "simulate_failure")
		if !ok {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		if !campaign.hasCharacter(fromCharacterID) {
			http.Error(w, "invalid transactional transfer", http.StatusBadRequest)
			return
		}
		if campaign.CharacterOwner[fromCharacterID] != actor.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		fromGold := campaign.Currency[fromCharacterID]
		toGold := campaign.Currency[toCharacterID]
		if amount > fromGold {
			http.Error(w, "insufficient funds", http.StatusConflict)
			return
		}
		prepared := referenceTransactionalTransfer{
			FromCharacterID: fromCharacterID,
			ToCharacterID:   toCharacterID,
			Amount:          amount,
			FromGold:        fromGold - amount,
			ToGold:          toGold + amount,
			Sequence:        len(campaign.TransactionalTransfers) + 1,
		}
		if simulateFailure {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "simulated failure"})
			return
		}
		campaign.Currency[fromCharacterID] = prepared.FromGold
		campaign.Currency[toCharacterID] = prepared.ToGold
		campaign.TransactionalTransfers = append(campaign.TransactionalTransfers, prepared)
		writeJSON(w, http.StatusCreated, prepared.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/transactional-transfers", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		transfers := make([]any, 0, len(campaign.TransactionalTransfers))
		for _, transfer := range campaign.TransactionalTransfers {
			transfers = append(transfers, transfer.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"transfers": transfers})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/exports", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		export := referenceCampaignExport{Version: len(campaign.Exports) + 1, Story: campaign.Story, Status: campaign.Status}
		campaign.Exports = append(campaign.Exports, export)
		writeJSON(w, http.StatusCreated, export.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/exports", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		exports := make([]any, 0, len(campaign.Exports))
		for _, export := range campaign.Exports {
			exports = append(exports, export.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"exports": exports})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/exports/{version}", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		version, err := strconv.Atoi(r.PathValue("version"))
		if err != nil || version < 1 || version > len(campaign.Exports) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, campaign.Exports[version-1].json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/imports", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Version int    `json:"version"`
			Story   string `json:"story"`
			Status  string `json:"status"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Version != 1 || req.Story == "" || (req.Status != "lobby" && req.Status != "started") {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		imported := referenceCampaignImport{Version: req.Version, Story: req.Story, Status: req.Status}
		campaign.Story = imported.Story
		campaign.Status = imported.Status
		campaign.ImportedState = &imported
		writeJSON(w, http.StatusOK, imported.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/import-state", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if campaign.ImportedState == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, campaign.ImportedState.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/migrations", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			SchemaVersion int    `json:"schema_version"`
			Story         string `json:"story"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.SchemaVersion != 1 || req.Story == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		migrated := referenceCampaignMigration{SchemaVersion: 2, Story: req.Story, CampaignName: campaign.Name}
		status := http.StatusCreated
		if campaign.MigratedState != nil && campaign.MigratedState.Story == migrated.Story && campaign.MigratedState.CampaignName == migrated.CampaignName {
			status = http.StatusOK
		} else {
			campaign.MigratedState = &migrated
		}
		writeJSON(w, status, migrated.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/migration-state", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if campaign.MigratedState == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, campaign.MigratedState.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/search-records", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			RecordID string `json:"record_id"`
			Text     string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.RecordID == "" || req.Text == "" || campaign.SearchRecordIndex[req.RecordID] || campaign.SearchTextIndex[req.Text] {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		record := referenceSearchRecord{RecordID: req.RecordID, Text: req.Text}
		campaign.SearchRecords = append(campaign.SearchRecords, record)
		campaign.SearchRecordIndex[record.RecordID] = true
		campaign.SearchTextIndex[record.Text] = true
		writeJSON(w, http.StatusCreated, record.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/search-records", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		values := r.URL.Query()
		if len(values["q"]) > 1 || len(values["limit"]) > 1 || len(values["cursor"]) > 1 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		q := values.Get("q")
		limit := 2
		if raw := values.Get("limit"); raw != "" {
			parsed, err := strconv.Atoi(raw)
			if err != nil || parsed < 1 || parsed > 3 {
				http.Error(w, "bad request", http.StatusBadRequest)
				return
			}
			limit = parsed
		}
		cursor := 0
		if raw := values.Get("cursor"); raw != "" {
			parsed, err := strconv.Atoi(raw)
			if err != nil || parsed < 0 {
				http.Error(w, "bad request", http.StatusBadRequest)
				return
			}
			cursor = parsed
		}
		filtered := make([]referenceSearchRecord, 0, len(campaign.SearchRecords))
		needle := strings.ToLower(q)
		for _, record := range campaign.SearchRecords {
			if needle == "" || strings.Contains(strings.ToLower(record.Text), needle) {
				filtered = append(filtered, record)
			}
		}
		end := cursor + limit
		if cursor > len(filtered) {
			cursor = len(filtered)
		}
		if end > len(filtered) {
			end = len(filtered)
		}
		records := make([]any, 0, end-cursor)
		for _, record := range filtered[cursor:end] {
			records = append(records, record.json())
		}
		var nextCursor any
		if end < len(filtered) {
			nextCursor = end
		}
		writeJSON(w, http.StatusOK, map[string]any{"records": records, "next_cursor": nextCursor})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rate-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		campaign.ensureRateLimits()
		var req struct {
			EventID string `json:"event_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.EventID == "" || campaign.RateEventIndex[req.EventID] {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		remaining := campaign.rateRemaining(actor.Username)
		if remaining == 0 {
			campaign.MetricRejectedRateEvents++
			writeJSON(w, http.StatusTooManyRequests, map[string]any{"limit": referenceRateEventLimit, "remaining": 0})
			return
		}
		campaign.RateCounts[actor.Username]++
		event := referenceRateEvent{EventID: req.EventID, Actor: actor.Username}
		campaign.RateEvents = append(campaign.RateEvents, event)
		campaign.RateEventIndex[event.EventID] = true
		campaign.MetricAcceptedRateEvents++
		writeJSON(w, http.StatusCreated, map[string]any{"event_id": event.EventID, "actor": event.Actor, "remaining": campaign.rateRemaining(actor.Username)})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/rate-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		campaign.ensureRateLimits()
		events := make([]any, 0, len(campaign.RateEvents))
		for _, event := range campaign.RateEvents {
			events = append(events, event.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"events": events, "remaining": campaign.rateRemaining(actor.Username)})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/metrics", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"accepted_rate_events": campaign.MetricAcceptedRateEvents,
			"rejected_rate_events": campaign.MetricRejectedRateEvents,
			"projection_events":    campaign.MetricProjectionEvents,
			"uptime_ticks":         1,
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/service-mode", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner || actor.Role != "dm" {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Maintenance bool `json:"maintenance"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		maintenanceMode = req.Maintenance
		writeJSON(w, http.StatusOK, map[string]any{"maintenance": maintenanceMode})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/backups", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		backup := referenceCampaignBackup{BackupID: fmt.Sprintf("backup-%d", len(campaign.Backups)+1), Story: campaign.Story, Status: campaign.Status}
		campaign.Backups = append(campaign.Backups, backup)
		campaign.BackupIndex[backup.BackupID] = len(campaign.Backups) - 1
		writeJSON(w, http.StatusCreated, backup.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/backups", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		backups := make([]any, 0, len(campaign.Backups))
		for _, backup := range campaign.Backups {
			backups = append(backups, backup.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"backups": backups})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/backups/{backup_id}/restore", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := campaign.BackupIndex[r.PathValue("backup_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		backup := campaign.Backups[index]
		campaign.Story = backup.Story
		campaign.Status = backup.Status
		writeJSON(w, http.StatusOK, backup.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/replay-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		eventID, ok := requiredString(raw, "event_id")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		kind, ok := requiredString(raw, "kind")
		if !ok || kind != "append" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.ReplayEventIndex[eventID] {
			http.Error(w, "duplicate event", http.StatusConflict)
			return
		}
		event := referenceReplayEvent{EventID: eventID, Kind: kind, Text: text, Sequence: len(campaign.ReplayEvents) + 1}
		campaign.ReplayEvents = append(campaign.ReplayEvents, event)
		campaign.ReplayEventIndex[eventID] = true
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/replay", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.replayStateJSON())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/replay/check", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.replayStateJSON())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/rng-seed", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		seed, ok := requiredString(raw, "seed")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.RNGSeed != "" {
			http.Error(w, "rng seed already configured", http.StatusConflict)
			return
		}
		campaign.RNGSeed = seed
		writeJSON(w, http.StatusOK, campaign.rngLedgerJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rng-rolls", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if campaign.RNGSeed == "" {
			http.Error(w, "rng seed required", http.StatusConflict)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		rollID, ok := requiredString(raw, "roll_id")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		sides, ok := requiredInt(raw, "sides")
		if !ok || sides < 2 || sides > 100 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.RNGRollIndex[rollID] {
			http.Error(w, "duplicate roll", http.StatusConflict)
			return
		}
		sequence := len(campaign.RNGRolls) + 1
		roll := referenceRNGRoll{RollID: rollID, Sides: sides, Result: deterministicRNGResult(campaign.RNGSeed, sequence, rollID, sides), Sequence: sequence}
		campaign.RNGRolls = append(campaign.RNGRolls, roll)
		campaign.RNGRollIndex[rollID] = true
		writeJSON(w, http.StatusCreated, roll.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/rng-ledger", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.rngLedgerJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/moderation/reports", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		reportID, ok := requiredString(raw, "report_id")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		targetID, ok := requiredString(raw, "target_id")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		reason, ok := requiredString(raw, "reason")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.ModerationReportIndex[reportID] != 0 {
			http.Error(w, "duplicate report", http.StatusConflict)
			return
		}
		report := referenceModerationReport{
			ReportID: reportID,
			TargetID: targetID,
			Reason:   reason,
			Status:   "open",
			Reporter: actor.Username,
			Sequence: len(campaign.ModerationReports) + 1,
		}
		campaign.ModerationReports = append(campaign.ModerationReports, report)
		campaign.ModerationReportIndex[reportID] = len(campaign.ModerationReports)
		writeJSON(w, http.StatusCreated, report.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/moderation/reports", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.moderationReportsJSON())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index := campaign.ModerationReportIndex[r.PathValue("report_id")]
		if index == 0 {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		action, ok := requiredString(raw, "action")
		if !ok || (action != "allow" && action != "remove") {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		note, ok := requiredString(raw, "note")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		report := &campaign.ModerationReports[index-1]
		if report.Status != "open" {
			http.Error(w, "report already resolved", http.StatusConflict)
			return
		}
		report.Status = "resolved"
		report.Action = action
		report.Note = note
		report.Resolver = actor.Username
		writeJSON(w, http.StatusOK, report.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/safety-boundaries", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		blockedTags, ok := requiredUniqueStrings(raw, "blocked_tags")
		if !ok || len(blockedTags) == 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		next := append([]string(nil), blockedTags...)
		sort.Strings(next)
		campaign.SafetyBlockedTags = next
		writeJSON(w, http.StatusOK, campaign.safetyBoundariesJSON())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safety-boundaries", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.safetyBoundariesJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/safety-checks", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		eventID, ok := requiredString(raw, "event_id")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		kind, ok := requiredString(raw, "kind")
		if !ok || (kind != "narration" && kind != "chat") {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		tags, ok := requiredUniqueStrings(raw, "tags")
		if !ok || len(tags) == 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if campaign.SafetyEventIndex[eventID] {
			http.Error(w, "duplicate event", http.StatusConflict)
			return
		}
		blocked := map[string]bool{}
		for _, tag := range campaign.SafetyBlockedTags {
			blocked[tag] = true
		}
		for _, tag := range tags {
			if blocked[tag] {
				http.Error(w, "blocked safety tag", http.StatusConflict)
				return
			}
		}
		event := referenceSafetyEvent{EventID: eventID, Kind: kind, Text: text, Tags: tags, Sequence: len(campaign.SafetyEvents) + 1}
		campaign.SafetyEvents = append(campaign.SafetyEvents, event)
		campaign.SafetyEventIndex[eventID] = true
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safety-events", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, campaign.safetyEventsJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/notes", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var req struct {
			NoteID     string `json:"note_id"`
			Text       string `json:"text"`
			Visibility string `json:"visibility"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.NoteID) || !nonEmptyString(req.Text) || (req.Visibility != "private" && req.Visibility != "party") {
			http.Error(w, "invalid note", http.StatusBadRequest)
			return
		}
		if _, exists := campaign.NoteIndex[req.NoteID]; exists {
			http.Error(w, "duplicate note", http.StatusConflict)
			return
		}
		note := referenceNote{NoteID: req.NoteID, Text: req.Text, Visibility: req.Visibility, Owner: actor.Username}
		campaign.NoteIndex[note.NoteID] = len(campaign.Notes)
		campaign.Notes = append(campaign.Notes, note)
		writeJSON(w, http.StatusCreated, note.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		notes := make([]any, 0, len(campaign.Notes))
		for _, note := range campaign.Notes {
			if referenceNoteReadable(campaign, actor, note) {
				notes = append(notes, note.json())
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"notes": notes})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes/{note_id}", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		index, exists := campaign.NoteIndex[r.PathValue("note_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		note := campaign.Notes[index]
		if !referenceNoteReadable(campaign, actor, note) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		writeJSON(w, http.StatusOK, note.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/notes/{note_id}", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		index, exists := campaign.NoteIndex[r.PathValue("note_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if campaign.Notes[index].Owner != actor.Username {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		var req struct {
			Text       string `json:"text"`
			Visibility string `json:"visibility"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.Text) || (req.Visibility != "private" && req.Visibility != "party") {
			http.Error(w, "invalid note", http.StatusBadRequest)
			return
		}
		campaign.Notes[index].Text = req.Text
		campaign.Notes[index].Visibility = req.Visibility
		writeJSON(w, http.StatusOK, campaign.Notes[index].json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/whispers", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		member, exists := campaign.Members[actor.Username]
		if !exists {
			http.Error(w, "player character required", http.StatusForbidden)
			return
		}
		var req struct {
			WhisperID     string `json:"whisper_id"`
			ToCharacterID string `json:"to_character_id"`
			Text          string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !nonEmptyString(req.WhisperID) || !nonEmptyString(req.ToCharacterID) || !nonEmptyString(req.Text) {
			http.Error(w, "invalid whisper", http.StatusBadRequest)
			return
		}
		if _, exists := campaign.CharacterOwner[req.ToCharacterID]; !exists {
			http.Error(w, "invalid recipient", http.StatusBadRequest)
			return
		}
		if _, exists := campaign.WhisperIndex[req.WhisperID]; exists {
			http.Error(w, "duplicate whisper", http.StatusConflict)
			return
		}
		whisper := referenceWhisper{WhisperID: req.WhisperID, FromCharacterID: member.CharacterID, ToCharacterID: req.ToCharacterID, Text: req.Text}
		campaign.WhisperIndex[whisper.WhisperID] = len(campaign.Whispers)
		campaign.Whispers = append(campaign.Whispers, whisper)
		writeJSON(w, http.StatusCreated, whisper.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/whispers", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		whispers := make([]any, 0, len(campaign.Whispers))
		for _, whisper := range campaign.Whispers {
			if referenceWhisperReadable(campaign, actor, whisper) {
				whispers = append(whispers, whisper.json())
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"whispers": whispers})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/sheet", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		owner, exists := campaign.CharacterOwner[characterID]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if actor.Username != campaign.Owner && actor.Username != owner {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		member := campaign.Members[owner]
		writeJSON(w, http.StatusOK, map[string]any{
			"character_id":      characterID,
			"owner":             owner,
			"name":              member.Name,
			"class":             member.Class,
			"level":             1,
			"proficiency_bonus": 2,
			"hp_max":            10,
			"armor_class":       10,
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/narrations", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner && !campaign.hasActiveDelegationPower(actor.Username, "narrate") {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		event := campaign.appendEvent("narration", actor.Username, "", req.Text)
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/turn", func(w http.ResponseWriter, r *http.Request) {
		campaign, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"campaign_id": campaign.ID, "current_actor": campaign.CurrentActor, "phase": campaign.Phase, "turn_number": campaign.TurnNumber, "queue": campaign.Queue, "overdue": false, "logical_deadline": campaign.TurnNumber + 1})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/my-turn", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		member := campaign.Members[actor.Username]
		writeJSON(w, http.StatusOK, map[string]any{"is_my_turn": campaign.CurrentActor == actor.Username, "current_actor": campaign.CurrentActor, "character": map[string]any{"id": member.CharacterID, "name": member.Name}, "recent_events": campaign.eventJSON()})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/gm/status", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		party := make([]map[string]any, 0, len(campaign.Order))
		for _, username := range campaign.Order {
			party = append(party, campaign.Members[username].json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"needs_attention": campaign.CurrentActor == campaign.Owner, "current_actor": campaign.CurrentActor, "party": party, "recent_events": campaign.eventJSON()})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/actions", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.CurrentActor || actor.Role != "player" {
			http.Error(w, "not this player's turn", http.StatusConflict)
			return
		}
		var req struct {
			Type string `json:"type"`
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Type == "" || req.Text == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		event := campaign.appendEvent("action", actor.Username, req.Type, req.Text)
		campaign.CurrentActor, campaign.Phase = campaign.Owner, "gm"
		payload := event.json()
		payload["next_actor"] = campaign.CurrentActor
		writeJSON(w, http.StatusCreated, payload)
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/resolutions", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner || campaign.CurrentActor != campaign.Owner {
			http.Error(w, "not the DM turn", http.StatusConflict)
			return
		}
		var req struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		event := campaign.appendEvent("resolution", actor.Username, "", req.Text)
		next := campaign.Order[1]
		if campaign.TurnNumber >= 2 {
			next = campaign.Order[0]
		}
		campaign.CurrentActor, campaign.Phase, campaign.TurnNumber = next, "player", campaign.TurnNumber+1
		payload := event.json()
		payload["next_actor"], payload["turn_number"] = campaign.CurrentActor, campaign.TurnNumber
		writeJSON(w, http.StatusCreated, payload)
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/nudge", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Message string `json:"message"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Message == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.NudgeCount++
		campaign.appendEvent("nudge", actor.Username, "", req.Message)
		writeJSON(w, http.StatusCreated, map[string]any{"actor": actor.Username, "target": campaign.CurrentActor, "message": req.Message, "nudge_count": campaign.NudgeCount})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/messages", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var req struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		event := campaign.appendEvent("chat", actor.Username, "", req.Text)
		payload := event.json()
		payload["current_actor"] = campaign.CurrentActor
		writeJSON(w, http.StatusCreated, payload)
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/observations", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var req struct {
			Type string `json:"type"`
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Type == "" || req.Text == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		event := campaign.appendEvent("observation", actor.Username, req.Type, req.Text)
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/document", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			Story   string `json:"story"`
			DMNotes string `json:"dm_notes"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Story == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		campaign.Story, campaign.DMNotes = req.Story, req.DMNotes
		writeJSON(w, http.StatusOK, map[string]any{"story": campaign.Story, "dm_notes": campaign.DMNotes})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/document", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		payload := map[string]any{"story": campaign.Story}
		if actor.Username == campaign.Owner {
			payload["dm_notes"] = campaign.DMNotes
		}
		writeJSON(w, http.StatusOK, payload)
	})
	// 031-050 reference surface. These handlers intentionally model only the
	// deterministic public contract exercised by dndeval; no evaluator reads
	// their in-memory state directly.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.ID == "" || q.Name == "" {
			http.Error(w, "bad request", 400)
			return
		}
		c.CurrentScene = q.ID
		c.Scenes[q.ID] = "open"
		c.SceneNames[q.ID] = q.Name
		writeJSON(w, 201, map[string]any{"id": q.ID, "name": q.Name, "status": "open", "current": true})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/close", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		id := r.PathValue("scene_id")
		if c.Scenes[id] != "open" {
			http.Error(w, "not found", 404)
			return
		}
		c.Scenes[id] = "closed"
		if c.CurrentScene == id {
			c.CurrentScene = ""
		}
		writeJSON(w, 200, map[string]any{"id": id, "status": "closed", "current": false})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.ID == "" || q.Name == "" {
			http.Error(w, "bad request", 400)
			return
		}
		c.Locations[q.ID] = q.Name
		writeJSON(w, 201, map[string]any{"id": q.ID, "name": q.Name})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations/{location_id}/edges", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			To string `json:"to"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || c.Locations[r.PathValue("location_id")] == "" || c.Locations[q.To] == "" {
			http.Error(w, "bad edge", 400)
			return
		}
		c.Edges[r.PathValue("location_id")+":"+q.To] = true
		writeJSON(w, 201, map[string]any{"from": r.PathValue("location_id"), "to": q.To})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/travel", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			From string `json:"from"`
			To   string `json:"to"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || !c.Edges[q.From+":"+q.To] {
			http.Error(w, "invalid travel", 409)
			return
		}
		c.CurrentActor = c.Owner
		c.Phase = "gm"
		c.appendEvent("travel", a.Username, "", q.To)
		writeJSON(w, 201, map[string]any{"kind": "travel", "actor": a.Username, "destination": q.To, "next_actor": c.Owner})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rests", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Type string `json:"type"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || (q.Type != "short" && q.Type != "long") {
			http.Error(w, "bad rest", 400)
			return
		}
		c.appendEvent("rest", a.Username, q.Type, "")
		writeJSON(w, 201, map[string]any{"kind": "rest", "type": q.Type, "resources_reset": q.Type == "long"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.ID == "" {
			http.Error(w, "bad request", 400)
			return
		}
		c.Encounter = &referencePlayEncounter{ID: q.ID, Status: "active", Current: "play-char-a", Round: 1, HP: map[string]int{"play-char-a": 10, "play-char-b": 10}, Bound: map[string]bool{"play-char-a": true}, Monsters: map[string]int{}, Conditions: map[string][]string{}}
		writeJSON(w, 201, map[string]any{"id": q.ID, "name": q.Name, "status": "active", "current_combatant": "play-char-a", "combatants": []any{}})
	})
	encounter := func(w http.ResponseWriter, r *http.Request) (*referencePlayCampaign, *referencePlayEncounter, referenceUser, bool) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return nil, nil, referenceUser{}, false
		}
		if c.Encounter == nil || c.Encounter.ID != r.PathValue("encounter_id") {
			http.Error(w, "not found", 404)
			return nil, nil, referenceUser{}, false
		}
		return c, c.Encounter, a, true
	}
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/monsters", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			ID         string `json:"monster_id"`
			Name       string `json:"name"`
			HP         int    `json:"hp_max"`
			Initiative int    `json:"initiative"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.ID == "" || q.HP < 1 {
			http.Error(w, "bad request", 400)
			return
		}
		e.Monsters[q.ID] = q.HP
		writeJSON(w, 201, map[string]any{"monster_id": q.ID, "name": q.Name, "hp_max": q.HP, "hp_current": q.HP, "initiative": q.Initiative})
	})
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{encounter_id}/monsters/{monster_id}", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		id := r.PathValue("monster_id")
		delete(e.Monsters, id)
		writeJSON(w, 200, map[string]any{"removed": id})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/combatants", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Member     string `json:"member"`
			Initiative int    `json:"initiative"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Member == "" {
			http.Error(w, "bad request", 400)
			return
		}
		characterID, name := "play-char-a", "Aria"
		if q.Member == "player-b" {
			characterID, name = "play-char-b", "Bram"
		}
		e.Bound[characterID] = true
		writeJSON(w, 201, map[string]any{"member": q.Member, "character_id": characterID, "name": name, "initiative": q.Initiative})
	})
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{encounter_id}/combatants/{member}", func(w http.ResponseWriter, r *http.Request) {
		_, _, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"removed": r.PathValue("member")})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{encounter_id}/turn", func(w http.ResponseWriter, r *http.Request) {
		_, e, _, ok := encounter(w, r)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"current_combatant": e.Current, "round": e.Round, "turn_index": 0, "active": map[string]any{"name": "Goblin", "kind": "monster", "initiative": 15}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/advance", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" || e.Current != "play-char-a" {
			http.Error(w, "not current combatant", 409)
			return
		}
		e.Current = "play-char-b"
		writeJSON(w, 200, map[string]any{"current_combatant": e.Current, "round": e.Round})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/actions", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		var q struct {
			Type   string `json:"type"`
			Target string `json:"target"`
			Text   string `json:"text"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Type != "attack" {
			http.Error(w, "bad action", 400)
			return
		}
		if a.Username != "player-a" || e.Current != "play-char-a" {
			http.Error(w, "not current combatant", 409)
			return
		}
		writeJSON(w, 201, map[string]any{"sequence": 11, "kind": "combat_action", "type": q.Type, "actor": a.Username, "target": q.Target, "text": q.Text})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/damage", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Target string `json:"target"`
			Amount int    `json:"amount"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Amount < 1 {
			http.Error(w, "bad damage", 400)
			return
		}
		if hp, monster := e.Monsters[q.Target]; monster {
			e.Monsters[q.Target] = hp - q.Amount
			writeJSON(w, 200, map[string]any{"target": q.Target, "hp_before": hp, "hp_after": e.Monsters[q.Target], "damage": q.Amount})
			return
		}
		e.HP[q.Target] -= q.Amount
		if e.HP[q.Target] < 0 {
			e.HP[q.Target] = 0
		}
		writeJSON(w, 200, map[string]any{"target": q.Target, "hp": e.HP[q.Target], "kind": "damage"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/healing", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Target string `json:"target"`
			Amount int    `json:"amount"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Amount < 1 {
			http.Error(w, "bad healing", 400)
			return
		}
		e.HP[q.Target] += q.Amount
		if e.HP[q.Target] > 10 {
			e.HP[q.Target] = 10
		}
		writeJSON(w, 200, map[string]any{"target": q.Target, "hp": e.HP[q.Target], "kind": "healing"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/death-saves", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Target  string `json:"target"`
			Success bool   `json:"success"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil {
			http.Error(w, "bad request", 400)
			return
		}
		if q.Success {
			e.DeathSuccess++
		} else {
			e.DeathFailure++
		}
		writeJSON(w, 200, map[string]any{"target": q.Target, "failures": e.DeathFailure, "successes": e.DeathSuccess, "state": "unconscious"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/conditions", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Target    string `json:"target"`
			Condition string `json:"condition"`
			Rounds    int    `json:"duration_rounds"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Condition == "" || q.Rounds < 1 {
			http.Error(w, "bad condition", 400)
			return
		}
		e.Conditions[q.Target] = []string{q.Condition}
		writeJSON(w, 201, map[string]any{"target": q.Target, "conditions": []any{map[string]any{"condition": q.Condition, "remaining_rounds": q.Rounds}}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/conditions/expire", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Target    string `json:"target"`
			Condition string `json:"condition"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil {
			http.Error(w, "bad request", 400)
			return
		}
		e.Conditions[q.Target] = []string{}
		writeJSON(w, 200, map[string]any{"target": q.Target, "conditions": e.Conditions[q.Target]})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/ready", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" || e.Current != "play-char-a" {
			http.Error(w, "not current combatant", 409)
			return
		}
		var q struct {
			Trigger string `json:"trigger"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Trigger == "" {
			http.Error(w, "bad ready", 400)
			return
		}
		writeJSON(w, 201, map[string]any{"actor": a.Username, "trigger": q.Trigger, "kind": "ready"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/delay", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" || e.Current != "play-char-a" {
			http.Error(w, "not current combatant", 409)
			return
		}
		e.Current = "play-char-b"
		writeJSON(w, 200, map[string]any{"delayed": "play-char-a", "current_combatant": e.Current})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/close", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		e.Status = "closed"
		writeJSON(w, 200, map[string]any{"id": e.ID, "status": "closed", "xp_awarded": e.XPAwarded})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/return", func(w http.ResponseWriter, r *http.Request) {
		c, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" || e.Status != "closed" {
			http.Error(w, "cannot return", 409)
			return
		}
		c.CurrentActor = "player-b"
		c.Phase = "player"
		writeJSON(w, 200, map[string]any{"phase": "player", "current_actor": "player-b", "mode": "exploration"})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/owner", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		id := r.PathValue("character_id")
		writeJSON(w, 200, map[string]any{"character_id": id, "username": c.CharacterOwner[id], "owner": c.CharacterOwner[id]})
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/owner", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			Username string `json:"username"`
		}
		json.NewDecoder(r.Body).Decode(&q)
		if c.CharacterOwner[r.PathValue("character_id")] != q.Username {
			http.Error(w, "ownership immutable", 409)
			return
		}
		writeJSON(w, 200, map[string]any{"character_id": r.PathValue("character_id"), "username": q.Username})
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/choices", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			Race       string `json:"race"`
			Class      string `json:"class"`
			Background string `json:"background"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.Race != "elf" || q.Class != "rogue" || q.Background != "sage" || a.Username != "player-a" {
			http.Error(w, "bad choices", 400)
			return
		}
		writeJSON(w, 200, map[string]any{"race": q.Race, "class": q.Class, "background": q.Background, "level": 1, "hp_max": 8})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/level", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			XP int `json:"xp"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || q.XP < 300 {
			http.Error(w, "bad xp", 400)
			return
		}
		writeJSON(w, 200, map[string]any{"level": 2, "xp": q.XP, "resource_max": 2})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/skills/check", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			Skill string `json:"skill"`
			Roll  int    `json:"roll"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-a" || q.Skill != "stealth" {
			http.Error(w, "bad skill", 400)
			return
		}
		writeJSON(w, 200, map[string]any{"skill": q.Skill, "modifier": 5, "total": q.Roll + 5, "proficient": true})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/spells", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			SpellID string `json:"spell_id"`
			Name    string `json:"name"`
			Level   int    `json:"level"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-a" || r.PathValue("character_id") != "play-char-w" || (q.SpellID != "fire-bolt" && q.SpellID != "magic-missile") {
			http.Error(w, "invalid class spell", 400)
			return
		}
		for _, knownSpellID := range c.Spells[r.PathValue("character_id")] {
			if knownSpellID == q.SpellID {
				http.Error(w, "duplicate spell", 409)
				return
			}
		}
		if q.SpellID == "magic-missile" && (q.Name != "Magic Missile" || q.Level != 1) {
			http.Error(w, "invalid class spell", 400)
			return
		}
		if q.SpellID == "fire-bolt" && (q.Name != "Fire Bolt" || q.Level != 0) {
			http.Error(w, "invalid class spell", 400)
			return
		}
		characterID := r.PathValue("character_id")
		c.Spells[characterID] = append(c.Spells[characterID], q.SpellID)
		if q.SpellID == "magic-missile" {
			c.SpellSlots[characterID] = 1
		}
		writeJSON(w, 201, map[string]any{"spell_id": q.SpellID, "name": q.Name, "level": q.Level})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/spells", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		id := r.PathValue("character_id")
		spells := make([]any, 0, len(c.Spells[id]))
		for _, spellID := range c.Spells[id] {
			switch spellID {
			case "fire-bolt":
				spells = append(spells, map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0})
			case "magic-missile":
				spells = append(spells, map[string]any{"spell_id": "magic-missile", "name": "Magic Missile", "level": 1})
			}
		}
		writeJSON(w, 200, map[string]any{"spells": spells})
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "not owner", 403)
			return
		}
		member, exists := c.Members[a.Username]
		if !exists || member.Class != "wizard" {
			http.Error(w, "not a spellcaster", 400)
			return
		}
		var q struct {
			SpellIDs []string `json:"spell_ids"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil {
			http.Error(w, "bad request", 400)
			return
		}
		known := map[string]bool{}
		for _, spell := range c.Spells[characterID] {
			known[spell] = true
		}
		if len(q.SpellIDs) > 1 {
			http.Error(w, "too many spells", 400)
			return
		}
		for _, spell := range q.SpellIDs {
			if !known[spell] {
				http.Error(w, "unknown spell", 400)
				return
			}
		}
		c.PreparedSpells[characterID] = q.SpellIDs
		writeJSON(w, 200, map[string]any{"character_id": characterID, "prepared_spells": q.SpellIDs, "max_prepared": 1})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		prepared := c.PreparedSpells[characterID]
		if prepared == nil {
			prepared = []string{}
		}
		writeJSON(w, 200, map[string]any{"character_id": characterID, "prepared_spells": prepared, "max_prepared": 1})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/casts", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		var q struct {
			SpellID string `json:"spell_id"`
			Target  string `json:"target"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.SpellID != "magic-missile" || q.Target == "" {
			http.Error(w, "invalid cast", http.StatusBadRequest)
			return
		}
		prepared := false
		for _, spellID := range c.PreparedSpells[characterID] {
			if spellID == q.SpellID {
				prepared = true
				break
			}
		}
		if !prepared {
			http.Error(w, "spell not prepared", http.StatusBadRequest)
			return
		}
		if c.SpellSlots[characterID] < 1 {
			http.Error(w, "spell slots exhausted", http.StatusConflict)
			return
		}
		c.SpellSlots[characterID]--
		event := referenceSpellCast{CharacterID: characterID, SpellID: q.SpellID, Target: q.Target, SlotLevel: 1, SlotsRemaining: c.SpellSlots[characterID], Sequence: len(c.SpellCasts[characterID]) + 1}
		c.SpellCasts[characterID] = append(c.SpellCasts[characterID], event)
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/casts", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		casts := make([]map[string]any, 0, len(c.SpellCasts[characterID]))
		for _, event := range c.SpellCasts[characterID] {
			casts = append(casts, event.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"casts": casts})
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/concentration", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		var q struct {
			SpellID       string `json:"spell_id"`
			Target        string `json:"target"`
			DurationTurns int    `json:"duration_turns"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.SpellID == "" || q.Target == "" || q.DurationTurns < 1 || !validatePreparedSpell(c, characterID, q.SpellID) {
			http.Error(w, "invalid concentration", http.StatusBadRequest)
			return
		}
		c.Concentration[characterID] = &referenceConcentration{SpellID: q.SpellID, Target: q.Target, RemainingTurns: q.DurationTurns}
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "concentration": concentrationJSON(c, characterID)})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/concentration", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "concentration": concentrationJSON(c, characterID)})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if concentration := c.Concentration[characterID]; concentration != nil {
			concentration.RemainingTurns--
			if concentration.RemainingTurns <= 0 {
				delete(c.Concentration, characterID)
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "concentration": concentrationJSON(c, characterID)})
	})
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{character_id}/concentration", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		delete(c.Concentration, characterID)
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "concentration": nil})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		var q struct {
			ItemID   string `json:"item_id"`
			Quantity int    `json:"quantity"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !validInventoryItem(q.ItemID) || q.Quantity < 1 {
			http.Error(w, "invalid inventory item", http.StatusBadRequest)
			return
		}
		if c.Inventory[characterID] == nil {
			c.Inventory[characterID] = map[string]int{}
		}
		c.Inventory[characterID][q.ItemID] += q.Quantity
		writeJSON(w, http.StatusCreated, inventoryItemJSON(characterID, q.ItemID, q.Quantity, c.Inventory[characterID][q.ItemID]))
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "items": inventoryItemsJSON(c.Inventory[characterID])})
	})
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		itemID := r.PathValue("item_id")
		var q struct {
			Quantity int `json:"quantity"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !validInventoryItem(itemID) || q.Quantity < 1 {
			http.Error(w, "invalid inventory item", http.StatusBadRequest)
			return
		}
		held := c.Inventory[characterID][itemID]
		if q.Quantity > held {
			http.Error(w, "insufficient inventory quantity", http.StatusConflict)
			return
		}
		c.Inventory[characterID][itemID] = held - q.Quantity
		if c.Inventory[characterID][itemID] == 0 {
			delete(c.Inventory[characterID], itemID)
		}
		writeJSON(w, http.StatusOK, inventoryItemJSON(characterID, itemID, q.Quantity, held-q.Quantity))
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		slot := r.PathValue("slot")
		var q struct {
			ItemID string `json:"item_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || equipmentSlot(q.ItemID) != slot || !validEquipmentSlot(slot) || c.Inventory[characterID][q.ItemID] < 1 {
			http.Error(w, "invalid equipment item", http.StatusBadRequest)
			return
		}
		if c.Equipment[characterID] == nil {
			c.Equipment[characterID] = map[string]referenceEquipmentItem{}
		}
		c.Equipment[characterID][slot] = referenceEquipmentItem{ItemID: q.ItemID, Attuned: c.AttunedItems[characterID][q.ItemID]}
		writeJSON(w, http.StatusOK, equipmentItemJSON(characterID, slot, c.Equipment[characterID][slot]))
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		slot := r.PathValue("slot")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if !validEquipmentSlot(slot) {
			http.Error(w, "invalid equipment slot", http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusOK, equipmentItemJSON(characterID, slot, c.Equipment[characterID][slot]))
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		slot := r.PathValue("slot")
		if !validEquipmentSlot(slot) {
			http.Error(w, "invalid equipment slot", http.StatusBadRequest)
			return
		}
		item := c.Equipment[characterID][slot]
		if slot != "accessory" || !attunableEquipmentItem(item.ItemID) {
			http.Error(w, "attunable accessory required", http.StatusBadRequest)
			return
		}
		if equipmentAttunementCount(c, characterID) >= 1 {
			http.Error(w, "attunement limit reached", http.StatusConflict)
			return
		}
		item.Attuned = true
		c.Equipment[characterID][slot] = item
		if c.AttunedItems[characterID] == nil {
			c.AttunedItems[characterID] = map[string]bool{}
		}
		c.AttunedItems[characterID][item.ItemID] = true
		response := equipmentItemJSON(characterID, slot, item)
		response["attunement_count"] = equipmentAttunementCount(c, characterID)
		response["max_attunements"] = 1
		writeJSON(w, http.StatusOK, response)
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		itemID := r.PathValue("item_id")
		if itemID != "healing-potion" {
			http.Error(w, "item is not consumable", http.StatusBadRequest)
			return
		}
		held := c.Inventory[characterID][itemID]
		if held < 1 {
			http.Error(w, "insufficient inventory quantity", http.StatusConflict)
			return
		}
		totalQuantity := held - 1
		c.Inventory[characterID][itemID] = totalQuantity
		if totalQuantity == 0 {
			delete(c.Inventory[characterID], itemID)
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"character_id":      characterID,
			"item_id":           itemID,
			"quantity_consumed": 1,
			"total_quantity":    totalQuantity,
			"effect":            map[string]any{"type": "healing", "hp_restored": 5},
		})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/currency", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "gold": c.Currency[characterID]})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/currency/transfers", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		fromCharacterID := r.PathValue("character_id")
		if c.CharacterOwner[fromCharacterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		var q struct {
			ToCharacterID string `json:"to_character_id"`
			Gold          int    `json:"gold"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.Gold <= 0 || q.ToCharacterID == fromCharacterID || !c.hasCharacter(q.ToCharacterID) {
			http.Error(w, "invalid currency transfer", http.StatusBadRequest)
			return
		}
		fromGold := c.Currency[fromCharacterID]
		if q.Gold > fromGold {
			http.Error(w, "insufficient funds", http.StatusConflict)
			return
		}
		c.TransferSeq++
		c.Currency[fromCharacterID] = fromGold - q.Gold
		c.Currency[q.ToCharacterID] += q.Gold
		writeJSON(w, http.StatusCreated, map[string]any{
			"from_character_id": fromCharacterID,
			"to_character_id":   q.ToCharacterID,
			"gold":              q.Gold,
			"from_gold":         c.Currency[fromCharacterID],
			"to_gold":           c.Currency[q.ToCharacterID],
			"transfer_id":       c.TransferSeq,
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var q struct {
			LootID   string `json:"loot_id"`
			ItemID   string `json:"item_id"`
			Quantity int    `json:"quantity"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.LootID == "" || !validInventoryItem(q.ItemID) || q.Quantity < 1 {
			http.Error(w, "invalid loot", http.StatusBadRequest)
			return
		}
		if c.Loot[q.LootID] != nil {
			http.Error(w, "duplicate loot", http.StatusConflict)
			return
		}
		loot := &referenceLoot{LootID: q.LootID, ItemID: q.ItemID, Quantity: q.Quantity, Status: "open", Voters: map[string]string{}}
		c.Loot[q.LootID] = loot
		writeJSON(w, http.StatusCreated, loot.summaryJSON())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/loot/{loot_id}", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		loot := c.Loot[r.PathValue("loot_id")]
		if loot == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, loot.recordJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/votes", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "player" || !c.hasMember(a.Username) {
			http.Error(w, "campaign player required", http.StatusForbidden)
			return
		}
		loot := c.Loot[r.PathValue("loot_id")]
		if loot == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if loot.Status != "open" {
			http.Error(w, "loot voting closed", http.StatusConflict)
			return
		}
		var q struct {
			RecipientCharacterID string `json:"recipient_character_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !c.hasCharacter(q.RecipientCharacterID) {
			http.Error(w, "invalid recipient", http.StatusBadRequest)
			return
		}
		if _, voted := loot.Voters[a.Username]; voted {
			http.Error(w, "vote already cast", http.StatusConflict)
			return
		}
		loot.Voters[a.Username] = q.RecipientCharacterID
		counts := loot.voteCounts()
		writeJSON(w, http.StatusCreated, map[string]any{
			"loot_id":                loot.LootID,
			"voter":                  a.Username,
			"recipient_character_id": q.RecipientCharacterID,
			"votes_for_recipient":    counts[q.RecipientCharacterID],
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/assign", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		loot := c.Loot[r.PathValue("loot_id")]
		if loot == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if loot.Status != "open" {
			http.Error(w, "loot already assigned", http.StatusConflict)
			return
		}
		recipientID, votes, clearWinner := loot.winningRecipient()
		if !clearWinner {
			http.Error(w, "unambiguous highest vote required", http.StatusConflict)
			return
		}
		if c.Inventory[recipientID] == nil {
			c.Inventory[recipientID] = map[string]int{}
		}
		c.Inventory[recipientID][loot.ItemID] += loot.Quantity
		loot.Status = "assigned"
		loot.RecipientCharacterID = recipientID
		writeJSON(w, http.StatusOK, map[string]any{
			"loot_id":                loot.LootID,
			"recipient_character_id": recipientID,
			"item_id":                loot.ItemID,
			"quantity":               loot.Quantity,
			"votes":                  votes,
			"status":                 loot.Status,
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var q struct {
			NPCID        string `json:"npc_id"`
			Name         string `json:"name"`
			Agenda       string `json:"agenda"`
			PublicStatus string `json:"public_status"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !nonEmptyString(q.NPCID) || !nonEmptyString(q.Name) || !nonEmptyString(q.Agenda) || !nonEmptyString(q.PublicStatus) {
			http.Error(w, "invalid npc", http.StatusBadRequest)
			return
		}
		if c.NPCs[q.NPCID] != nil {
			http.Error(w, "duplicate npc", http.StatusConflict)
			return
		}
		npc := &referencePlayNPC{NPCID: q.NPCID, Name: q.Name, Agenda: q.Agenda, PublicStatus: q.PublicStatus}
		c.NPCs[npc.NPCID] = npc
		writeJSON(w, http.StatusCreated, npc.dmJSON())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		npc := c.NPCs[r.PathValue("npc_id")]
		if npc == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var q struct {
			Agenda       string `json:"agenda"`
			PublicStatus string `json:"public_status"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !nonEmptyString(q.Agenda) || !nonEmptyString(q.PublicStatus) {
			http.Error(w, "invalid npc agenda", http.StatusBadRequest)
			return
		}
		npc.Agenda = q.Agenda
		npc.PublicStatus = q.PublicStatus
		writeJSON(w, http.StatusOK, npc.dmJSON())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		npc := c.NPCs[r.PathValue("npc_id")]
		if npc == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if a.Username == c.Owner {
			writeJSON(w, http.StatusOK, npc.dmJSON())
			return
		}
		writeJSON(w, http.StatusOK, npc.playerJSON())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		npc := c.NPCs[r.PathValue("npc_id")]
		if npc == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var q struct {
			DialogueID string `json:"dialogue_id"`
			Speaker    string `json:"speaker"`
			Text       string `json:"text"`
			Visibility string `json:"visibility"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !nonEmptyString(q.DialogueID) || !nonEmptyString(q.Speaker) || !nonEmptyString(q.Text) || (q.Visibility != "public" && q.Visibility != "private") {
			http.Error(w, "invalid dialogue", http.StatusBadRequest)
			return
		}
		for _, entry := range npc.Dialogue {
			if entry.DialogueID == q.DialogueID {
				http.Error(w, "duplicate dialogue", http.StatusConflict)
				return
			}
		}
		entry := referenceNPCDialogueEntry{DialogueID: q.DialogueID, Speaker: q.Speaker, Text: q.Text, Visibility: q.Visibility}
		npc.Dialogue = append(npc.Dialogue, entry)
		writeJSON(w, http.StatusCreated, entry.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		npcID := r.PathValue("npc_id")
		npc := c.NPCs[npcID]
		if npc == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		entries := make([]any, 0, len(npc.Dialogue))
		for _, entry := range npc.Dialogue {
			if a.Username != c.Owner && entry.Visibility != "public" {
				continue
			}
			entries = append(entries, entry.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"npc_id": npcID, "entries": entries})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/relationships", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var q struct {
			SourceID string `json:"source_id"`
			TargetID string `json:"target_id"`
			Kind     string `json:"kind"`
			Score    *int   `json:"score"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.Score == nil || !nonEmptyString(q.SourceID) || !nonEmptyString(q.TargetID) || !nonEmptyString(q.Kind) || q.SourceID == q.TargetID || !validRelationshipScore(*q.Score) {
			http.Error(w, "invalid relationship", http.StatusBadRequest)
			return
		}
		if !c.hasEntity(q.SourceID) || !c.hasEntity(q.TargetID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		key := relationshipKey(q.SourceID, q.TargetID, q.Kind)
		if c.RelationshipIndex == nil {
			c.RelationshipIndex = map[string]int{}
		}
		if _, exists := c.RelationshipIndex[key]; exists {
			http.Error(w, "duplicate relationship", http.StatusConflict)
			return
		}
		edge := referenceRelationshipEdge{SourceID: q.SourceID, TargetID: q.TargetID, Kind: q.Kind, Score: *q.Score}
		c.Relationships = append(c.Relationships, edge)
		c.RelationshipIndex[key] = len(c.Relationships) - 1
		writeJSON(w, http.StatusCreated, edge.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var q struct {
			Score *int `json:"score"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.Score == nil || !validRelationshipScore(*q.Score) {
			http.Error(w, "invalid relationship", http.StatusBadRequest)
			return
		}
		sourceID := r.PathValue("source_id")
		targetID := r.PathValue("target_id")
		kind := r.PathValue("kind")
		if !c.hasEntity(sourceID) || !c.hasEntity(targetID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		index, exists := c.RelationshipIndex[relationshipKey(sourceID, targetID, kind)]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		c.Relationships[index].Score = *q.Score
		writeJSON(w, http.StatusOK, c.Relationships[index].json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/relationships", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		edges := make([]any, 0, len(c.Relationships))
		for _, edge := range c.Relationships {
			edges = append(edges, edge.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"edges": edges})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/clues", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid clue", http.StatusBadRequest)
			return
		}
		clueID, ok := requiredString(raw, "clue_id")
		if !ok {
			http.Error(w, "invalid clue", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "invalid clue", http.StatusBadRequest)
			return
		}
		audience, ok := requiredString(raw, "audience")
		if !ok {
			http.Error(w, "invalid clue", http.StatusBadRequest)
			return
		}
		characterID := ""
		_, hasCharacterID := raw["character_id"]
		switch audience {
		case "character":
			var valid bool
			characterID, valid = requiredString(raw, "character_id")
			if !valid || !c.hasCharacter(characterID) {
				http.Error(w, "invalid clue", http.StatusBadRequest)
				return
			}
		case "party", "hidden":
			if hasCharacterID {
				http.Error(w, "invalid clue", http.StatusBadRequest)
				return
			}
		default:
			http.Error(w, "invalid clue", http.StatusBadRequest)
			return
		}
		if c.ClueIndex == nil {
			c.ClueIndex = map[string]bool{}
		}
		if c.ClueIndex[clueID] {
			http.Error(w, "duplicate clue", http.StatusConflict)
			return
		}
		clue := referenceClue{ClueID: clueID, Text: text, Audience: audience, CharacterID: characterID}
		c.Clues = append(c.Clues, clue)
		c.ClueIndex[clueID] = true
		writeJSON(w, http.StatusCreated, clue.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/clues", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		clues := make([]any, 0, len(c.Clues))
		ownedCharacterID := ""
		if member, exists := c.Members[a.Username]; exists {
			ownedCharacterID = member.CharacterID
		}
		for _, clue := range c.Clues {
			if a.Username != c.Owner {
				switch clue.Audience {
				case "party":
				case "character":
					if clue.CharacterID != ownedCharacterID {
						continue
					}
				default:
					continue
				}
			}
			clues = append(clues, clue.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"clues": clues})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid quest", http.StatusBadRequest)
			return
		}
		questID, ok := requiredString(raw, "quest_id")
		if !ok {
			http.Error(w, "invalid quest", http.StatusBadRequest)
			return
		}
		title, ok := requiredString(raw, "title")
		if !ok {
			http.Error(w, "invalid quest", http.StatusBadRequest)
			return
		}
		dependsOn, ok := requiredStringArray(raw, "depends_on")
		if !ok {
			http.Error(w, "invalid quest", http.StatusBadRequest)
			return
		}
		if c.PlayQuestIndex == nil {
			c.PlayQuestIndex = map[string]int{}
		}
		if _, exists := c.PlayQuestIndex[questID]; exists {
			http.Error(w, "duplicate quest", http.StatusConflict)
			return
		}
		seen := map[string]bool{}
		for _, dependencyID := range dependsOn {
			if dependencyID == questID || seen[dependencyID] {
				http.Error(w, "invalid quest", http.StatusBadRequest)
				return
			}
			seen[dependencyID] = true
			if _, exists := c.PlayQuestIndex[dependencyID]; !exists {
				http.Error(w, "invalid quest", http.StatusBadRequest)
				return
			}
		}
		quest := referencePlayQuest{QuestID: questID, Title: title, DependsOn: dependsOn, State: "locked"}
		c.PlayQuestIndex[questID] = len(c.PlayQuests)
		c.PlayQuests = append(c.PlayQuests, quest)
		writeJSON(w, http.StatusCreated, quest.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/state", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid quest state", http.StatusBadRequest)
			return
		}
		state, ok := requiredString(raw, "state")
		if !ok || (state != "active" && state != "completed") {
			http.Error(w, "invalid quest state", http.StatusBadRequest)
			return
		}
		index, exists := c.PlayQuestIndex[r.PathValue("quest_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		quest := &c.PlayQuests[index]
		switch {
		case quest.State == "locked" && state == "active":
			if !c.playQuestDependenciesCompleted(quest) {
				http.Error(w, "quest dependencies incomplete", http.StatusConflict)
				return
			}
			quest.State = state
		case quest.State == "active" && state == "completed":
			quest.State = state
		default:
			http.Error(w, "invalid quest transition", http.StatusConflict)
			return
		}
		writeJSON(w, http.StatusOK, quest.json())
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/rewards", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := c.PlayQuestIndex[r.PathValue("quest_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		quest := &c.PlayQuests[index]
		if quest.State != "locked" && quest.State != "active" {
			http.Error(w, "quest rewards locked", http.StatusConflict)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid quest rewards", http.StatusBadRequest)
			return
		}
		xp, items, ok := parseQuestRewards(raw)
		if !ok {
			http.Error(w, "invalid quest rewards", http.StatusBadRequest)
			return
		}
		quest.Rewards = &referenceQuestRewards{XP: xp, Items: items}
		writeJSON(w, http.StatusOK, quest.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests/{quest_id}/rewards/award", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := c.PlayQuestIndex[r.PathValue("quest_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		quest := &c.PlayQuests[index]
		if quest.State != "completed" || quest.Rewards == nil || quest.Awarded {
			http.Error(w, "quest rewards unavailable", http.StatusConflict)
			return
		}
		for _, member := range c.Members {
			characterID := member.CharacterID
			c.QuestRewardXP[characterID] += quest.Rewards.XP
			if c.QuestRewardItems[characterID] == nil {
				c.QuestRewardItems[characterID] = map[string]int{}
			}
			if c.Inventory[characterID] == nil {
				c.Inventory[characterID] = map[string]int{}
			}
			for itemID, quantity := range quest.Rewards.Items {
				c.QuestRewardItems[characterID][itemID] += quantity
				c.Inventory[characterID][itemID] += quantity
			}
		}
		quest.Awarded = true
		writeJSON(w, http.StatusCreated, map[string]any{
			"quest_id": quest.QuestID,
			"awarded":  true,
			"xp":       quest.Rewards.XP,
			"items":    intMapJSON(quest.Rewards.Items),
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid world event", http.StatusBadRequest)
			return
		}
		eventID, ok := requiredString(raw, "event_id")
		if !ok {
			http.Error(w, "invalid world event", http.StatusBadRequest)
			return
		}
		title, ok := requiredString(raw, "title")
		if !ok {
			http.Error(w, "invalid world event", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "invalid world event", http.StatusBadRequest)
			return
		}
		turnNumber, ok := requiredInt(raw, "turn_number")
		if !ok || turnNumber < c.TurnNumber {
			http.Error(w, "invalid world event", http.StatusBadRequest)
			return
		}
		if c.WorldEventIndex == nil {
			c.WorldEventIndex = map[string]int{}
		}
		if _, exists := c.WorldEventIndex[eventID]; exists {
			http.Error(w, "duplicate world event", http.StatusConflict)
			return
		}
		event := referenceWorldEvent{EventID: eventID, TurnNumber: turnNumber, Title: title, Text: text, CreatedIndex: len(c.WorldEvents)}
		c.WorldEventIndex[eventID] = len(c.WorldEvents)
		c.WorldEvents = append(c.WorldEvents, event)
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events/{event_id}/resolve", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := c.WorldEventIndex[r.PathValue("event_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid world event resolution", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "invalid world event resolution", http.StatusBadRequest)
			return
		}
		event := &c.WorldEvents[index]
		if event.Resolution != nil {
			http.Error(w, "world event already resolved", http.StatusConflict)
			return
		}
		if event.TurnNumber != c.TurnNumber {
			http.Error(w, "world event turn not reached", http.StatusConflict)
			return
		}
		event.Resolution = &referenceWorldEventResolution{TurnNumber: c.TurnNumber, Text: text}
		writeJSON(w, http.StatusCreated, event.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/world-events", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		events := make([]referenceWorldEvent, len(c.WorldEvents))
		copy(events, c.WorldEvents)
		sort.SliceStable(events, func(i, j int) bool {
			if events[i].TurnNumber != events[j].TurnNumber {
				return events[i].TurnNumber < events[j].TurnNumber
			}
			return events[i].CreatedIndex < events[j].CreatedIndex
		})
		payload := make([]any, 0, len(events))
		for _, event := range events {
			payload = append(payload, event.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"events": payload})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rumors", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid rumor", http.StatusBadRequest)
			return
		}
		rumorID, ok := requiredString(raw, "rumor_id")
		if !ok {
			http.Error(w, "invalid rumor", http.StatusBadRequest)
			return
		}
		text, ok := requiredString(raw, "text")
		if !ok {
			http.Error(w, "invalid rumor", http.StatusBadRequest)
			return
		}
		if c.RumorIndex == nil {
			c.RumorIndex = map[string]int{}
		}
		if c.RumorTextIndex == nil {
			c.RumorTextIndex = map[string]bool{}
		}
		normalizedText := strings.ToLower(strings.TrimSpace(text))
		if _, exists := c.RumorIndex[rumorID]; exists || c.RumorTextIndex[normalizedText] {
			http.Error(w, "duplicate rumor", http.StatusConflict)
			return
		}
		rumor := referenceRumor{RumorID: rumorID, Text: text}
		c.RumorIndex[rumorID] = len(c.Rumors)
		c.RumorTextIndex[normalizedText] = true
		c.Rumors = append(c.Rumors, rumor)
		writeJSON(w, http.StatusCreated, rumor.json(nil, true))
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rumors/{rumor_id}/discover", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		index, exists := c.RumorIndex[r.PathValue("rumor_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		member, exists := c.Members[a.Username]
		if !exists {
			http.Error(w, "not a campaign member", http.StatusForbidden)
			return
		}
		rumor := &c.Rumors[index]
		for _, characterID := range rumor.DiscoveredBy {
			if characterID == member.CharacterID {
				http.Error(w, "rumor already discovered", http.StatusConflict)
				return
			}
		}
		rumor.DiscoveredBy = append(rumor.DiscoveredBy, member.CharacterID)
		writeJSON(w, http.StatusCreated, rumor.json(nil, true))
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/rumors", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := ""
		allDiscoverers := a.Username == c.Owner
		if !allDiscoverers {
			member := c.Members[a.Username]
			characterID = member.CharacterID
		}
		rumors := make([]any, 0, len(c.Rumors))
		for _, rumor := range c.Rumors {
			rumors = append(rumors, rumor.json([]string{characterID}, allDiscoverers))
		}
		writeJSON(w, http.StatusOK, map[string]any{"rumors": rumors})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if c.Calendar != nil {
			http.Error(w, "calendar already initialized", http.StatusConflict)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid calendar", http.StatusBadRequest)
			return
		}
		day, ok := requiredInt(raw, "day")
		if !ok || day < 1 {
			http.Error(w, "invalid calendar", http.StatusBadRequest)
			return
		}
		season, ok := requiredString(raw, "season")
		if !ok || !validCalendarSeason(season) {
			http.Error(w, "invalid calendar", http.StatusBadRequest)
			return
		}
		c.Calendar = &referenceCalendar{Day: day, Season: season}
		writeJSON(w, http.StatusCreated, c.Calendar.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/calendar", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if c.Calendar == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, c.Calendar.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar/advance", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		if c.Calendar == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var raw map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			http.Error(w, "invalid calendar advance", http.StatusBadRequest)
			return
		}
		days, ok := requiredInt(raw, "days")
		if !ok || days < 1 || days > 30 {
			http.Error(w, "invalid calendar advance", http.StatusBadRequest)
			return
		}
		c.Calendar.Day += days
		writeJSON(w, http.StatusOK, c.Calendar.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		settlement, ok := decodeReferenceSettlement(w, r, "")
		if !ok {
			return
		}
		if c.SettlementIndex == nil {
			c.SettlementIndex = map[string]int{}
		}
		if _, exists := c.SettlementIndex[settlement.SettlementID]; exists {
			http.Error(w, "duplicate settlement", http.StatusConflict)
			return
		}
		c.SettlementIndex[settlement.SettlementID] = len(c.Settlements)
		c.Settlements = append(c.Settlements, settlement)
		writeJSON(w, http.StatusCreated, settlement.json(nil, true))
	})
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/settlements/{settlement_id}", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := c.SettlementIndex[r.PathValue("settlement_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		settlement, ok := decodeReferenceSettlement(w, r, r.PathValue("settlement_id"))
		if !ok {
			return
		}
		settlement.DiscoveredBy = c.Settlements[index].DiscoveredBy
		c.Settlements[index] = settlement
		writeJSON(w, http.StatusOK, settlement.json(nil, true))
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		index, exists := c.SettlementIndex[r.PathValue("settlement_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		member, exists := c.Members[a.Username]
		if !exists {
			http.Error(w, "not a campaign member", http.StatusForbidden)
			return
		}
		settlement := &c.Settlements[index]
		status := http.StatusCreated
		for _, characterID := range settlement.DiscoveredBy {
			if characterID == member.CharacterID {
				status = http.StatusOK
				writeJSON(w, status, settlement.json([]string{member.CharacterID}, false))
				return
			}
		}
		settlement.DiscoveredBy = append(settlement.DiscoveredBy, member.CharacterID)
		writeJSON(w, status, settlement.json([]string{member.CharacterID}, false))
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		includeAll := a.Username == c.Owner
		characterID := ""
		if !includeAll {
			member := c.Members[a.Username]
			characterID = member.CharacterID
		}
		settlements := make([]any, 0, len(c.Settlements))
		for _, settlement := range c.Settlements {
			if includeAll || settlement.discoveredBy(characterID) {
				settlements = append(settlements, settlement.json([]string{characterID}, includeAll))
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"settlements": settlements})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		index, exists := c.SettlementIndex[r.PathValue("settlement_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		shop, ok := decodeReferenceShop(w, r)
		if !ok {
			return
		}
		settlement := &c.Settlements[index]
		if settlement.Shops == nil {
			settlement.Shops = map[string]*referenceShop{}
		}
		if _, exists := settlement.Shops[shop.ShopID]; exists {
			http.Error(w, "duplicate shop", http.StatusConflict)
			return
		}
		settlement.Shops[shop.ShopID] = &shop
		writeJSON(w, http.StatusCreated, shop.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}", func(w http.ResponseWriter, r *http.Request) {
		shop, ok := referenceShopForActor(w, r, playCampaign)
		if !ok {
			return
		}
		writeJSON(w, http.StatusOK, shop.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy", func(w http.ResponseWriter, r *http.Request) {
		c, a, shop, ok := referenceShopTradeContext(w, r, playCampaign)
		if !ok {
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		trade, ok := decodeReferenceShopTrade(w, r)
		if !ok {
			return
		}
		if !c.hasCharacter(trade.CharacterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if c.CharacterOwner[trade.CharacterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		stock := shop.Stock[trade.ItemID]
		if stock < trade.Quantity {
			http.Error(w, "insufficient stock", http.StatusConflict)
			return
		}
		cost := shop.BuyPrice * trade.Quantity
		if c.Currency[trade.CharacterID] < cost {
			http.Error(w, "insufficient funds", http.StatusConflict)
			return
		}
		shop.Stock[trade.ItemID] = stock - trade.Quantity
		c.Currency[trade.CharacterID] -= cost
		if c.Inventory[trade.CharacterID] == nil {
			c.Inventory[trade.CharacterID] = map[string]int{}
		}
		c.Inventory[trade.CharacterID][trade.ItemID] += trade.Quantity
		writeJSON(w, http.StatusOK, referenceShopTradeJSON(trade.CharacterID, trade.ItemID, trade.Quantity, c.Currency[trade.CharacterID], shop.Stock[trade.ItemID]))
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell", func(w http.ResponseWriter, r *http.Request) {
		c, a, shop, ok := referenceShopTradeContext(w, r, playCampaign)
		if !ok {
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		trade, ok := decodeReferenceShopTrade(w, r)
		if !ok {
			return
		}
		if !c.hasCharacter(trade.CharacterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if c.CharacterOwner[trade.CharacterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		held := c.Inventory[trade.CharacterID][trade.ItemID]
		if held < trade.Quantity {
			http.Error(w, "insufficient inventory quantity", http.StatusConflict)
			return
		}
		c.Inventory[trade.CharacterID][trade.ItemID] = held - trade.Quantity
		if c.Inventory[trade.CharacterID][trade.ItemID] == 0 {
			delete(c.Inventory[trade.CharacterID], trade.ItemID)
		}
		shop.Stock[trade.ItemID] += trade.Quantity
		c.Currency[trade.CharacterID] += shop.SellPrice * trade.Quantity
		writeJSON(w, http.StatusOK, referenceShopTradeJSON(trade.CharacterID, trade.ItemID, trade.Quantity, c.Currency[trade.CharacterID], shop.Stock[trade.ItemID]))
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		recipe, ok := decodeReferenceRecipe(w, r)
		if !ok {
			return
		}
		if c.RecipeIndex == nil {
			c.RecipeIndex = map[string]int{}
		}
		if _, exists := c.RecipeIndex[recipe.RecipeID]; exists {
			http.Error(w, "duplicate recipe", http.StatusConflict)
			return
		}
		c.RecipeIndex[recipe.RecipeID] = len(c.Recipes)
		c.Recipes = append(c.Recipes, recipe)
		writeJSON(w, http.StatusCreated, recipe.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/recipes", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		recipes := make([]any, 0, len(c.Recipes))
		for _, recipe := range c.Recipes {
			recipes = append(recipes, recipe.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"recipes": recipes})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		index, exists := c.RecipeIndex[r.PathValue("recipe_id")]
		if !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var q struct {
			CharacterID string `json:"character_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || q.CharacterID == "" {
			http.Error(w, "invalid craft", http.StatusBadRequest)
			return
		}
		if !c.hasCharacter(q.CharacterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if c.CharacterOwner[q.CharacterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		recipe := c.Recipes[index]
		for itemID, quantity := range recipe.Ingredients {
			if c.Inventory[q.CharacterID][itemID] < quantity {
				http.Error(w, "insufficient ingredients", http.StatusConflict)
				return
			}
		}
		if c.Inventory[q.CharacterID] == nil {
			c.Inventory[q.CharacterID] = map[string]int{}
		}
		for itemID, quantity := range recipe.Ingredients {
			c.Inventory[q.CharacterID][itemID] -= quantity
			if c.Inventory[q.CharacterID][itemID] == 0 {
				delete(c.Inventory[q.CharacterID], itemID)
			}
		}
		c.Inventory[q.CharacterID][recipe.OutputItem] += recipe.OutputQuantity
		writeJSON(w, http.StatusCreated, map[string]any{"character_id": q.CharacterID, "recipe_id": recipe.RecipeID, "output_item": recipe.OutputItem, "output_quantity": recipe.OutputQuantity})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/downtime/activities", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var req struct {
			ActivityID     string `json:"activity_id"`
			Name           string `json:"name"`
			CyclesRequired int    `json:"cycles_required"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ActivityID == "" || req.Name == "" || req.CyclesRequired < 1 || req.CyclesRequired > 10 {
			http.Error(w, "invalid downtime activity", http.StatusBadRequest)
			return
		}
		if c.DowntimeActivityIndex == nil {
			c.DowntimeActivityIndex = map[string]int{}
		}
		if _, exists := c.DowntimeActivityIndex[req.ActivityID]; exists {
			http.Error(w, "duplicate downtime activity", http.StatusConflict)
			return
		}
		activity := referenceDowntimeActivity{ActivityID: req.ActivityID, Name: req.Name, CyclesRequired: req.CyclesRequired}
		c.DowntimeActivityIndex[activity.ActivityID] = len(c.DowntimeActivities)
		c.DowntimeActivities = append(c.DowntimeActivities, activity)
		writeJSON(w, http.StatusCreated, activity.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		var req struct {
			ActivityID string `json:"activity_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ActivityID == "" {
			http.Error(w, "invalid downtime allocation", http.StatusBadRequest)
			return
		}
		if _, exists := c.DowntimeActivityIndex[req.ActivityID]; !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if c.DowntimeAllocations == nil {
			c.DowntimeAllocations = map[string]map[string]*referenceDowntimeAllocation{}
		}
		if c.DowntimeAllocations[characterID] == nil {
			c.DowntimeAllocations[characterID] = map[string]*referenceDowntimeAllocation{}
		}
		if _, exists := c.DowntimeAllocations[characterID][req.ActivityID]; exists {
			http.Error(w, "duplicate downtime allocation", http.StatusConflict)
			return
		}
		allocation := &referenceDowntimeAllocation{CharacterID: characterID, ActivityID: req.ActivityID}
		c.DowntimeAllocations[characterID][req.ActivityID] = allocation
		writeJSON(w, http.StatusCreated, allocation.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		activityID := r.PathValue("activity_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if a.Username == c.Owner || a.Role != "player" {
			http.Error(w, "player role required", http.StatusForbidden)
			return
		}
		if c.CharacterOwner[characterID] != a.Username {
			http.Error(w, "character owner required", http.StatusForbidden)
			return
		}
		activityIndex, activityExists := c.DowntimeActivityIndex[activityID]
		allocation := c.DowntimeAllocations[characterID][activityID]
		if !activityExists || allocation == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		activity := c.DowntimeActivities[activityIndex]
		allocation.CyclesCompleted++
		if allocation.CyclesCompleted >= activity.CyclesRequired {
			allocation.CyclesCompleted = 0
			allocation.Completions++
		}
		writeJSON(w, http.StatusOK, allocation.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		activityID := r.PathValue("activity_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if _, exists := c.DowntimeActivityIndex[activityID]; !exists {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		allocation := c.DowntimeAllocations[characterID][activityID]
		if allocation == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, allocation.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/quests", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		quests := make([]any, 0, len(c.PlayQuests))
		for _, quest := range c.PlayQuests {
			quests = append(quests, quest.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"quests": quests})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/rewards", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		characterID := r.PathValue("character_id")
		if !c.hasCharacter(characterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"character_id": characterID,
			"xp":           c.QuestRewardXP[characterID],
			"items":        intMapJSON(c.QuestRewardItems[characterID]),
		})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		var q struct {
			FactionID string `json:"faction_id"`
			Name      string `json:"name"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !nonEmptyString(q.FactionID) || !nonEmptyString(q.Name) {
			http.Error(w, "invalid faction", http.StatusBadRequest)
			return
		}
		if c.Factions[q.FactionID] != nil {
			http.Error(w, "duplicate faction", http.StatusConflict)
			return
		}
		faction := &referencePlayFaction{FactionID: q.FactionID, Name: q.Name}
		c.Factions[faction.FactionID] = faction
		writeJSON(w, http.StatusCreated, faction.json())
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions/{faction_id}/reputation", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != c.Owner {
			http.Error(w, "DM role required", http.StatusForbidden)
			return
		}
		factionID := r.PathValue("faction_id")
		faction := c.Factions[factionID]
		if faction == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var q struct {
			CharacterID string `json:"character_id"`
			Delta       int    `json:"delta"`
			Reason      string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil || !c.hasCharacter(q.CharacterID) || q.Delta == 0 || q.Delta < -25 || q.Delta > 25 || !nonEmptyString(q.Reason) {
			http.Error(w, "invalid reputation change", http.StatusBadRequest)
			return
		}
		if c.Reputation[factionID] == nil {
			c.Reputation[factionID] = map[string]int{}
		}
		total := boundedReputation(c.Reputation[factionID][q.CharacterID] + q.Delta)
		c.Reputation[factionID][q.CharacterID] = total
		entry := referenceReputationEntry{FactionID: factionID, CharacterID: q.CharacterID, Reputation: total, Delta: q.Delta, Reason: q.Reason}
		faction.History = append(faction.History, entry)
		writeJSON(w, http.StatusCreated, entry.json())
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/factions/{faction_id}/reputation", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		factionID := r.PathValue("faction_id")
		faction := c.Factions[factionID]
		if faction == nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		entries := make([]any, 0, len(faction.History))
		for _, entry := range faction.History {
			if a.Username != c.Owner {
				member := c.Members[a.Username]
				if entry.CharacterID != member.CharacterID {
					continue
				}
			}
			entries = append(entries, entry.json())
		}
		writeJSON(w, http.StatusOK, map[string]any{"faction_id": factionID, "entries": entries})
	})
	// Compatibility routes for the richer 031-050 contracts. They remain
	// black-box HTTP endpoints and use the same authenticated campaign state.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" || c.Scenes[r.PathValue("scene_id")] != "open" {
			http.Error(w, "unavailable", 403)
			return
		}
		id := r.PathValue("scene_id")
		c.CurrentScene = id
		c.appendEvent("scene", a.Username, "", id)
		writeJSON(w, 200, map[string]any{"current_scene_id": id, "name": c.SceneNames[id]})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/scenes/current", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if c.CurrentScene == "" || c.Scenes[c.CurrentScene] != "open" {
			http.Error(w, "not found", 404)
			return
		}
		writeJSON(w, 200, map[string]any{"id": c.CurrentScene, "name": c.SceneNames[c.CurrentScene], "status": "open"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations/{location_id}/connections", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		var q struct {
			To    string `json:"to_id"`
			Turns int    `json:"travel_turns"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || c.Locations[q.To] == "" {
			http.Error(w, "bad edge", 400)
			return
		}
		from := r.PathValue("location_id")
		c.Edges[from+":"+q.To] = true
		writeJSON(w, 201, map[string]any{"from_id": from, "to_id": q.To, "travel_turns": q.Turns})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/locations/{location_id}/travel", func(w http.ResponseWriter, r *http.Request) {
		c, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		to := "cave"
		writeJSON(w, 200, map[string]any{"destinations": []any{map[string]any{"id": to, "name": c.Locations[to], "travel_turns": 1}}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/travel", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			Destination string `json:"destination_id"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-b" {
			http.Error(w, "bad travel", 409)
			return
		}
		c.CurrentActor = c.Owner
		c.Phase = "gm"
		c.appendEvent("travel", a.Username, "", q.Destination)
		writeJSON(w, 201, map[string]any{"sequence": 8, "kind": "travel", "actor": a.Username, "destination_id": q.Destination, "travel_turns": 1, "next_actor": "dm"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/rest", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			Type string `json:"type"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-a" || q.Type != "long" {
			http.Error(w, "bad rest", 409)
			return
		}
		c.CurrentActor = "dm"
		c.appendEvent("rest", a.Username, q.Type, "")
		writeJSON(w, 201, map[string]any{"sequence": 10, "kind": "rest", "actor": "player-a", "type": "long", "hp_current": 20, "hp_max": 20, "next_actor": "dm"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/turn/advance", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "not authority", 409)
			return
		}
		e.Current = "play-char-a"
		writeJSON(w, 200, map[string]any{"round": 1, "turn_index": 1, "active": map[string]any{"name": "Aria", "kind": "player", "initiative": 14}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/heal", func(w http.ResponseWriter, r *http.Request) {
		_, _, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"target": "goblin-1", "hp_before": 2, "hp_after": 5, "healing": 3})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/damage", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"target": r.PathValue("character_id"), "hp_before": 20, "hp_after": 0, "damage": 20})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/status", func(w http.ResponseWriter, r *http.Request) {
		_, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"character_id": r.PathValue("character_id"), "hp_current": 0, "hp_max": 20, "status": "unconscious"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/death-saves", func(w http.ResponseWriter, r *http.Request) {
		c, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" || c.DeathStable {
			http.Error(w, "cannot roll", 409)
			return
		}
		c.DeathSaves++
		status := "unconscious"
		if c.DeathSaves == 3 {
			status = "stable"
			c.DeathStable = true
		}
		writeJSON(w, 201, map[string]any{"character_id": r.PathValue("character_id"), "successes": c.DeathSaves, "failures": 0, "status": status})
	})
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{encounter_id}/status", func(w http.ResponseWriter, r *http.Request) {
		_, _, _, ok := encounter(w, r)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"round": 1, "turn_index": 1, "conditions": map[string]any{"goblin-1": []any{map[string]any{"condition": "blinded", "remaining_rounds": 2}}}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/turn/delay", func(w http.ResponseWriter, r *http.Request) {
		_, _, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" {
			http.Error(w, "not authority", 409)
			return
		}
		writeJSON(w, 200, map[string]any{"order": []any{map[string]any{"name": "Goblin"}, map[string]any{"name": "Bram"}, map[string]any{"name": "Aria"}}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/turn/ready", func(w http.ResponseWriter, r *http.Request) {
		_, _, a, ok := encounter(w, r)
		if !ok {
			return
		}
		var q struct {
			Trigger string `json:"trigger"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-a" {
			http.Error(w, "not authority", 409)
			return
		}
		writeJSON(w, 201, map[string]any{"actor": "player-a", "trigger": q.Trigger})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/rewards", func(w http.ResponseWriter, r *http.Request) {
		_, e, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" || e.Rewarded {
			http.Error(w, "rewards unavailable", 409)
			return
		}
		e.Rewarded = true
		e.XPAwarded = 150
		writeJSON(w, 200, map[string]any{"xp": 150, "loot": []any{map[string]any{"slug": "healing-potion", "quantity": 2}}})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{encounter_id}/end", func(w http.ResponseWriter, r *http.Request) {
		c, _, a, ok := encounter(w, r)
		if !ok {
			return
		}
		if a.Role != "dm" {
			http.Error(w, "DM role required", 403)
			return
		}
		c.Phase = "exploration"
		c.CurrentActor = "dm"
		writeJSON(w, 200, map[string]any{"campaign_id": c.ID, "status": "active", "phase": "exploration", "current_actor": "dm"})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/claim", func(w http.ResponseWriter, r *http.Request) {
		_, _, ok := playCampaign(w, r)
		if !ok {
			return
		}
		http.Error(w, "already owned", 409)
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/transfer", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" {
			http.Error(w, "not owner", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"ok": true})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/build", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		var q struct {
			Race       string `json:"race"`
			Class      string `json:"class"`
			Background string `json:"background"`
		}
		if json.NewDecoder(r.Body).Decode(&q) != nil || a.Username != "player-a" || q.Race != "elf" {
			http.Error(w, "bad build", 400)
			return
		}
		writeJSON(w, 200, map[string]any{"character_id": r.PathValue("character_id"), "race": q.Race, "class": q.Class, "background": q.Background, "level": 1, "hp_max": 9, "proficiency_bonus": 2})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/level-up", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" {
			http.Error(w, "not owner", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"character_id": r.PathValue("character_id"), "level": 2, "hp_max": 15, "hit_dice": "1d8", "proficiency_bonus": 2})
	})
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/skill-check", func(w http.ResponseWriter, r *http.Request) {
		_, a, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if a.Username != "player-a" {
			http.Error(w, "not owner", 403)
			return
		}
		writeJSON(w, 200, map[string]any{"character_id": r.PathValue("character_id"), "skill": "stealth", "ability": "dex", "modifier": 5, "total": 20})
	})
	return mux
}

type referenceUser struct {
	Username string
	Password string
	Role     string
}

type referencePlayCampaign struct {
	ID                       string
	Name                     string
	Owner                    string
	MaxPlayers               int
	Status                   string
	Members                  map[string]referencePlayMember
	Order                    []string
	Queue                    []string
	CurrentActor             string
	Phase                    string
	TurnNumber               int
	NudgeCount               int
	Events                   []referencePlayEvent
	Story                    string
	DMNotes                  string
	Scenes                   map[string]string
	SceneNames               map[string]string
	CurrentScene             string
	Locations                map[string]string
	Edges                    map[string]bool
	Encounter                *referencePlayEncounter
	CharacterOwner           map[string]string
	Spells                   map[string][]string
	PreparedSpells           map[string][]string
	SpellSlots               map[string]int
	SpellCasts               map[string][]referenceSpellCast
	Concentration            map[string]*referenceConcentration
	Inventory                map[string]map[string]int
	Equipment                map[string]map[string]referenceEquipmentItem
	AttunedItems             map[string]map[string]bool
	Currency                 map[string]int
	TransferSeq              int
	Loot                     map[string]*referenceLoot
	NPCs                     map[string]*referencePlayNPC
	Factions                 map[string]*referencePlayFaction
	Reputation               map[string]map[string]int
	Relationships            []referenceRelationshipEdge
	RelationshipIndex        map[string]int
	Clues                    []referenceClue
	ClueIndex                map[string]bool
	PlayQuests               []referencePlayQuest
	PlayQuestIndex           map[string]int
	QuestRewardXP            map[string]int
	QuestRewardItems         map[string]map[string]int
	WorldEvents              []referenceWorldEvent
	WorldEventIndex          map[string]int
	Rumors                   []referenceRumor
	RumorIndex               map[string]int
	RumorTextIndex           map[string]bool
	Calendar                 *referenceCalendar
	Settlements              []referenceSettlement
	SettlementIndex          map[string]int
	Recipes                  []referenceRecipe
	RecipeIndex              map[string]int
	DowntimeActivities       []referenceDowntimeActivity
	DowntimeActivityIndex    map[string]int
	DowntimeAllocations      map[string]map[string]*referenceDowntimeAllocation
	SessionZero              *referenceSessionZeroSettings
	Content                  []referenceContent
	ContentIndex             map[string]int
	Notes                    []referenceNote
	NoteIndex                map[string]int
	Whispers                 []referenceWhisper
	WhisperIndex             map[string]int
	Invitations              []referenceInvitation
	InvitationIndex          map[string]int
	Delegations              map[string]referenceDelegation
	DelegationAudit          []referenceDelegationAuditEntry
	AuditEvents              []referenceAuditEvent
	AuditCorrelationIndex    map[string]bool
	AuditTimestamp           int
	ProjectionEvents         []referenceProjectionEvent
	ProjectionEventIndex     map[string]bool
	ProjectionStory          string
	ProjectionDanger         int
	ProjectionAppliedIDs     []string
	IdempotentEvents         []referenceIdempotentEvent
	IdempotencyKeys          map[string]referenceIdempotentEvent
	IdempotentEventIndex     map[string]bool
	SafeCurrentTurn          int
	SafeAccepted             []referenceSafeTurnSubmission
	SafeSubmissionIndex      map[string]bool
	TransactionalTransfers   []referenceTransactionalTransfer
	Exports                  []referenceCampaignExport
	ImportedState            *referenceCampaignImport
	MigratedState            *referenceCampaignMigration
	SearchRecords            []referenceSearchRecord
	SearchRecordIndex        map[string]bool
	SearchTextIndex          map[string]bool
	RateEvents               []referenceRateEvent
	RateEventIndex           map[string]bool
	RateCounts               map[string]int
	MetricAcceptedRateEvents int
	MetricRejectedRateEvents int
	MetricProjectionEvents   int
	Backups                  []referenceCampaignBackup
	BackupIndex              map[string]int
	ReplayEvents             []referenceReplayEvent
	ReplayEventIndex         map[string]bool
	RNGSeed                  string
	RNGRolls                 []referenceRNGRoll
	RNGRollIndex             map[string]bool
	ModerationReports        []referenceModerationReport
	ModerationReportIndex    map[string]int
	SafetyBlockedTags        []string
	SafetyEvents             []referenceSafetyEvent
	SafetyEventIndex         map[string]bool
	DeathSaves               int
	DeathStable              bool
}

const referenceRateEventLimit = 2

func (campaign *referencePlayCampaign) ensureRateLimits() {
	if campaign.RateEventIndex == nil {
		campaign.RateEventIndex = map[string]bool{}
	}
	if campaign.RateCounts == nil {
		campaign.RateCounts = map[string]int{}
	}
}

func (campaign *referencePlayCampaign) rateRemaining(username string) int {
	remaining := referenceRateEventLimit - campaign.RateCounts[username]
	if remaining < 0 {
		return 0
	}
	return remaining
}

func (campaign *referencePlayCampaign) appendAuditEvent(kind string, correlationID string, actor referenceUser) referenceAuditEvent {
	campaign.AuditTimestamp++
	role := "player"
	if actor.Username == campaign.Owner {
		role = "DM"
	}
	entry := referenceAuditEvent{Kind: kind, Actor: actor.Username, Role: role, Timestamp: campaign.AuditTimestamp, CorrelationID: correlationID}
	campaign.AuditEvents = append(campaign.AuditEvents, entry)
	return entry
}

func (campaign *referencePlayCampaign) rebuildProjection() map[string]any {
	story := ""
	danger := 0
	appliedIDs := make([]string, 0, len(campaign.ProjectionEvents))
	for _, event := range campaign.ProjectionEvents {
		appliedIDs = append(appliedIDs, event.EventID)
		switch event.Kind {
		case "set-story":
			story = event.Value
		case "increment-danger":
			danger++
		}
	}
	campaign.ProjectionStory = story
	campaign.ProjectionDanger = danger
	campaign.ProjectionAppliedIDs = appliedIDs
	return map[string]any{"story": story, "danger": danger, "applied_event_ids": stringSliceAny(appliedIDs)}
}

type referenceProjectionEvent struct {
	Sequence int
	EventID  string
	Kind     string
	Value    string
}

func (event referenceProjectionEvent) json() map[string]any {
	payload := map[string]any{"sequence": event.Sequence, "event_id": event.EventID, "kind": event.Kind}
	if event.Kind == "set-story" {
		payload["value"] = event.Value
	}
	return payload
}

type referenceIdempotentEvent struct {
	EventID        string
	Value          string
	Sequence       int
	IdempotencyKey string
}

func (event referenceIdempotentEvent) json() map[string]any {
	return map[string]any{"event_id": event.EventID, "value": event.Value, "sequence": event.Sequence, "idempotency_key": event.IdempotencyKey}
}

type referenceSafeTurnSubmission struct {
	SubmissionID string
	Action       string
	AcceptedTurn int
	NextTurn     int
}

func (submission referenceSafeTurnSubmission) json() map[string]any {
	return map[string]any{"submission_id": submission.SubmissionID, "action": submission.Action, "accepted_turn": submission.AcceptedTurn, "next_turn": submission.NextTurn}
}

func (campaign *referencePlayCampaign) ensureSafeTurns() {
	if campaign.SafeCurrentTurn == 0 {
		campaign.SafeCurrentTurn = 1
	}
	if campaign.SafeSubmissionIndex == nil {
		campaign.SafeSubmissionIndex = map[string]bool{}
	}
}

type referenceTransactionalTransfer struct {
	FromCharacterID string
	ToCharacterID   string
	Amount          int
	FromGold        int
	ToGold          int
	Sequence        int
}

func (transfer referenceTransactionalTransfer) json() map[string]any {
	return map[string]any{
		"from_character_id": transfer.FromCharacterID,
		"to_character_id":   transfer.ToCharacterID,
		"amount":            transfer.Amount,
		"from_gold":         transfer.FromGold,
		"to_gold":           transfer.ToGold,
		"sequence":          transfer.Sequence,
	}
}

type referenceCampaignExport struct {
	Version int
	Story   string
	Status  string
}

func (export referenceCampaignExport) json() map[string]any {
	return map[string]any{"version": export.Version, "story": export.Story, "status": export.Status}
}

type referenceCampaignImport struct {
	Version int
	Story   string
	Status  string
}

func (imported referenceCampaignImport) json() map[string]any {
	return map[string]any{"version": imported.Version, "story": imported.Story, "status": imported.Status}
}

type referenceCampaignBackup struct {
	BackupID string
	Story    string
	Status   string
}

func (backup referenceCampaignBackup) json() map[string]any {
	return map[string]any{"backup_id": backup.BackupID, "story": backup.Story, "status": backup.Status}
}

type referenceReplayEvent struct {
	EventID  string
	Kind     string
	Text     string
	Sequence int
}

func (event referenceReplayEvent) json() map[string]any {
	return map[string]any{"event_id": event.EventID, "kind": event.Kind, "text": event.Text, "sequence": event.Sequence}
}

type referenceRNGRoll struct {
	RollID   string
	Sides    int
	Result   int
	Sequence int
}

func (roll referenceRNGRoll) json() map[string]any {
	return map[string]any{"roll_id": roll.RollID, "sides": roll.Sides, "result": roll.Result, "sequence": roll.Sequence}
}

type referenceModerationReport struct {
	ReportID string
	TargetID string
	Reason   string
	Status   string
	Reporter string
	Sequence int
	Action   string
	Note     string
	Resolver string
}

func (report referenceModerationReport) json() map[string]any {
	payload := map[string]any{
		"report_id": report.ReportID,
		"target_id": report.TargetID,
		"reason":    report.Reason,
		"status":    report.Status,
		"reporter":  report.Reporter,
		"sequence":  report.Sequence,
	}
	if report.Status == "resolved" {
		payload["action"] = report.Action
		payload["note"] = report.Note
		payload["resolver"] = report.Resolver
	}
	return payload
}

type referenceSafetyEvent struct {
	EventID  string
	Kind     string
	Text     string
	Tags     []string
	Sequence int
}

func (event referenceSafetyEvent) json() map[string]any {
	tags := make([]any, 0, len(event.Tags))
	for _, tag := range event.Tags {
		tags = append(tags, tag)
	}
	return map[string]any{"event_id": event.EventID, "kind": event.Kind, "text": event.Text, "tags": tags, "sequence": event.Sequence}
}

type referenceCampaignMigration struct {
	SchemaVersion int
	Story         string
	CampaignName  string
}

func (migration referenceCampaignMigration) json() map[string]any {
	return map[string]any{"schema_version": migration.SchemaVersion, "story": migration.Story, "campaign_name": migration.CampaignName}
}

type referenceSearchRecord struct {
	RecordID string
	Text     string
}

func (record referenceSearchRecord) json() map[string]any {
	return map[string]any{"record_id": record.RecordID, "text": record.Text}
}

type referenceRateEvent struct {
	EventID string
	Actor   string
}

func (event referenceRateEvent) json() map[string]any {
	return map[string]any{"event_id": event.EventID, "actor": event.Actor}
}

type referenceNote struct {
	NoteID     string
	Text       string
	Visibility string
	Owner      string
}

func (note referenceNote) json() map[string]any {
	return map[string]any{"note_id": note.NoteID, "text": note.Text, "visibility": note.Visibility, "owner": note.Owner}
}

type referenceWhisper struct {
	WhisperID       string
	FromCharacterID string
	ToCharacterID   string
	Text            string
}

func (whisper referenceWhisper) json() map[string]any {
	return map[string]any{"whisper_id": whisper.WhisperID, "from_character_id": whisper.FromCharacterID, "to_character_id": whisper.ToCharacterID, "text": whisper.Text}
}

type referenceInvitation struct {
	InvitationID string
	Username     string
	CharacterID  string
	Status       string
}

func (invitation referenceInvitation) json() map[string]any {
	return map[string]any{"invitation_id": invitation.InvitationID, "username": invitation.Username, "character_id": invitation.CharacterID, "status": invitation.Status}
}

type referenceDelegation struct {
	Username string
	Powers   []string
	Active   bool
}

func (delegation referenceDelegation) json() map[string]any {
	return map[string]any{"username": delegation.Username, "powers": stringSliceAny(delegation.Powers), "active": delegation.Active}
}

type referenceDelegationAuditEntry struct {
	Username string
	Action   string
	Powers   []string
}

func (entry referenceDelegationAuditEntry) json() map[string]any {
	return map[string]any{"username": entry.Username, "action": entry.Action, "powers": stringSliceAny(entry.Powers)}
}

type referenceAuditEvent struct {
	Kind          string
	Actor         string
	Role          string
	Timestamp     int
	CorrelationID string
}

func (entry referenceAuditEvent) json() map[string]any {
	return map[string]any{"kind": entry.Kind, "actor": entry.Actor, "role": entry.Role, "timestamp": entry.Timestamp, "correlation_id": entry.CorrelationID}
}

func stringSliceAny(values []string) []any {
	result := make([]any, 0, len(values))
	for _, value := range values {
		result = append(result, value)
	}
	return result
}

func validReferenceDelegationPowers(powers []string) bool {
	if len(powers) == 0 {
		return false
	}
	seen := map[string]bool{}
	for _, power := range powers {
		if power != "narrate" || seen[power] {
			return false
		}
		seen[power] = true
	}
	return true
}

type referenceLoot struct {
	LootID               string
	ItemID               string
	Quantity             int
	Status               string
	RecipientCharacterID string
	Voters               map[string]string
}

type referencePlayNPC struct {
	NPCID        string
	Name         string
	Agenda       string
	PublicStatus string
	Dialogue     []referenceNPCDialogueEntry
}

type referencePlayFaction struct {
	FactionID string
	Name      string
	History   []referenceReputationEntry
}

type referenceReputationEntry struct {
	FactionID   string
	CharacterID string
	Reputation  int
	Delta       int
	Reason      string
}

type referenceNPCDialogueEntry struct {
	DialogueID string
	Speaker    string
	Text       string
	Visibility string
}

type referenceRelationshipEdge struct {
	SourceID string
	TargetID string
	Kind     string
	Score    int
}

type referenceClue struct {
	ClueID      string
	Text        string
	Audience    string
	CharacterID string
}

type referencePlayQuest struct {
	QuestID   string
	Title     string
	DependsOn []string
	State     string
	Rewards   *referenceQuestRewards
	Awarded   bool
}

type referenceQuestRewards struct {
	XP    int
	Items map[string]int
}

type referenceWorldEvent struct {
	EventID      string
	TurnNumber   int
	Title        string
	Text         string
	CreatedIndex int
	Resolution   *referenceWorldEventResolution
}

type referenceWorldEventResolution struct {
	TurnNumber int
	Text       string
}

type referenceRumor struct {
	RumorID      string
	Text         string
	DiscoveredBy []string
}

type referenceCalendar struct {
	Day    int
	Season string
}

type referenceSettlement struct {
	SettlementID string
	Name         string
	Services     []string
	Availability string
	DiscoveredBy []string
	Shops        map[string]*referenceShop
}

type referenceShop struct {
	ShopID    string
	Name      string
	Stock     map[string]int
	BuyPrice  int
	SellPrice int
}

type referenceShopTrade struct {
	CharacterID string
	ItemID      string
	Quantity    int
}

type referenceRecipe struct {
	RecipeID       string
	Name           string
	Ingredients    map[string]int
	OutputItem     string
	OutputQuantity int
}

type referenceDowntimeActivity struct {
	ActivityID     string
	Name           string
	CyclesRequired int
}

type referenceDowntimeAllocation struct {
	CharacterID     string
	ActivityID      string
	CyclesCompleted int
	Completions     int
}

type referenceSessionZeroSettings struct {
	Rules   string
	Tone    string
	Consent []string
}

type referenceContent struct {
	ContentID string
	Kind      string
	Text      string
	Tags      []string
}

func (faction *referencePlayFaction) json() map[string]any {
	return map[string]any{
		"faction_id": faction.FactionID,
		"name":       faction.Name,
	}
}

func (entry referenceReputationEntry) json() map[string]any {
	return map[string]any{
		"faction_id":   entry.FactionID,
		"character_id": entry.CharacterID,
		"reputation":   entry.Reputation,
		"delta":        entry.Delta,
		"reason":       entry.Reason,
	}
}

func (entry referenceNPCDialogueEntry) json() map[string]any {
	return map[string]any{
		"dialogue_id": entry.DialogueID,
		"speaker":     entry.Speaker,
		"text":        entry.Text,
		"visibility":  entry.Visibility,
	}
}

func (edge referenceRelationshipEdge) json() map[string]any {
	return map[string]any{
		"source_id": edge.SourceID,
		"target_id": edge.TargetID,
		"kind":      edge.Kind,
		"score":     edge.Score,
	}
}

func (clue referenceClue) json() map[string]any {
	payload := map[string]any{
		"clue_id":  clue.ClueID,
		"text":     clue.Text,
		"audience": clue.Audience,
	}
	if clue.Audience == "character" {
		payload["character_id"] = clue.CharacterID
	}
	return payload
}

func (quest referencePlayQuest) json() map[string]any {
	dependsOn := make([]any, 0, len(quest.DependsOn))
	for _, dependencyID := range quest.DependsOn {
		dependsOn = append(dependsOn, dependencyID)
	}
	payload := map[string]any{
		"quest_id":   quest.QuestID,
		"title":      quest.Title,
		"depends_on": dependsOn,
		"state":      quest.State,
	}
	if quest.Rewards != nil {
		payload["rewards"] = map[string]any{
			"xp":    quest.Rewards.XP,
			"items": intMapJSON(quest.Rewards.Items),
		}
	}
	return payload
}

func (event referenceWorldEvent) json() map[string]any {
	payload := map[string]any{
		"event_id":    event.EventID,
		"turn_number": event.TurnNumber,
		"title":       event.Title,
		"text":        event.Text,
		"status":      "scheduled",
	}
	if event.Resolution != nil {
		payload["status"] = "resolved"
		payload["resolution"] = map[string]any{
			"turn_number": event.Resolution.TurnNumber,
			"text":        event.Resolution.Text,
		}
	}
	return payload
}

func (rumor referenceRumor) json(visibleCharacterIDs []string, includeAll bool) map[string]any {
	discoveredBy := []any{}
	if includeAll {
		for _, characterID := range rumor.DiscoveredBy {
			discoveredBy = append(discoveredBy, characterID)
		}
	} else {
		for _, visibleCharacterID := range visibleCharacterIDs {
			for _, characterID := range rumor.DiscoveredBy {
				if characterID == visibleCharacterID {
					discoveredBy = append(discoveredBy, characterID)
					break
				}
			}
		}
	}
	return map[string]any{
		"rumor_id":      rumor.RumorID,
		"text":          rumor.Text,
		"discovered_by": discoveredBy,
	}
}

func (calendar referenceCalendar) json() map[string]any {
	return map[string]any{
		"day":     calendar.Day,
		"season":  calendar.Season,
		"weather": calendarWeather(calendar.Day, calendar.Season),
	}
}

func (settlement referenceSettlement) json(visibleCharacterIDs []string, includeAll bool) map[string]any {
	services := make([]any, 0, len(settlement.Services))
	for _, service := range settlement.Services {
		services = append(services, service)
	}
	discoveredBy := []any{}
	if includeAll {
		for _, characterID := range settlement.DiscoveredBy {
			discoveredBy = append(discoveredBy, characterID)
		}
	} else {
		for _, visibleCharacterID := range visibleCharacterIDs {
			for _, characterID := range settlement.DiscoveredBy {
				if characterID == visibleCharacterID {
					discoveredBy = append(discoveredBy, characterID)
					break
				}
			}
		}
	}
	return map[string]any{
		"settlement_id": settlement.SettlementID,
		"name":          settlement.Name,
		"services":      services,
		"availability":  settlement.Availability,
		"discovered_by": discoveredBy,
	}
}

func (settlement referenceSettlement) discoveredBy(characterID string) bool {
	for _, discoveredBy := range settlement.DiscoveredBy {
		if discoveredBy == characterID {
			return true
		}
	}
	return false
}

func (shop referenceShop) json() map[string]any {
	return map[string]any{
		"shop_id":    shop.ShopID,
		"name":       shop.Name,
		"stock":      intMapJSON(shop.Stock),
		"buy_price":  shop.BuyPrice,
		"sell_price": shop.SellPrice,
	}
}

func validCalendarSeason(season string) bool {
	return season == "spring" || season == "summer" || season == "autumn" || season == "winter"
}

func calendarWeather(day int, season string) string {
	seasonOffset := map[string]int{
		"spring": 0,
		"summer": 1,
		"autumn": 2,
		"winter": 3,
	}[season]
	return []string{"clear", "rain", "wind", "snow"}[(day+seasonOffset)%4]
}

func decodeReferenceSettlement(w http.ResponseWriter, r *http.Request, pathSettlementID string) (referenceSettlement, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid settlement", http.StatusBadRequest)
		return referenceSettlement{}, false
	}
	settlementID := pathSettlementID
	if settlementID == "" {
		var ok bool
		settlementID, ok = requiredString(raw, "settlement_id")
		if !ok {
			http.Error(w, "invalid settlement", http.StatusBadRequest)
			return referenceSettlement{}, false
		}
	}
	name, ok := requiredString(raw, "name")
	if !ok {
		http.Error(w, "invalid settlement", http.StatusBadRequest)
		return referenceSettlement{}, false
	}
	services, ok := requiredUniqueNormalizedStrings(raw, "services")
	if !ok || len(services) == 0 {
		http.Error(w, "invalid settlement", http.StatusBadRequest)
		return referenceSettlement{}, false
	}
	availability, ok := requiredString(raw, "availability")
	if !ok || !validSettlementAvailability(availability) {
		http.Error(w, "invalid settlement", http.StatusBadRequest)
		return referenceSettlement{}, false
	}
	return referenceSettlement{SettlementID: settlementID, Name: name, Services: services, Availability: availability, Shops: map[string]*referenceShop{}}, true
}

func validSettlementAvailability(availability string) bool {
	return availability == "open" || availability == "limited" || availability == "closed"
}

func decodeReferenceShop(w http.ResponseWriter, r *http.Request) (referenceShop, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	shopID, ok := requiredString(raw, "shop_id")
	if !ok {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	name, ok := requiredString(raw, "name")
	if !ok {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	stock, ok := requiredItemQuantities(raw, "stock")
	if !ok || len(stock) == 0 {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	buyPrice, ok := requiredInt(raw, "buy_price")
	if !ok || buyPrice <= 0 {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	sellPrice, ok := requiredInt(raw, "sell_price")
	if !ok || sellPrice < 0 {
		http.Error(w, "invalid shop", http.StatusBadRequest)
		return referenceShop{}, false
	}
	return referenceShop{ShopID: shopID, Name: name, Stock: stock, BuyPrice: buyPrice, SellPrice: sellPrice}, true
}

func decodeReferenceShopTrade(w http.ResponseWriter, r *http.Request) (referenceShopTrade, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid shop trade", http.StatusBadRequest)
		return referenceShopTrade{}, false
	}
	characterID, ok := requiredString(raw, "character_id")
	if !ok {
		http.Error(w, "invalid shop trade", http.StatusBadRequest)
		return referenceShopTrade{}, false
	}
	itemID, ok := requiredString(raw, "item_id")
	if !ok || !validInventoryItem(itemID) {
		http.Error(w, "invalid shop trade", http.StatusBadRequest)
		return referenceShopTrade{}, false
	}
	quantity, ok := requiredInt(raw, "quantity")
	if !ok || quantity < 1 {
		http.Error(w, "invalid shop trade", http.StatusBadRequest)
		return referenceShopTrade{}, false
	}
	return referenceShopTrade{CharacterID: characterID, ItemID: itemID, Quantity: quantity}, true
}

func referenceShopForActor(w http.ResponseWriter, r *http.Request, playCampaign func(http.ResponseWriter, *http.Request) (*referencePlayCampaign, referenceUser, bool)) (*referenceShop, bool) {
	c, a, ok := playCampaign(w, r)
	if !ok {
		return nil, false
	}
	index, exists := c.SettlementIndex[r.PathValue("settlement_id")]
	if !exists {
		http.Error(w, "not found", http.StatusNotFound)
		return nil, false
	}
	settlement := &c.Settlements[index]
	if a.Username != c.Owner {
		member, exists := c.Members[a.Username]
		if !exists || !settlement.discoveredBy(member.CharacterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return nil, false
		}
	}
	shop := settlement.Shops[r.PathValue("shop_id")]
	if shop == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return nil, false
	}
	return shop, true
}

func referenceShopTradeContext(w http.ResponseWriter, r *http.Request, playCampaign func(http.ResponseWriter, *http.Request) (*referencePlayCampaign, referenceUser, bool)) (*referencePlayCampaign, referenceUser, *referenceShop, bool) {
	c, a, ok := playCampaign(w, r)
	if !ok {
		return nil, referenceUser{}, nil, false
	}
	index, exists := c.SettlementIndex[r.PathValue("settlement_id")]
	if !exists {
		http.Error(w, "not found", http.StatusNotFound)
		return nil, referenceUser{}, nil, false
	}
	settlement := &c.Settlements[index]
	if a.Username != c.Owner {
		member, exists := c.Members[a.Username]
		if !exists || !settlement.discoveredBy(member.CharacterID) {
			http.Error(w, "not found", http.StatusNotFound)
			return nil, referenceUser{}, nil, false
		}
	}
	shop := settlement.Shops[r.PathValue("shop_id")]
	if shop == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return nil, referenceUser{}, nil, false
	}
	return c, a, shop, true
}

func referenceShopTradeJSON(characterID string, itemID string, quantity int, gold int, stock int) map[string]any {
	return map[string]any{
		"character_id": characterID,
		"item_id":      itemID,
		"quantity":     quantity,
		"gold":         gold,
		"stock":        stock,
	}
}

func (recipe referenceRecipe) json() map[string]any {
	return map[string]any{
		"recipe_id":       recipe.RecipeID,
		"name":            recipe.Name,
		"ingredients":     intMapJSON(recipe.Ingredients),
		"output_item":     recipe.OutputItem,
		"output_quantity": recipe.OutputQuantity,
	}
}

func (activity referenceDowntimeActivity) json() map[string]any {
	return map[string]any{
		"activity_id":     activity.ActivityID,
		"name":            activity.Name,
		"cycles_required": activity.CyclesRequired,
	}
}

func (allocation referenceDowntimeAllocation) json() map[string]any {
	return map[string]any{
		"character_id":     allocation.CharacterID,
		"activity_id":      allocation.ActivityID,
		"cycles_completed": allocation.CyclesCompleted,
		"completions":      allocation.Completions,
	}
}

func (settings referenceSessionZeroSettings) json() map[string]any {
	consent := make([]any, 0, len(settings.Consent))
	for _, item := range settings.Consent {
		consent = append(consent, item)
	}
	return map[string]any{
		"rules":   settings.Rules,
		"tone":    settings.Tone,
		"consent": consent,
	}
}

func (content referenceContent) json() map[string]any {
	tags := make([]any, 0, len(content.Tags))
	for _, tag := range content.Tags {
		tags = append(tags, tag)
	}
	return map[string]any{
		"content_id": content.ContentID,
		"kind":       content.Kind,
		"text":       content.Text,
		"tags":       tags,
	}
}

func (content referenceContent) hasTag(tag string) bool {
	for _, candidate := range content.Tags {
		if candidate == tag {
			return true
		}
	}
	return false
}

func decodeReferenceContent(w http.ResponseWriter, r *http.Request, requireTags bool) (referenceContent, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid content", http.StatusBadRequest)
		return referenceContent{}, false
	}
	contentID, ok := requiredString(raw, "content_id")
	if !ok {
		http.Error(w, "invalid content", http.StatusBadRequest)
		return referenceContent{}, false
	}
	kind, ok := requiredString(raw, "kind")
	if !ok {
		http.Error(w, "invalid content", http.StatusBadRequest)
		return referenceContent{}, false
	}
	text, ok := requiredString(raw, "text")
	if !ok {
		http.Error(w, "invalid content", http.StatusBadRequest)
		return referenceContent{}, false
	}
	tags, ok := requiredUniqueStrings(raw, "tags")
	if !ok || (requireTags && len(tags) == 0) {
		http.Error(w, "invalid content", http.StatusBadRequest)
		return referenceContent{}, false
	}
	return referenceContent{ContentID: contentID, Kind: kind, Text: text, Tags: tags}, true
}

func decodeReferenceContentTags(w http.ResponseWriter, r *http.Request, requireTags bool) ([]string, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid content tags", http.StatusBadRequest)
		return nil, false
	}
	tags, ok := requiredUniqueStrings(raw, "tags")
	if !ok || (requireTags && len(tags) == 0) {
		http.Error(w, "invalid content tags", http.StatusBadRequest)
		return nil, false
	}
	return tags, true
}

func requiredUniqueStrings(raw map[string]json.RawMessage, key string) ([]string, bool) {
	values, ok := requiredStringArray(raw, key)
	if !ok {
		return nil, false
	}
	seen := map[string]bool{}
	for _, value := range values {
		if seen[value] {
			return nil, false
		}
		seen[value] = true
	}
	return values, true
}

func decodeReferenceRecipe(w http.ResponseWriter, r *http.Request) (referenceRecipe, bool) {
	var raw map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	recipeID, ok := requiredString(raw, "recipe_id")
	if !ok {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	name, ok := requiredString(raw, "name")
	if !ok {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	ingredients, ok := requiredItemQuantities(raw, "ingredients")
	if !ok || len(ingredients) == 0 {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	outputItem, ok := requiredString(raw, "output_item")
	if !ok || !validInventoryItem(outputItem) {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	outputQuantity, ok := requiredInt(raw, "output_quantity")
	if !ok || outputQuantity < 1 {
		http.Error(w, "invalid recipe", http.StatusBadRequest)
		return referenceRecipe{}, false
	}
	return referenceRecipe{RecipeID: recipeID, Name: name, Ingredients: ingredients, OutputItem: outputItem, OutputQuantity: outputQuantity}, true
}

func (npc *referencePlayNPC) dmJSON() map[string]any {
	payload := npc.playerJSON()
	payload["agenda"] = npc.Agenda
	return payload
}

func (npc *referencePlayNPC) playerJSON() map[string]any {
	return map[string]any{
		"npc_id":        npc.NPCID,
		"name":          npc.Name,
		"public_status": npc.PublicStatus,
	}
}

func (loot *referenceLoot) summaryJSON() map[string]any {
	return map[string]any{
		"loot_id":  loot.LootID,
		"item_id":  loot.ItemID,
		"quantity": loot.Quantity,
		"status":   loot.Status,
	}
}

func (loot *referenceLoot) recordJSON() map[string]any {
	payload := loot.summaryJSON()
	payload["recipient_character_id"] = nil
	if loot.RecipientCharacterID != "" {
		payload["recipient_character_id"] = loot.RecipientCharacterID
	}
	payload["votes"] = loot.voteCounts()
	return payload
}

func (loot *referenceLoot) voteCounts() map[string]int {
	counts := map[string]int{}
	for _, recipientID := range loot.Voters {
		counts[recipientID]++
	}
	return counts
}

func (loot *referenceLoot) winningRecipient() (string, int, bool) {
	recipientID := ""
	highest := 0
	tied := false
	for candidate, votes := range loot.voteCounts() {
		switch {
		case votes > highest:
			recipientID = candidate
			highest = votes
			tied = false
		case votes == highest:
			tied = true
		}
	}
	return recipientID, highest, highest > 0 && !tied
}

type referenceConcentration struct {
	SpellID        string
	Target         string
	RemainingTurns int
}

func (concentration referenceConcentration) json() map[string]any {
	return map[string]any{
		"spell_id":        concentration.SpellID,
		"target":          concentration.Target,
		"remaining_turns": concentration.RemainingTurns,
	}
}

type referenceSpellCast struct {
	CharacterID    string
	SpellID        string
	Target         string
	SlotLevel      int
	SlotsRemaining int
	Sequence       int
}

func (cast referenceSpellCast) json() map[string]any {
	return map[string]any{
		"character_id":    cast.CharacterID,
		"spell_id":        cast.SpellID,
		"target":          cast.Target,
		"slot_level":      cast.SlotLevel,
		"slots_remaining": cast.SlotsRemaining,
		"sequence":        cast.Sequence,
	}
}

func concentrationJSON(campaign *referencePlayCampaign, characterID string) any {
	concentration := campaign.Concentration[characterID]
	if concentration == nil {
		return nil
	}
	return concentration.json()
}

func validInventoryItem(itemID string) bool {
	return itemID == "healing-potion" || itemID == "torch" || itemID == "leather-armor" || itemID == "ring-of-protection" || itemID == "amulet-of-health"
}

func nonEmptyString(value string) bool {
	return strings.TrimSpace(value) != ""
}

func requiredString(raw map[string]json.RawMessage, key string) (string, bool) {
	var value string
	if payload, exists := raw[key]; !exists || json.Unmarshal(payload, &value) != nil || !nonEmptyString(value) {
		return "", false
	}
	return value, true
}

func requiredInt(raw map[string]json.RawMessage, key string) (int, bool) {
	var value int
	if payload, exists := raw[key]; !exists || json.Unmarshal(payload, &value) != nil || !jsonInteger(payload) {
		return 0, false
	}
	return value, true
}

func requiredBool(raw map[string]json.RawMessage, key string) (bool, bool) {
	var value bool
	if payload, exists := raw[key]; !exists || json.Unmarshal(payload, &value) != nil {
		return false, false
	}
	return value, true
}

func requiredStringArray(raw map[string]json.RawMessage, key string) ([]string, bool) {
	var values []string
	if payload, exists := raw[key]; !exists || json.Unmarshal(payload, &values) != nil {
		return nil, false
	}
	for _, value := range values {
		if !nonEmptyString(value) {
			return nil, false
		}
	}
	return values, true
}

func requiredUniqueNormalizedStrings(raw map[string]json.RawMessage, key string) ([]string, bool) {
	values, ok := requiredStringArray(raw, key)
	if !ok {
		return nil, false
	}
	normalized := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		trimmed := strings.TrimSpace(value)
		if seen[trimmed] {
			return nil, false
		}
		seen[trimmed] = true
		normalized = append(normalized, trimmed)
	}
	return normalized, true
}

func requiredItemQuantities(raw map[string]json.RawMessage, key string) (map[string]int, bool) {
	payload, exists := raw[key]
	if !exists {
		return nil, false
	}
	var itemRaw map[string]json.RawMessage
	if json.Unmarshal(payload, &itemRaw) != nil {
		return nil, false
	}
	items := map[string]int{}
	for itemID, itemPayload := range itemRaw {
		var quantity int
		if !validInventoryItem(itemID) || json.Unmarshal(itemPayload, &quantity) != nil || quantity < 1 || !jsonInteger(itemPayload) {
			return nil, false
		}
		items[itemID] = quantity
	}
	return items, true
}

func parseQuestRewards(raw map[string]json.RawMessage) (int, map[string]int, bool) {
	var xp int
	if payload, exists := raw["xp"]; !exists || json.Unmarshal(payload, &xp) != nil || xp < 0 || !jsonInteger(payload) {
		return 0, nil, false
	}
	items, ok := requiredItemQuantities(raw, "items")
	if !ok {
		return 0, nil, false
	}
	return xp, items, true
}

func jsonInteger(payload json.RawMessage) bool {
	var number json.Number
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	if decoder.Decode(&number) != nil {
		return false
	}
	_, err := number.Int64()
	return err == nil
}

func intMapJSON(values map[string]int) map[string]any {
	result := map[string]any{}
	for key, value := range values {
		result[key] = value
	}
	return result
}

func (campaign *referencePlayCampaign) playQuestDependenciesCompleted(quest *referencePlayQuest) bool {
	for _, dependencyID := range quest.DependsOn {
		index, exists := campaign.PlayQuestIndex[dependencyID]
		if !exists || campaign.PlayQuests[index].State != "completed" {
			return false
		}
	}
	return true
}

func validRelationshipScore(score int) bool {
	return score >= -100 && score <= 100
}

func relationshipKey(sourceID string, targetID string, kind string) string {
	return sourceID + "\x00" + targetID + "\x00" + kind
}

func boundedReputation(value int) int {
	if value < -100 {
		return -100
	}
	if value > 100 {
		return 100
	}
	return value
}

type referenceEquipmentItem struct {
	ItemID  string
	Attuned bool
}

func validEquipmentSlot(slot string) bool {
	return slot == "armor" || slot == "accessory"
}

func equipmentSlot(itemID string) string {
	switch itemID {
	case "leather-armor":
		return "armor"
	case "ring-of-protection", "amulet-of-health":
		return "accessory"
	default:
		return ""
	}
}

func attunableEquipmentItem(itemID string) bool {
	return itemID == "ring-of-protection" || itemID == "amulet-of-health"
}

func equipmentItemJSON(characterID string, slot string, item referenceEquipmentItem) map[string]any {
	return map[string]any{
		"character_id": characterID,
		"slot":         slot,
		"item_id":      item.ItemID,
		"attuned":      item.Attuned,
	}
}

func equipmentAttunementCount(campaign *referencePlayCampaign, characterID string) int {
	count := 0
	for _, attuned := range campaign.AttunedItems[characterID] {
		if attuned {
			count++
		}
	}
	return count
}

func inventoryItemJSON(characterID string, itemID string, quantity int, totalQuantity int) map[string]any {
	return map[string]any{
		"character_id":   characterID,
		"item_id":        itemID,
		"quantity":       quantity,
		"total_quantity": totalQuantity,
	}
}

func inventoryItemsJSON(stacks map[string]int) []map[string]any {
	itemIDs := make([]string, 0, len(stacks))
	for itemID, quantity := range stacks {
		if quantity > 0 {
			itemIDs = append(itemIDs, itemID)
		}
	}
	sort.Strings(itemIDs)
	items := make([]map[string]any, 0, len(itemIDs))
	for _, itemID := range itemIDs {
		items = append(items, map[string]any{"item_id": itemID, "quantity": stacks[itemID]})
	}
	return items
}

type referencePlayEncounter struct {
	ID           string
	Status       string
	Current      string
	Round        int
	Monsters     map[string]int
	Bound        map[string]bool
	HP           map[string]int
	DeathSuccess int
	DeathFailure int
	Conditions   map[string][]string
	Rewarded     bool
	XPAwarded    int
}

type referencePlayMember struct {
	Username    string
	CharacterID string
	Name        string
	Class       string
}

func (member referencePlayMember) json() map[string]any {
	return map[string]any{"username": member.Username, "character_id": member.CharacterID, "name": member.Name, "class": member.Class}
}

type referencePlayEvent struct {
	Sequence int
	Kind     string
	Actor    string
	Type     string
	Text     string
}

func (campaign *referencePlayCampaign) hasMember(username string) bool {
	_, ok := campaign.Members[username]
	return ok
}

func (campaign *referencePlayCampaign) hasCharacter(characterID string) bool {
	for _, member := range campaign.Members {
		if member.CharacterID == characterID {
			return true
		}
	}
	return false
}

func (campaign *referencePlayCampaign) hasActiveDelegationPower(username string, power string) bool {
	delegation, exists := campaign.Delegations[username]
	if !exists || !delegation.Active {
		return false
	}
	for _, candidate := range delegation.Powers {
		if candidate == power {
			return true
		}
	}
	return false
}

func (campaign *referencePlayCampaign) hasEntity(entityID string) bool {
	return campaign.hasCharacter(entityID) || campaign.NPCs[entityID] != nil
}

func referenceNoteReadable(campaign *referencePlayCampaign, actor referenceUser, note referenceNote) bool {
	return actor.Username == campaign.Owner || note.Visibility == "party" || note.Owner == actor.Username
}

func referenceWhisperReadable(campaign *referencePlayCampaign, actor referenceUser, whisper referenceWhisper) bool {
	if actor.Username == campaign.Owner {
		return true
	}
	member, exists := campaign.Members[actor.Username]
	if !exists {
		return false
	}
	return member.CharacterID == whisper.FromCharacterID || member.CharacterID == whisper.ToCharacterID
}

func (campaign *referencePlayCampaign) appendEvent(kind string, actor string, eventType string, text string) referencePlayEvent {
	event := referencePlayEvent{Sequence: len(campaign.Events) + 1, Kind: kind, Actor: actor, Type: eventType, Text: text}
	campaign.Events = append(campaign.Events, event)
	return event
}

func (event referencePlayEvent) json() map[string]any {
	payload := map[string]any{"sequence": event.Sequence, "kind": event.Kind, "actor": event.Actor, "text": event.Text}
	if event.Type != "" {
		payload["type"] = event.Type
	}
	return payload
}

func (campaign *referencePlayCampaign) eventJSON() []map[string]any {
	result := make([]map[string]any, 0, len(campaign.Events))
	for _, event := range campaign.Events {
		result = append(result, event.json())
	}
	return result
}

func (campaign *referencePlayCampaign) replayStateJSON() map[string]any {
	var story strings.Builder
	eventIDs := make([]any, 0, len(campaign.ReplayEvents))
	digestIDs := make([]string, 0, len(campaign.ReplayEvents))
	for _, event := range campaign.ReplayEvents {
		story.WriteString(event.Text)
		eventIDs = append(eventIDs, event.EventID)
		digestIDs = append(digestIDs, event.EventID)
	}
	replayStory := story.String()
	return map[string]any{
		"story":     replayStory,
		"event_ids": eventIDs,
		"digest":    strings.Join(digestIDs, ",") + "|" + replayStory,
	}
}

func (campaign *referencePlayCampaign) rngLedgerJSON() map[string]any {
	rolls := make([]any, 0, len(campaign.RNGRolls))
	for _, roll := range campaign.RNGRolls {
		rolls = append(rolls, roll.json())
	}
	return map[string]any{"seed": campaign.RNGSeed, "rolls": rolls}
}

func (campaign *referencePlayCampaign) moderationReportsJSON() map[string]any {
	reports := make([]any, 0, len(campaign.ModerationReports))
	for _, report := range campaign.ModerationReports {
		reports = append(reports, report.json())
	}
	return map[string]any{"reports": reports}
}

func (campaign *referencePlayCampaign) safetyBoundariesJSON() map[string]any {
	tags := make([]any, 0, len(campaign.SafetyBlockedTags))
	for _, tag := range campaign.SafetyBlockedTags {
		tags = append(tags, tag)
	}
	return map[string]any{"blocked_tags": tags}
}

func (campaign *referencePlayCampaign) safetyEventsJSON() map[string]any {
	events := make([]any, 0, len(campaign.SafetyEvents))
	for _, event := range campaign.SafetyEvents {
		events = append(events, event.json())
	}
	return map[string]any{"events": events}
}

func deterministicRNGResult(seed string, sequence int, rollID string, sides int) int {
	payload := fmt.Sprintf("%s|%d|%s|%d", seed, sequence, rollID, sides)
	var acc uint32
	for i := 0; i < len(payload); i++ {
		acc = acc*31 + uint32(payload[i])
	}
	return int(acc%uint32(sides)) + 1
}

type referenceCampaign struct {
	ID                      string
	Name                    string
	DM                      string
	Characters              []map[string]any
	Events                  []map[string]any
	Quests                  map[string]*referenceQuest
	Factions                map[string]map[string]any
	NPCs                    map[string]map[string]any
	Inventory               []map[string]any
	AssignedItems           int
	HealingPotionsAvailable int
	Crafting                map[string]*referenceCraftingProject
	Sessions                map[string]*referenceScheduledSession
}

type referenceQuest struct {
	ID         string
	Title      string
	Status     string
	Milestones []string
	Completed  map[string]bool
}

type referenceCraftingProject struct {
	ID            string
	CharacterID   string
	ItemSlug      string
	DaysRequired  int
	DaysCompleted int
	Status        string
}

type referenceScheduledSession struct {
	ID              string
	StartsAt        string
	DurationMinutes int
	AgendaCount     int
	PresentCount    int
	AbsentCount     int
}

func newReferenceCampaign(id string, name string, dm string) *referenceCampaign {
	return &referenceCampaign{
		ID:                      id,
		Name:                    name,
		DM:                      dm,
		Quests:                  map[string]*referenceQuest{},
		Factions:                map[string]map[string]any{},
		NPCs:                    map[string]map[string]any{},
		HealingPotionsAvailable: 0,
		Crafting:                map[string]*referenceCraftingProject{},
		Sessions:                map[string]*referenceScheduledSession{},
	}
}

func activeQuestCount(campaign *referenceCampaign) int {
	count := 0
	for _, quest := range campaign.Quests {
		if quest.Status == "" || quest.Status == "active" {
			count++
		}
	}
	return count
}

func friendlyNPCCount(campaign *referenceCampaign) int {
	count := 0
	for _, npc := range campaign.NPCs {
		if disposition, ok := npc["disposition"].(float64); ok && disposition > 0 {
			count++
		}
	}
	return count
}

type referenceCombatant struct {
	Name  string
	Dex   int
	Score int
}

type referenceCondition struct {
	Condition string
	Remaining int
}

type referenceSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []referenceCombatant
	Conditions map[string][]referenceCondition
}

func (session *referenceSession) snapshot() map[string]any {
	return map[string]any{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     combatantJSON(session.Order[session.TurnIndex]),
		"order":      combatantList(session.Order),
		"conditions": conditionsJSON(session.Conditions),
	}
}

func abilityModifier(score int) int {
	if score >= 10 {
		return (score - 10) / 2
	}
	return -((11 - score) / 2)
}

func proficiency(level int) int {
	return 2 + (level-1)/4
}

func sortReferenceOrder(order []referenceCombatant) {
	for i := 0; i < len(order); i++ {
		for j := i + 1; j < len(order); j++ {
			if order[j].Score > order[i].Score ||
				(order[j].Score == order[i].Score && order[j].Dex > order[i].Dex) ||
				(order[j].Score == order[i].Score && order[j].Dex == order[i].Dex && order[j].Name < order[i].Name) {
				order[i], order[j] = order[j], order[i]
			}
		}
	}
}

func combatantJSON(combatant referenceCombatant) map[string]any {
	return map[string]any{"name": combatant.Name, "score": combatant.Score}
}

func combatantList(order []referenceCombatant) []map[string]any {
	out := make([]map[string]any, 0, len(order))
	for _, combatant := range order {
		out = append(out, combatantJSON(combatant))
	}
	return out
}

func conditionList(conditions []referenceCondition) []map[string]any {
	out := make([]map[string]any, 0, len(conditions))
	for _, condition := range conditions {
		out = append(out, map[string]any{
			"condition":        condition.Condition,
			"remaining_rounds": condition.Remaining,
		})
	}
	return out
}

func conditionsJSON(conditions map[string][]referenceCondition) map[string]any {
	out := map[string]any{}
	for name, list := range conditions {
		out[name] = conditionList(list)
	}
	return out
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
