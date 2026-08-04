package main

import (
	"encoding/json"
	"log"
	"net/http"

	"golang.org/x/crypto/bcrypt"
)

func hashPassword(password string) (string, error) {
	bytes, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(bytes), err
}

func checkPassword(password, hash string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if !usernameExpr.MatchString(req.Username) {
		badRequest(w, "username must be 2-32 lowercase letters, digits, _, or -")
		return
	}
	if len(req.Password) < 8 {
		badRequest(w, "password must be at least 8 characters")
		return
	}
	if req.Role != roleDM && req.Role != rolePlayer {
		badRequest(w, "role must be dm or player")
		return
	}

	users.mu.Lock()
	defer users.mu.Unlock()

	if _, exists := users.users[req.Username]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "username already exists"})
		return
	}

	hash, err := hashPassword(req.Password)
	if err != nil {
		log.Printf("hash password: %v", err)
		badRequest(w, "failed to process password")
		return
	}

	if err := dbCreateUser(req.Username, hash, req.Role); err != nil {
		log.Printf("create user: %v", err)
		badRequest(w, "failed to create user")
		return
	}

	users.users[req.Username] = &user{
		Username:     req.Username,
		PasswordHash: hash,
		Role:         req.Role,
	}

	writeJSON(w, http.StatusCreated, map[string]string{
		"username": req.Username,
		"role":     req.Role,
	})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	users.mu.RLock()
	defer users.mu.RUnlock()

	u, exists := users.users[req.Username]
	if !exists || !checkPassword(req.Password, u.PasswordHash) {
		unauthorized(w, "invalid credentials")
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"username": req.Username,
		"token":    "session-" + req.Username,
	})
}
