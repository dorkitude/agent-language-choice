package eval

import (
	"encoding/json"
	"net/http"
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
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
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
		campaign := &referencePlayCampaign{ID: req.ID, Name: req.Name, Owner: actor.Username, MaxPlayers: req.MaxPlayers, Status: "lobby", Members: map[string]referencePlayMember{}}
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
	mux.HandleFunc("POST /v1/play/campaigns/{id}/narrations", func(w http.ResponseWriter, r *http.Request) {
		campaign, actor, ok := playCampaign(w, r)
		if !ok {
			return
		}
		if actor.Username != campaign.Owner {
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
		campaign.CurrentActor, campaign.Phase, campaign.TurnNumber = campaign.Order[1], "player", 2
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
	return mux
}

type referenceUser struct {
	Username string
	Password string
	Role     string
}

type referencePlayCampaign struct {
	ID           string
	Name         string
	Owner        string
	MaxPlayers   int
	Status       string
	Members      map[string]referencePlayMember
	Order        []string
	Queue        []string
	CurrentActor string
	Phase        string
	TurnNumber   int
	NudgeCount   int
	Events       []referencePlayEvent
	Story        string
	DMNotes      string
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
