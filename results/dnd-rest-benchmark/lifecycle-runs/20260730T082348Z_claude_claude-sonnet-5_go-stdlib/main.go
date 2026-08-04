package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
)

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatant struct {
	Name       string `json:"name"`
	Score      int    `json:"score"`
	dex        int
	Conditions []condition `json:"-"`
}

type combatSession struct {
	ID        string
	Round     int
	TurnIndex int
	Order     []*combatant
}

var (
	combatMu       sync.Mutex
	combatSessions = map[string]*combatSession{}
)

func handleCreateCombatSession(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "combatants are required")
		return
	}

	combatMu.Lock()

	if _, exists := combatSessions[req.ID]; exists {
		combatMu.Unlock()
		writeError(w, http.StatusBadRequest, "session id already exists")
		return
	}

	order := make([]*combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			combatMu.Unlock()
			writeError(w, http.StatusBadRequest, "combatant name is required")
			return
		}
		order = append(order, &combatant{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex})
	}

	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	session := &combatSession{
		ID:        req.ID,
		Round:     1,
		TurnIndex: 0,
		Order:     order,
	}
	combatSessions[req.ID] = session
	combatMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     activeCombatant(session),
		"order":      orderSummary(session),
	})
}

func activeCombatant(s *combatSession) map[string]interface{} {
	c := s.Order[s.TurnIndex]
	return map[string]interface{}{"name": c.Name, "score": c.Score}
}

func orderSummary(s *combatSession) []map[string]interface{} {
	out := make([]map[string]interface{}, 0, len(s.Order))
	for _, c := range s.Order {
		out = append(out, map[string]interface{}{"name": c.Name, "score": c.Score})
	}
	return out
}

func findSessionFromPath(prefix, suffix, path string) (string, bool) {
	if !strings.HasPrefix(path, prefix) || !strings.HasSuffix(path, suffix) {
		return "", false
	}
	id := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	if id == "" {
		return "", false
	}
	return id, true
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	id, ok := findSessionFromPath("/v1/combat/sessions/", "/conditions", r.URL.Path)
	if !ok {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	var req struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds *int   `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Condition == "" {
		writeError(w, http.StatusBadRequest, "target and condition are required")
		return
	}
	if req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be a positive integer")
		return
	}

	combatMu.Lock()

	session, exists := combatSessions[id]
	if !exists {
		combatMu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	var target *combatant
	for _, c := range session.Order {
		if c.Name == req.Target {
			target = c
			break
		}
	}
	if target == nil {
		combatMu.Unlock()
		writeError(w, http.StatusBadRequest, "target must name a combatant in the session")
		return
	}

	target.Conditions = append(target.Conditions, condition{
		Condition:       req.Condition,
		RemainingRounds: *req.DurationRounds,
	})
	combatMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"target":     target.Name,
		"conditions": target.Conditions,
	})
}

func handleAdvanceTurn(w http.ResponseWriter, r *http.Request) {
	id, ok := findSessionFromPath("/v1/combat/sessions/", "/advance", r.URL.Path)
	if !ok {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	combatMu.Lock()

	session, exists := combatSessions[id]
	if !exists {
		combatMu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}

	active := session.Order[session.TurnIndex]
	remaining := []condition{}
	for _, cond := range active.Conditions {
		cond.RemainingRounds--
		if cond.RemainingRounds > 0 {
			remaining = append(remaining, cond)
		}
	}
	active.Conditions = remaining

	conditionsOut := map[string][]condition{}
	for _, c := range session.Order {
		if len(c.Conditions) > 0 {
			conditionsOut[c.Name] = c.Conditions
		} else if c.Name == active.Name {
			conditionsOut[c.Name] = []condition{}
		}
	}
	combatMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     activeCombatant(session),
		"conditions": conditionsOut,
	})
}

func handleCombatSessionSub(w http.ResponseWriter, r *http.Request) {
	if strings.HasSuffix(r.URL.Path, "/conditions") {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		handleAddCondition(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/advance") {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		handleAdvanceTurn(w, r)
		return
	}
	writeError(w, http.StatusNotFound, "not found")
}

// hashPassword and verifyPassword isolate password handling behind a small
// helper. This uses a salted SHA-256 hash for determinism in the benchmark
// environment; swap this helper for a production-grade KDF (e.g. bcrypt or
// scrypt) when a suitable dependency is available.
func hashPassword(password string) (salt string, hash string) {
	saltBytes := make([]byte, 16)
	if _, err := rand.Read(saltBytes); err != nil {
		log.Fatal(err)
	}
	salt = hex.EncodeToString(saltBytes)
	sum := sha256.Sum256([]byte(salt + password))
	hash = hex.EncodeToString(sum[:])
	return salt, hash
}

func verifyPassword(password, salt, hash string) bool {
	sum := sha256.Sum256([]byte(salt + password))
	candidate := hex.EncodeToString(sum[:])
	return subtle.ConstantTimeCompare([]byte(candidate), []byte(hash)) == 1
}

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

type userAccount struct {
	Username     string
	Role         string
	PasswordSalt string
	PasswordHash string
}

var (
	userMu    sync.Mutex
	userStore = map[string]*userAccount{}
)

func handleRegister(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !usernameRe.MatchString(req.Username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, underscore, or hyphen")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		writeError(w, http.StatusBadRequest, "role must be dm or player")
		return
	}

	userMu.Lock()

	if _, exists := userStore[req.Username]; exists {
		userMu.Unlock()
		writeError(w, http.StatusConflict, "username already exists")
		return
	}

	salt, hash := hashPassword(req.Password)
	userStore[req.Username] = &userAccount{
		Username:     req.Username,
		Role:         req.Role,
		PasswordSalt: salt,
		PasswordHash: hash,
	}
	userMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"username": req.Username,
		"role":     req.Role,
	})
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Username == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "username and password are required")
		return
	}

	userMu.Lock()
	account, exists := userStore[req.Username]
	userMu.Unlock()

	if !exists || !verifyPassword(req.Password, account.PasswordSalt, account.PasswordHash) {
		writeError(w, http.StatusUnauthorized, "invalid username or password")
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"username": account.Username,
		"token":    "session-" + account.Username,
	})
}

func withMethod(method string, h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != method {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		h(w, r)
	}
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	initStorage()

	mux := http.NewServeMux()
	mux.HandleFunc("/health", withMethod(http.MethodGet, handleHealth))
	mux.HandleFunc("/healthz", withMethod(http.MethodGet, handleLiveness))
	mux.HandleFunc("/readyz", withMethod(http.MethodGet, handleReadiness))
	mux.HandleFunc("/v1/storage/status", withMethod(http.MethodGet, handleStorageStatus))
	mux.HandleFunc("/v1/storage/reset", withMethod(http.MethodPost, handleStorageReset))
	mux.HandleFunc("/v1/dice/stats", withMethod(http.MethodPost, handleDiceStats))
	mux.HandleFunc("/v1/checks/ability", withMethod(http.MethodPost, handleAbilityCheck))
	mux.HandleFunc("/v1/encounters/adjusted-xp", withMethod(http.MethodPost, handleAdjustedXP))
	mux.HandleFunc("/v1/initiative/order", withMethod(http.MethodPost, handleInitiativeOrder))
	mux.HandleFunc("/v1/characters/ability-modifier", withMethod(http.MethodPost, handleAbilityModifier))
	mux.HandleFunc("/v1/characters/proficiency", withMethod(http.MethodPost, handleProficiency))
	mux.HandleFunc("/v1/characters/derived-stats", withMethod(http.MethodPost, handleDerivedStats))
	mux.HandleFunc("/v1/combat/sessions", withMethod(http.MethodPost, handleCreateCombatSession))
	mux.HandleFunc("/v1/combat/sessions/", handleCombatSessionSub)
	mux.HandleFunc("/v1/auth/register", withMethod(http.MethodPost, handleRegister))
	mux.HandleFunc("/v1/auth/login", withMethod(http.MethodPost, handleLogin))
	mux.HandleFunc("/v1/compendium/monsters", handleMonstersCollection)
	mux.HandleFunc("/v1/compendium/monsters/", handleMonstersItem)
	mux.HandleFunc("/v1/compendium/items", handleItemsCollection)
	mux.HandleFunc("/v1/compendium/items/", handleItemsItem)
	mux.HandleFunc("/v1/campaigns", handleCampaignsCollection)
	mux.HandleFunc("/v1/campaigns/", handleCampaignsSub)
	mux.HandleFunc("/v1/phb/spell-slots", withMethod(http.MethodPost, handleSpellSlots))
	mux.HandleFunc("/v1/phb/rests/long", withMethod(http.MethodPost, handleLongRest))
	mux.HandleFunc("/v1/phb/equipment-load", withMethod(http.MethodPost, handleEquipmentLoad))
	mux.HandleFunc("/v1/dm/encounter-builder", withMethod(http.MethodPost, handleEncounterBuilder))
	mux.HandleFunc("/v1/dm/loot-parcel", withMethod(http.MethodPost, handleLootParcel))
	mux.HandleFunc("/v1/dm/session-recap", withMethod(http.MethodPost, handleSessionRecap))
	mux.HandleFunc("/v1/schema", withMethod(http.MethodGet, handleAPISchema))
	mux.HandleFunc("/v1/play/campaigns", handlePlayCampaignsCollection)
	mux.HandleFunc("/v1/play/campaigns/", handlePlayCampaignsSub)

	addr := "127.0.0.1:" + port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
