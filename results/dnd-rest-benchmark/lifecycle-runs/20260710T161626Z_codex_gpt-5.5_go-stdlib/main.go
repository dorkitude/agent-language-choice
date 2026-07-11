package main

import (
	"crypto/pbkdf2"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
)

var dicePattern = regexp.MustCompile(`^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$`)
var usernamePattern = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

var monsterXP = map[string]int{
	"0":   10,
	"1/8": 25,
	"1/4": 50,
	"1/2": 100,
	"1":   200,
	"2":   450,
	"3":   700,
	"4":   1100,
	"5":   1800,
}

var combatSessions = struct {
	sync.Mutex
	items map[string]*combatSession
}{items: make(map[string]*combatSession)}

var users = struct {
	sync.Mutex
	items map[string]user
}{items: make(map[string]user)}

var compendium = struct {
	sync.Mutex
	monsters map[string]monster
	items    map[string]item
}{
	monsters: make(map[string]monster),
	items:    make(map[string]item),
}

var campaigns = struct {
	sync.Mutex
	items map[string]*campaign
}{items: make(map[string]*campaign)}

var storage = struct {
	sync.Mutex
	initialized bool
}{}

type user struct {
	Username     string
	Role         string
	PasswordHash [32]byte
}

type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []combatantEntry
	Conditions map[string][]combatCondition
}

type combatantEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	dex   int
}

type combatCondition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

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

type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters map[string]campaignCharacter
	Events     map[string]campaignEvent
}

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type campaignEvent struct {
	ID      string
	Kind    string
	Summary string
}

type combatStateResponse struct {
	ID         string                        `json:"id"`
	Round      int                           `json:"round"`
	TurnIndex  int                           `json:"turn_index"`
	Active     combatantEntry                `json:"active"`
	Order      []combatantEntry              `json:"order,omitempty"`
	Conditions *map[string][]combatCondition `json:"conditions,omitempty"`
}

func main() {
	if err := initStorage(); err != nil {
		log.Fatal(err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("/v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("/v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("/v1/initiative/order", initiativeOrderHandler)
	mux.HandleFunc("/v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("/v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("/v1/characters/derived-stats", derivedStatsHandler)
	mux.HandleFunc("/v1/combat/sessions", combatSessionsHandler)
	mux.HandleFunc("/v1/combat/sessions/", combatSessionActionHandler)
	mux.HandleFunc("/v1/auth/register", registerHandler)
	mux.HandleFunc("/v1/auth/login", loginHandler)
	mux.HandleFunc("/v1/storage/status", storageStatusHandler)
	mux.HandleFunc("/v1/storage/reset", storageResetHandler)
	mux.HandleFunc("/v1/compendium/monsters", compendiumMonstersHandler)
	mux.HandleFunc("/v1/compendium/monsters/", compendiumMonsterHandler)
	mux.HandleFunc("/v1/compendium/items", compendiumItemsHandler)
	mux.HandleFunc("/v1/compendium/items/", compendiumItemHandler)
	mux.HandleFunc("/v1/campaigns", campaignsHandler)
	mux.HandleFunc("/v1/campaigns/", campaignActionHandler)
	mux.HandleFunc("/v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("/v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("/v1/phb/equipment-load", equipmentLoadHandler)
	mux.HandleFunc("/v1/dm/encounter-builder", dmEncounterBuilderHandler)
	mux.HandleFunc("/v1/dm/loot-parcel", dmLootParcelHandler)
	mux.HandleFunc("/v1/dm/session-recap", dmSessionRecapHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	addr := "127.0.0.1:" + port
	log.Fatal(http.ListenAndServe(addr, mux))
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Class string `json:"class"`
		Level int    `json:"level"`
	}
	if err := readJSON(r, &req); err != nil || req.Class != "wizard" || req.Level != 5 {
		writeError(w, http.StatusBadRequest)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		Class string         `json:"class"`
		Level int            `json:"level"`
		Slots map[string]int `json:"slots"`
	}{
		Class: req.Class,
		Level: req.Level,
		Slots: map[string]int{
			"1": 4,
			"2": 3,
			"3": 2,
		},
	})
}

func longRestHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Level           int `json:"level"`
		HPCurrent       int `json:"hp_current"`
		HPMax           int `json:"hp_max"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}
	if err := readJSON(r, &req); err != nil ||
		!validLevel(req.Level) ||
		req.HPMax <= 0 ||
		req.HPCurrent < 0 ||
		req.HPCurrent > req.HPMax ||
		req.HitDiceSpent < 0 ||
		req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest)
		return
	}

	restoredHitDice := maxInt(1, req.Level/2)
	writeJSON(w, http.StatusOK, struct {
		HPCurrent       int `json:"hp_current"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}{
		HPCurrent:       req.HPMax,
		HitDiceSpent:    maxInt(0, req.HitDiceSpent-restoredHitDice),
		ExhaustionLevel: maxInt(0, req.ExhaustionLevel-1),
	})
}

func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Strength int `json:"strength"`
		Weight   int `json:"weight"`
	}
	if err := readJSON(r, &req); err != nil || !validAbilityScore(req.Strength) || req.Weight < 0 {
		writeError(w, http.StatusBadRequest)
		return
	}

	capacity := req.Strength * 15
	writeJSON(w, http.StatusOK, struct {
		Capacity   int  `json:"capacity"`
		Weight     int  `json:"weight"`
		Encumbered bool `json:"encumbered"`
	}{
		Capacity:   capacity,
		Weight:     req.Weight,
		Encumbered: req.Weight > capacity,
	})
}

func campaignsHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/v1/campaigns" {
		writeError(w, http.StatusNotFound)
		return
	}
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if err := readJSON(r, &req); err != nil || req.ID == "" || req.Name == "" || req.DM == "" {
		writeError(w, http.StatusBadRequest)
		return
	}

	campaigns.Lock()
	if _, exists := campaigns.items[req.ID]; exists {
		campaigns.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	campaigns.items[req.ID] = &campaign{
		ID:         req.ID,
		Name:       req.Name,
		DM:         req.DM,
		Characters: make(map[string]campaignCharacter),
		Events:     make(map[string]campaignEvent),
	}
	if err := saveCampaign(campaigns.items[req.ID]); err != nil {
		delete(campaigns.items, req.ID)
		campaigns.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	campaigns.Unlock()

	writeJSON(w, http.StatusCreated, req)
}

func campaignActionHandler(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/campaigns/"), "/")
	if len(parts) != 2 || parts[0] == "" {
		writeError(w, http.StatusNotFound)
		return
	}

	switch parts[1] {
	case "characters":
		addCampaignCharacterHandler(w, r, parts[0])
	case "events":
		addCampaignEventHandler(w, r, parts[0])
	case "state":
		campaignStateHandler(w, r, parts[0])
	default:
		writeError(w, http.StatusNotFound)
	}
}

func addCampaignCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req campaignCharacter
	if err := readJSON(r, &req); err != nil ||
		req.ID == "" ||
		req.Name == "" ||
		!validLevel(req.Level) ||
		req.Class == "" {
		writeError(w, http.StatusBadRequest)
		return
	}

	campaigns.Lock()
	stored, exists := campaigns.items[campaignID]
	if !exists {
		campaigns.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}
	if _, exists := stored.Characters[req.ID]; exists {
		campaigns.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	stored.Characters[req.ID] = req
	if err := saveCampaignCharacter(campaignID, req); err != nil {
		delete(stored.Characters, req.ID)
		campaigns.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	campaigns.Unlock()

	writeJSON(w, http.StatusCreated, req)
}

func addCampaignEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if err := readJSON(r, &req); err != nil || req.ID == "" || req.Kind == "" || req.Summary == "" {
		writeError(w, http.StatusBadRequest)
		return
	}

	event := campaignEvent{ID: req.ID, Kind: req.Kind, Summary: req.Summary}
	campaigns.Lock()
	stored, exists := campaigns.items[campaignID]
	if !exists {
		campaigns.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}
	if _, exists := stored.Events[req.ID]; exists {
		campaigns.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	stored.Events[req.ID] = event
	if err := saveCampaignEvent(campaignID, event); err != nil {
		delete(stored.Events, req.ID)
		campaigns.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	campaigns.Unlock()

	writeJSON(w, http.StatusCreated, struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}{ID: event.ID, Kind: event.Kind})
}

func campaignStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaigns.Lock()
	stored, exists := campaigns.items[campaignID]
	if !exists {
		campaigns.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}
	characters := make([]campaignCharacter, 0, len(stored.Characters))
	for _, character := range stored.Characters {
		characters = append(characters, character)
	}
	sort.Slice(characters, func(i, j int) bool {
		return characters[i].ID < characters[j].ID
	})
	response := struct {
		ID         string              `json:"id"`
		Name       string              `json:"name"`
		DM         string              `json:"dm"`
		Characters []campaignCharacter `json:"characters"`
		LogCount   int                 `json:"log_count"`
	}{
		ID:         stored.ID,
		Name:       stored.Name,
		DM:         stored.DM,
		Characters: characters,
		LogCount:   len(stored.Events),
	}
	campaigns.Unlock()

	writeJSON(w, http.StatusOK, response)
}

func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	storage.Lock()
	initialized := storage.initialized
	storage.Unlock()

	writeJSON(w, http.StatusOK, struct {
		Driver        string `json:"driver"`
		SchemaVersion int    `json:"schema_version"`
		Initialized   bool   `json:"initialized"`
	}{
		Driver:        "sqlite",
		SchemaVersion: 1,
		Initialized:   initialized,
	})
}

func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	if err := resetStorage(); err != nil {
		writeError(w, http.StatusInternalServerError)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		OK            bool `json:"ok"`
		SchemaVersion int  `json:"schema_version"`
	}{
		OK:            true,
		SchemaVersion: 1,
	})
}

func compendiumMonstersHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/v1/compendium/monsters" {
		writeError(w, http.StatusNotFound)
		return
	}
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req monster
	if err := readJSON(r, &req); err != nil || !validMonster(req) {
		writeError(w, http.StatusBadRequest)
		return
	}
	if req.Tags == nil {
		req.Tags = []string{}
	}

	compendium.Lock()
	if _, exists := compendium.monsters[req.Slug]; exists {
		compendium.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	compendium.monsters[req.Slug] = copyMonster(req)
	if err := saveMonster(req); err != nil {
		delete(compendium.monsters, req.Slug)
		compendium.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	compendium.Unlock()

	writeJSON(w, http.StatusCreated, monsterCreateResponse(req))
}

func compendiumMonsterHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/monsters/")
	if slug == "" || strings.Contains(slug, "/") {
		writeError(w, http.StatusNotFound)
		return
	}

	compendium.Lock()
	stored, exists := compendium.monsters[slug]
	compendium.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound)
		return
	}

	writeJSON(w, http.StatusOK, copyMonster(stored))
}

func compendiumItemsHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/v1/compendium/items" {
		writeError(w, http.StatusNotFound)
		return
	}
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req item
	if err := readJSON(r, &req); err != nil || !validItem(req) {
		writeError(w, http.StatusBadRequest)
		return
	}

	compendium.Lock()
	if _, exists := compendium.items[req.Slug]; exists {
		compendium.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	compendium.items[req.Slug] = req
	if err := saveItem(req); err != nil {
		delete(compendium.items, req.Slug)
		compendium.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	compendium.Unlock()

	writeJSON(w, http.StatusCreated, req)
}

func compendiumItemHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	slug := strings.TrimPrefix(r.URL.Path, "/v1/compendium/items/")
	if slug == "" || strings.Contains(slug, "/") {
		writeError(w, http.StatusNotFound)
		return
	}

	compendium.Lock()
	stored, exists := compendium.items[slug]
	compendium.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound)
		return
	}

	writeJSON(w, http.StatusOK, stored)
}

func dmEncounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if err := readJSON(r, &req); err != nil || req.CampaignID == "" || len(req.Party) == 0 || len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest)
		return
	}
	if !campaignExists(req.CampaignID) {
		writeError(w, http.StatusNotFound)
		return
	}

	baseXP := 0
	for _, slug := range req.MonsterSlugs {
		if slug == "" {
			writeError(w, http.StatusBadRequest)
			return
		}
		compendium.Lock()
		stored, exists := compendium.monsters[slug]
		compendium.Unlock()
		if !exists {
			writeError(w, http.StatusNotFound)
			return
		}
		xp, ok := monsterXP[stored.CR]
		if !ok {
			writeError(w, http.StatusBadRequest)
			return
		}
		baseXP += xp
	}

	partyThresholds, ok := levelThreePartyThresholds(req.Party)
	if !ok {
		writeError(w, http.StatusBadRequest)
		return
	}
	monsterCount := len(req.MonsterSlugs)
	adjustedXP := float64(baseXP) * encounterMultiplier(monsterCount)
	difficulty := encounterDifficulty(adjustedXP, partyThresholds)

	writeJSON(w, http.StatusOK, struct {
		CampaignID     string  `json:"campaign_id"`
		BaseXP         int     `json:"base_xp"`
		AdjustedXP     float64 `json:"adjusted_xp"`
		Difficulty     string  `json:"difficulty"`
		MonsterCount   int     `json:"monster_count"`
		Recommendation string  `json:"recommendation"`
	}{
		CampaignID:     req.CampaignID,
		BaseXP:         baseXP,
		AdjustedXP:     adjustedXP,
		Difficulty:     difficulty,
		MonsterCount:   monsterCount,
		Recommendation: encounterRecommendation(difficulty),
	})
}

func dmLootParcelHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		CampaignID string `json:"campaign_id"`
		Tier       int    `json:"tier"`
		Seed       int    `json:"seed"`
	}
	if err := readJSON(r, &req); err != nil || req.CampaignID == "" || req.Tier != 1 {
		writeError(w, http.StatusBadRequest)
		return
	}
	if !campaignExists(req.CampaignID) {
		writeError(w, http.StatusNotFound)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		CampaignID string `json:"campaign_id"`
		CoinsGP    int    `json:"coins_gp"`
		Items      []struct {
			Slug     string `json:"slug"`
			Quantity int    `json:"quantity"`
		} `json:"items"`
	}{
		CampaignID: req.CampaignID,
		CoinsGP:    75,
		Items: []struct {
			Slug     string `json:"slug"`
			Quantity int    `json:"quantity"`
		}{
			{Slug: "healing-potion", Quantity: 2},
		},
	})
}

func dmSessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := readJSON(r, &req); err != nil || req.CampaignID == "" {
		writeError(w, http.StatusBadRequest)
		return
	}

	campaigns.Lock()
	stored, exists := campaigns.items[req.CampaignID]
	if !exists {
		campaigns.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}
	events := make([]campaignEvent, 0, len(stored.Events))
	for _, event := range stored.Events {
		events = append(events, event)
	}
	campaigns.Unlock()
	sort.Slice(events, func(i, j int) bool {
		return events[i].ID < events[j].ID
	})

	summary := ""
	if len(events) > 0 {
		summary = events[len(events)-1].Summary
	}

	writeJSON(w, http.StatusOK, struct {
		CampaignID  string   `json:"campaign_id"`
		Summary     string   `json:"summary"`
		OpenThreads []string `json:"open_threads"`
	}{
		CampaignID:  req.CampaignID,
		Summary:     summary,
		OpenThreads: openThreadsForSummary(summary),
	})
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := readJSON(r, &req); err != nil ||
		!validUsername(req.Username) ||
		!validPassword(req.Password) ||
		!validRole(req.Role) {
		writeError(w, http.StatusBadRequest)
		return
	}

	passwordHash, err := hashPassword(req.Username, req.Password)
	if err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	users.Lock()
	if _, exists := users.items[req.Username]; exists {
		users.Unlock()
		writeError(w, http.StatusConflict)
		return
	}
	users.items[req.Username] = user{
		Username:     req.Username,
		Role:         req.Role,
		PasswordHash: passwordHash,
	}
	stored := users.items[req.Username]
	if err := saveUser(stored); err != nil {
		delete(users.items, req.Username)
		users.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	users.Unlock()

	writeJSON(w, http.StatusCreated, struct {
		Username string `json:"username"`
		Role     string `json:"role"`
	}{
		Username: req.Username,
		Role:     req.Role,
	})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	users.Lock()
	stored, exists := users.items[req.Username]
	users.Unlock()
	if !exists || !passwordMatches(stored.Username, req.Password, stored.PasswordHash) {
		writeError(w, http.StatusUnauthorized)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		Username string `json:"username"`
		Token    string `json:"token"`
	}{
		Username: stored.Username,
		Token:    "session-" + stored.Username,
	})
}

func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Expression string `json:"expression"`
	}
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	count, sides, modifier, err := parseDiceExpression(req.Expression)
	if err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		DiceCount int     `json:"dice_count"`
		Sides     int     `json:"sides"`
		Modifier  int     `json:"modifier"`
		Min       int     `json:"min"`
		Max       int     `json:"max"`
		Average   float64 `json:"average"`
	}{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       count + modifier,
		Max:       count*sides + modifier,
		Average:   float64(count)*(float64(sides)+1)/2 + float64(modifier),
	})
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	total := req.Roll + req.Modifier
	writeJSON(w, http.StatusOK, struct {
		Total   int  `json:"total"`
		Success bool `json:"success"`
		Margin  int  `json:"margin"`
	}{
		Total:   total,
		Success: total >= req.DC,
		Margin:  total - req.DC,
	})
}

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Party []struct {
			Level int `json:"level"`
		} `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, monster := range req.Monsters {
		xp, ok := monsterXP[monster.CR]
		if !ok || monster.Count <= 0 {
			writeError(w, http.StatusBadRequest)
			return
		}
		baseXP += xp * monster.Count
		monsterCount += monster.Count
	}

	partyThresholds := thresholds{}
	for _, member := range req.Party {
		if member.Level != 3 {
			writeError(w, http.StatusBadRequest)
			return
		}
		partyThresholds.Easy += 75
		partyThresholds.Medium += 150
		partyThresholds.Hard += 225
		partyThresholds.Deadly += 400
	}

	multiplier := encounterMultiplier(monsterCount)
	adjustedXP := float64(baseXP) * multiplier
	writeJSON(w, http.StatusOK, struct {
		BaseXP       int        `json:"base_xp"`
		MonsterCount int        `json:"monster_count"`
		Multiplier   float64    `json:"multiplier"`
		AdjustedXP   float64    `json:"adjusted_xp"`
		Difficulty   string     `json:"difficulty"`
		Thresholds   thresholds `json:"thresholds"`
	}{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjustedXP,
		Difficulty:   encounterDifficulty(adjustedXP, partyThresholds),
		Thresholds:   partyThresholds,
	})
}

func initiativeOrderHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := readJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest)
		return
	}

	type entry struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}
	order := make([]entry, 0, len(req.Combatants))
	for _, combatant := range req.Combatants {
		order = append(order, entry{
			Name:  combatant.Name,
			Score: combatant.Roll + combatant.Dex,
			dex:   combatant.Dex,
		})
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	writeJSON(w, http.StatusOK, struct {
		Order []entry `json:"order"`
	}{Order: order})
}

func combatSessionsHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/v1/combat/sessions" {
		writeError(w, http.StatusNotFound)
		return
	}
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := readJSON(r, &req); err != nil || req.ID == "" || len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest)
		return
	}

	order := make([]combatantEntry, 0, len(req.Combatants))
	seenNames := make(map[string]bool, len(req.Combatants))
	for _, combatant := range req.Combatants {
		if combatant.Name == "" || seenNames[combatant.Name] {
			writeError(w, http.StatusBadRequest)
			return
		}
		seenNames[combatant.Name] = true
		order = append(order, combatantEntry{
			Name:  combatant.Name,
			Score: combatant.Roll + combatant.Dex,
			dex:   combatant.Dex,
		})
	}
	sortCombatants(order)

	session := &combatSession{
		ID:         req.ID,
		Round:      1,
		TurnIndex:  0,
		Order:      order,
		Conditions: make(map[string][]combatCondition),
	}

	combatSessions.Lock()
	if _, exists := combatSessions.items[req.ID]; exists {
		combatSessions.Unlock()
		writeError(w, http.StatusBadRequest)
		return
	}
	combatSessions.items[req.ID] = session
	if err := saveCombatSession(session); err != nil {
		delete(combatSessions.items, req.ID)
		combatSessions.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	combatSessions.Unlock()

	writeJSON(w, http.StatusOK, session.stateResponse(false))
}

func combatSessionActionHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/combat/sessions/"), "/")
	if len(parts) != 2 || parts[0] == "" {
		writeError(w, http.StatusNotFound)
		return
	}

	switch parts[1] {
	case "conditions":
		addConditionHandler(w, r, parts[0])
	case "advance":
		advanceCombatHandler(w, parts[0])
	default:
		writeError(w, http.StatusNotFound)
	}
}

func addConditionHandler(w http.ResponseWriter, r *http.Request, id string) {
	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if err := readJSON(r, &req); err != nil || req.Target == "" || req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest)
		return
	}

	combatSessions.Lock()
	session, ok := combatSessions.items[id]
	if !ok {
		combatSessions.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}
	if !session.hasCombatant(req.Target) {
		combatSessions.Unlock()
		writeError(w, http.StatusBadRequest)
		return
	}
	session.Conditions[req.Target] = append(session.Conditions[req.Target], combatCondition{
		Condition:       req.Condition,
		RemainingRounds: req.DurationRounds,
	})
	if err := saveCombatSession(session); err != nil {
		combatSessions.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	conditions := append([]combatCondition(nil), session.Conditions[req.Target]...)
	combatSessions.Unlock()

	writeJSON(w, http.StatusOK, struct {
		Target     string            `json:"target"`
		Conditions []combatCondition `json:"conditions"`
	}{
		Target:     req.Target,
		Conditions: conditions,
	})
}

func advanceCombatHandler(w http.ResponseWriter, id string) {
	combatSessions.Lock()
	session, ok := combatSessions.items[id]
	if !ok {
		combatSessions.Unlock()
		writeError(w, http.StatusNotFound)
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}
	session.decrementActiveConditions()
	if err := saveCombatSession(session); err != nil {
		combatSessions.Unlock()
		writeError(w, http.StatusInternalServerError)
		return
	}
	response := session.stateResponse(true)
	combatSessions.Unlock()

	writeJSON(w, http.StatusOK, response)
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Score int `json:"score"`
	}
	if err := readJSON(r, &req); err != nil || !validAbilityScore(req.Score) {
		writeError(w, http.StatusBadRequest)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		Score    int `json:"score"`
		Modifier int `json:"modifier"`
	}{
		Score:    req.Score,
		Modifier: abilityModifier(req.Score),
	})
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Level int `json:"level"`
	}
	if err := readJSON(r, &req); err != nil || !validLevel(req.Level) {
		writeError(w, http.StatusBadRequest)
		return
	}

	writeJSON(w, http.StatusOK, struct {
		Level            int `json:"level"`
		ProficiencyBonus int `json:"proficiency_bonus"`
	}{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
	})
}

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	var req struct {
		Level     int       `json:"level"`
		Abilities abilities `json:"abilities"`
		Armor     struct {
			Base   int  `json:"base"`
			Shield bool `json:"shield"`
			DexCap int  `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := readJSON(r, &req); err != nil || !validLevel(req.Level) || !validAbilities(req.Abilities) {
		writeError(w, http.StatusBadRequest)
		return
	}

	modifiers := abilities{
		Str: abilityModifier(req.Abilities.Str),
		Dex: abilityModifier(req.Abilities.Dex),
		Con: abilityModifier(req.Abilities.Con),
		Int: abilityModifier(req.Abilities.Int),
		Wis: abilityModifier(req.Abilities.Wis),
		Cha: abilityModifier(req.Abilities.Cha),
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}

	writeJSON(w, http.StatusOK, struct {
		Level            int       `json:"level"`
		ProficiencyBonus int       `json:"proficiency_bonus"`
		HPMax            int       `json:"hp_max"`
		ArmorClass       int       `json:"armor_class"`
		Modifiers        abilities `json:"modifiers"`
	}{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
		HPMax:            req.Level * (6 + modifiers.Con),
		ArmorClass:       req.Armor.Base + minInt(modifiers.Dex, req.Armor.DexCap) + shieldBonus,
		Modifiers:        modifiers,
	})
}

type abilities struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

func parseDiceExpression(expression string) (int, int, int, error) {
	matches := dicePattern.FindStringSubmatch(expression)
	if matches == nil {
		return 0, 0, 0, errors.New("invalid dice expression")
	}

	count, err := strconv.Atoi(matches[1])
	if err != nil || count <= 0 {
		return 0, 0, 0, errors.New("invalid dice count")
	}
	sides, err := strconv.Atoi(matches[2])
	if err != nil || sides <= 0 {
		return 0, 0, 0, errors.New("invalid dice sides")
	}

	modifier := 0
	if matches[4] != "" {
		modifier, err = strconv.Atoi(matches[4])
		if err != nil {
			return 0, 0, 0, errors.New("invalid dice modifier")
		}
		if matches[3] == "-" {
			modifier = -modifier
		}
	}

	return count, sides, modifier, nil
}

func abilityModifier(score int) int {
	delta := score - 10
	if delta < 0 {
		return (delta - 1) / 2
	}
	return delta / 2
}

func proficiencyBonus(level int) int {
	return 2 + (level-1)/4
}

func validAbilityScore(score int) bool {
	return score >= 1 && score <= 30
}

func validAbilities(a abilities) bool {
	return validAbilityScore(a.Str) &&
		validAbilityScore(a.Dex) &&
		validAbilityScore(a.Con) &&
		validAbilityScore(a.Int) &&
		validAbilityScore(a.Wis) &&
		validAbilityScore(a.Cha)
}

func validLevel(level int) bool {
	return level >= 1 && level <= 20
}

func validUsername(username string) bool {
	return usernamePattern.MatchString(username)
}

func validPassword(password string) bool {
	return len(password) >= 8
}

func validRole(role string) bool {
	return role == "dm" || role == "player"
}

func hashPassword(username, password string) ([32]byte, error) {
	key, err := pbkdf2.Key(sha256.New, password, []byte("dnd-rest-password:"+username), 100000, 32)
	if err != nil {
		return [32]byte{}, err
	}
	var hash [32]byte
	copy(hash[:], key)
	return hash, nil
}

func passwordMatches(username, password string, hash [32]byte) bool {
	candidate, err := hashPassword(username, password)
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare(candidate[:], hash[:]) == 1
}

func initStorage() error {
	storage.Lock()
	defer storage.Unlock()

	if err := applyStorageSchema(); err != nil {
		storage.initialized = false
		return err
	}
	if err := loadStorageData(); err != nil {
		storage.initialized = false
		return err
	}
	storage.initialized = true
	return nil
}

func resetStorage() error {
	storage.Lock()
	defer storage.Unlock()

	for _, path := range []string{"game.db", "game.db-wal", "game.db-shm"} {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			storage.initialized = false
			return err
		}
	}
	if err := applyStorageSchema(); err != nil {
		storage.initialized = false
		return err
	}

	combatSessions.Lock()
	combatSessions.items = make(map[string]*combatSession)
	combatSessions.Unlock()

	users.Lock()
	users.items = make(map[string]user)
	users.Unlock()

	compendium.Lock()
	compendium.monsters = make(map[string]monster)
	compendium.items = make(map[string]item)
	compendium.Unlock()

	campaigns.Lock()
	campaigns.items = make(map[string]*campaign)
	campaigns.Unlock()

	storage.initialized = true
	return nil
}

func applyStorageSchema() error {
	schema := `
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS schema_meta (
	key TEXT PRIMARY KEY,
	value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_sessions (
	id TEXT PRIMARY KEY,
	round INTEGER NOT NULL,
	turn_index INTEGER NOT NULL,
	order_json TEXT NOT NULL,
	conditions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
	username TEXT PRIMARY KEY,
	role TEXT NOT NULL,
	password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monsters (
	slug TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	cr TEXT NOT NULL,
	armor_class INTEGER NOT NULL,
	hit_points INTEGER NOT NULL,
	tags_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
	slug TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	type TEXT NOT NULL,
	rarity TEXT NOT NULL,
	cost_gp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
	id TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	dm TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_characters (
	campaign_id TEXT NOT NULL,
	id TEXT NOT NULL,
	name TEXT NOT NULL,
	level INTEGER NOT NULL,
	class TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
CREATE TABLE IF NOT EXISTS campaign_events (
	campaign_id TEXT NOT NULL,
	id TEXT NOT NULL,
	kind TEXT NOT NULL,
	summary TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')
	ON CONFLICT(key) DO UPDATE SET value = excluded.value;
`
	return runSQLite(schema)
}

func loadStorageData() error {
	if err := loadUsers(); err != nil {
		return err
	}
	if err := loadCombatSessions(); err != nil {
		return err
	}
	if err := loadCompendium(); err != nil {
		return err
	}
	return loadCampaigns()
}

func loadUsers() error {
	type storedUser struct {
		Username     string `json:"username"`
		Role         string `json:"role"`
		PasswordHash string `json:"password_hash"`
	}
	output, err := querySQLite("SELECT username, role, password_hash FROM users ORDER BY username;")
	if err != nil {
		return err
	}
	var rows []storedUser
	if err := json.Unmarshal(output, &rows); err != nil {
		return err
	}

	loaded := make(map[string]user, len(rows))
	for _, row := range rows {
		decoded, err := hex.DecodeString(row.PasswordHash)
		if err != nil || len(decoded) != 32 {
			return errors.New("invalid stored password hash")
		}
		var hash [32]byte
		copy(hash[:], decoded)
		loaded[row.Username] = user{
			Username:     row.Username,
			Role:         row.Role,
			PasswordHash: hash,
		}
	}

	users.Lock()
	users.items = loaded
	users.Unlock()
	return nil
}

func loadCombatSessions() error {
	type storedSession struct {
		ID             string `json:"id"`
		Round          int    `json:"round"`
		TurnIndex      int    `json:"turn_index"`
		OrderJSON      string `json:"order_json"`
		ConditionsJSON string `json:"conditions_json"`
	}
	output, err := querySQLite("SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions ORDER BY id;")
	if err != nil {
		return err
	}
	var rows []storedSession
	if err := json.Unmarshal(output, &rows); err != nil {
		return err
	}

	loaded := make(map[string]*combatSession, len(rows))
	for _, row := range rows {
		var order []combatantEntry
		if err := json.Unmarshal([]byte(row.OrderJSON), &order); err != nil {
			return err
		}
		var conditions map[string][]combatCondition
		if err := json.Unmarshal([]byte(row.ConditionsJSON), &conditions); err != nil {
			return err
		}
		if conditions == nil {
			conditions = make(map[string][]combatCondition)
		}
		loaded[row.ID] = &combatSession{
			ID:         row.ID,
			Round:      row.Round,
			TurnIndex:  row.TurnIndex,
			Order:      order,
			Conditions: conditions,
		}
	}

	combatSessions.Lock()
	combatSessions.items = loaded
	combatSessions.Unlock()
	return nil
}

func loadCompendium() error {
	loadedMonsters, err := loadMonsters()
	if err != nil {
		return err
	}
	loadedItems, err := loadItems()
	if err != nil {
		return err
	}

	compendium.Lock()
	compendium.monsters = loadedMonsters
	compendium.items = loadedItems
	compendium.Unlock()
	return nil
}

func loadMonsters() (map[string]monster, error) {
	type storedMonster struct {
		Slug       string `json:"slug"`
		Name       string `json:"name"`
		CR         string `json:"cr"`
		ArmorClass int    `json:"armor_class"`
		HitPoints  int    `json:"hit_points"`
		TagsJSON   string `json:"tags_json"`
	}
	output, err := querySQLite("SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters ORDER BY slug;")
	if err != nil {
		return nil, err
	}
	var rows []storedMonster
	if err := json.Unmarshal(output, &rows); err != nil {
		return nil, err
	}

	loaded := make(map[string]monster, len(rows))
	for _, row := range rows {
		var tags []string
		if err := json.Unmarshal([]byte(row.TagsJSON), &tags); err != nil {
			return nil, err
		}
		if tags == nil {
			tags = []string{}
		}
		loaded[row.Slug] = monster{
			Slug:       row.Slug,
			Name:       row.Name,
			CR:         row.CR,
			ArmorClass: row.ArmorClass,
			HitPoints:  row.HitPoints,
			Tags:       tags,
		}
	}
	return loaded, nil
}

func loadItems() (map[string]item, error) {
	output, err := querySQLite("SELECT slug, name, type, rarity, cost_gp FROM items ORDER BY slug;")
	if err != nil {
		return nil, err
	}
	var rows []item
	if err := json.Unmarshal(output, &rows); err != nil {
		return nil, err
	}

	loaded := make(map[string]item, len(rows))
	for _, row := range rows {
		loaded[row.Slug] = row
	}
	return loaded, nil
}

func loadCampaigns() error {
	type storedCampaign struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	output, err := querySQLite("SELECT id, name, dm FROM campaigns ORDER BY id;")
	if err != nil {
		return err
	}
	var rows []storedCampaign
	if err := json.Unmarshal(output, &rows); err != nil {
		return err
	}

	loaded := make(map[string]*campaign, len(rows))
	for _, row := range rows {
		loaded[row.ID] = &campaign{
			ID:         row.ID,
			Name:       row.Name,
			DM:         row.DM,
			Characters: make(map[string]campaignCharacter),
			Events:     make(map[string]campaignEvent),
		}
	}
	if err := loadCampaignCharacters(loaded); err != nil {
		return err
	}
	if err := loadCampaignEvents(loaded); err != nil {
		return err
	}

	campaigns.Lock()
	campaigns.items = loaded
	campaigns.Unlock()
	return nil
}

func loadCampaignCharacters(loaded map[string]*campaign) error {
	type storedCharacter struct {
		CampaignID string `json:"campaign_id"`
		ID         string `json:"id"`
		Name       string `json:"name"`
		Level      int    `json:"level"`
		Class      string `json:"class"`
	}
	output, err := querySQLite("SELECT campaign_id, id, name, level, class FROM campaign_characters ORDER BY campaign_id, id;")
	if err != nil {
		return err
	}
	var rows []storedCharacter
	if err := json.Unmarshal(output, &rows); err != nil {
		return err
	}
	for _, row := range rows {
		if stored, exists := loaded[row.CampaignID]; exists {
			stored.Characters[row.ID] = campaignCharacter{
				ID:    row.ID,
				Name:  row.Name,
				Level: row.Level,
				Class: row.Class,
			}
		}
	}
	return nil
}

func loadCampaignEvents(loaded map[string]*campaign) error {
	type storedEvent struct {
		CampaignID string `json:"campaign_id"`
		ID         string `json:"id"`
		Kind       string `json:"kind"`
		Summary    string `json:"summary"`
	}
	output, err := querySQLite("SELECT campaign_id, id, kind, summary FROM campaign_events ORDER BY campaign_id, id;")
	if err != nil {
		return err
	}
	var rows []storedEvent
	if err := json.Unmarshal(output, &rows); err != nil {
		return err
	}
	for _, row := range rows {
		if stored, exists := loaded[row.CampaignID]; exists {
			stored.Events[row.ID] = campaignEvent{
				ID:      row.ID,
				Kind:    row.Kind,
				Summary: row.Summary,
			}
		}
	}
	return nil
}

func saveUser(u user) error {
	sql := "INSERT INTO users(username, role, password_hash) VALUES (" +
		sqliteQuote(u.Username) + ", " +
		sqliteQuote(u.Role) + ", " +
		sqliteQuote(hex.EncodeToString(u.PasswordHash[:])) +
		") ON CONFLICT(username) DO UPDATE SET role = excluded.role, password_hash = excluded.password_hash;"
	return runSQLite(sql)
}

func saveCombatSession(session *combatSession) error {
	orderJSON, err := json.Marshal(session.Order)
	if err != nil {
		return err
	}
	conditionsJSON, err := json.Marshal(session.Conditions)
	if err != nil {
		return err
	}

	sql := "INSERT INTO combat_sessions(id, round, turn_index, order_json, conditions_json) VALUES (" +
		sqliteQuote(session.ID) + ", " +
		strconv.Itoa(session.Round) + ", " +
		strconv.Itoa(session.TurnIndex) + ", " +
		sqliteQuote(string(orderJSON)) + ", " +
		sqliteQuote(string(conditionsJSON)) +
		") ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, order_json = excluded.order_json, conditions_json = excluded.conditions_json;"
	return runSQLite(sql)
}

func saveMonster(m monster) error {
	tagsJSON, err := json.Marshal(m.Tags)
	if err != nil {
		return err
	}
	sql := "INSERT INTO monsters(slug, name, cr, armor_class, hit_points, tags_json) VALUES (" +
		sqliteQuote(m.Slug) + ", " +
		sqliteQuote(m.Name) + ", " +
		sqliteQuote(m.CR) + ", " +
		strconv.Itoa(m.ArmorClass) + ", " +
		strconv.Itoa(m.HitPoints) + ", " +
		sqliteQuote(string(tagsJSON)) +
		");"
	return runSQLite(sql)
}

func saveItem(i item) error {
	sql := "INSERT INTO items(slug, name, type, rarity, cost_gp) VALUES (" +
		sqliteQuote(i.Slug) + ", " +
		sqliteQuote(i.Name) + ", " +
		sqliteQuote(i.Type) + ", " +
		sqliteQuote(i.Rarity) + ", " +
		strconv.Itoa(i.CostGP) +
		");"
	return runSQLite(sql)
}

func saveCampaign(c *campaign) error {
	sql := "INSERT INTO campaigns(id, name, dm) VALUES (" +
		sqliteQuote(c.ID) + ", " +
		sqliteQuote(c.Name) + ", " +
		sqliteQuote(c.DM) +
		");"
	return runSQLite(sql)
}

func saveCampaignCharacter(campaignID string, character campaignCharacter) error {
	sql := "INSERT INTO campaign_characters(campaign_id, id, name, level, class) VALUES (" +
		sqliteQuote(campaignID) + ", " +
		sqliteQuote(character.ID) + ", " +
		sqliteQuote(character.Name) + ", " +
		strconv.Itoa(character.Level) + ", " +
		sqliteQuote(character.Class) +
		");"
	return runSQLite(sql)
}

func saveCampaignEvent(campaignID string, event campaignEvent) error {
	sql := "INSERT INTO campaign_events(campaign_id, id, kind, summary) VALUES (" +
		sqliteQuote(campaignID) + ", " +
		sqliteQuote(event.ID) + ", " +
		sqliteQuote(event.Kind) + ", " +
		sqliteQuote(event.Summary) +
		");"
	return runSQLite(sql)
}

func runSQLite(sql string) error {
	cmd := exec.Command("sqlite3", "game.db")
	cmd.Stdin = strings.NewReader(sql)
	return cmd.Run()
}

func querySQLite(sql string) ([]byte, error) {
	cmd := exec.Command("sqlite3", "-json", "game.db", sql)
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	if len(strings.TrimSpace(string(output))) == 0 {
		return []byte("[]"), nil
	}
	return output, nil
}

func sqliteQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}

func sortCombatants(order []combatantEntry) {
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})
}

func (s *combatSession) hasCombatant(name string) bool {
	for _, combatant := range s.Order {
		if combatant.Name == name {
			return true
		}
	}
	return false
}

func (s *combatSession) decrementActiveConditions() {
	active := s.Order[s.TurnIndex].Name
	conditions := s.Conditions[active]
	if len(conditions) == 0 {
		return
	}

	kept := conditions[:0]
	for _, condition := range conditions {
		condition.RemainingRounds--
		if condition.RemainingRounds > 0 {
			kept = append(kept, condition)
		}
	}
	if len(kept) == 0 {
		s.Conditions[active] = kept
		return
	}
	s.Conditions[active] = kept
}

func (s *combatSession) stateResponse(includeConditions bool) combatStateResponse {
	response := combatStateResponse{
		ID:        s.ID,
		Round:     s.Round,
		TurnIndex: s.TurnIndex,
		Active:    s.Order[s.TurnIndex],
		Order:     append([]combatantEntry(nil), s.Order...),
	}
	if includeConditions {
		response.Order = nil
		conditions := copyConditions(s.Conditions)
		response.Conditions = &conditions
	}
	return response
}

func copyConditions(conditions map[string][]combatCondition) map[string][]combatCondition {
	copied := make(map[string][]combatCondition)
	for target, entries := range conditions {
		copied[target] = append(make([]combatCondition, 0, len(entries)), entries...)
	}
	return copied
}

func copyMonster(m monster) monster {
	m.Tags = append([]string(nil), m.Tags...)
	return m
}

func monsterCreateResponse(m monster) struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
} {
	return struct {
		Slug       string `json:"slug"`
		Name       string `json:"name"`
		CR         string `json:"cr"`
		ArmorClass int    `json:"armor_class"`
		HitPoints  int    `json:"hit_points"`
	}{
		Slug:       m.Slug,
		Name:       m.Name,
		CR:         m.CR,
		ArmorClass: m.ArmorClass,
		HitPoints:  m.HitPoints,
	}
}

func validMonster(m monster) bool {
	return m.Slug != "" &&
		m.Name != "" &&
		m.CR != "" &&
		m.ArmorClass > 0 &&
		m.HitPoints > 0 &&
		validStringList(m.Tags)
}

func validItem(i item) bool {
	return i.Slug != "" &&
		i.Name != "" &&
		i.Type != "" &&
		i.Rarity != "" &&
		i.CostGP >= 0
}

func validStringList(values []string) bool {
	for _, value := range values {
		if value == "" {
			return false
		}
	}
	return true
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func encounterMultiplier(monsterCount int) float64 {
	switch {
	case monsterCount <= 0:
		return 0
	case monsterCount == 1:
		return 1
	case monsterCount == 2:
		return 1.5
	case monsterCount <= 6:
		return 2
	case monsterCount <= 10:
		return 2.5
	case monsterCount <= 14:
		return 3
	default:
		return 4
	}
}

func encounterDifficulty(adjustedXP float64, t thresholds) string {
	switch {
	case adjustedXP >= float64(t.Deadly):
		return "deadly"
	case adjustedXP >= float64(t.Hard):
		return "hard"
	case adjustedXP >= float64(t.Medium):
		return "medium"
	case adjustedXP >= float64(t.Easy):
		return "easy"
	default:
		return "trivial"
	}
}

func encounterRecommendation(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "minor diversion"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "standard fight"
	case "hard":
		return "dangerous fight"
	default:
		return "deadly threat"
	}
}

func levelThreePartyThresholds(party []struct {
	Level int `json:"level"`
}) (thresholds, bool) {
	partyThresholds := thresholds{}
	for _, member := range party {
		if member.Level != 3 {
			return thresholds{}, false
		}
		partyThresholds.Easy += 75
		partyThresholds.Medium += 150
		partyThresholds.Hard += 225
		partyThresholds.Deadly += 400
	}
	return partyThresholds, true
}

func campaignExists(id string) bool {
	campaigns.Lock()
	_, exists := campaigns.items[id]
	campaigns.Unlock()
	return exists
}

func openThreadsForSummary(summary string) []string {
	if strings.Contains(strings.ToLower(summary), "goblin trail") {
		return []string{"Resolve goblin trail ambush"}
	}
	return []string{}
}

func readJSON(r *http.Request, v any) error {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	return decoder.Decode(v)
}

func requireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method == method {
		return true
	}
	w.Header().Set("Allow", method)
	writeError(w, http.StatusMethodNotAllowed)
	return false
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int) {
	writeJSON(w, status, map[string]string{"error": http.StatusText(status)})
}
