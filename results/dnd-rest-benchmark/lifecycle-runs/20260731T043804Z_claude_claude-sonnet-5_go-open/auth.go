package main

import (
	"net/http"
	"regexp"
	"sync"

	"golang.org/x/crypto/bcrypt"
)

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

type user struct {
	Username     string
	Role         string
	PasswordHash string
}

// usersMu guards users, the in-memory index mirroring the users table.
var (
	usersMu sync.Mutex
	users   = map[string]*user{}
)

func hashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

func checkPassword(hash, password string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

type registerRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req registerRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !usernameRe.MatchString(req.Username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, _, or -")
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

	usersMu.Lock()
	defer usersMu.Unlock()

	if _, exists := users[req.Username]; exists {
		writeError(w, http.StatusConflict, "username already exists")
		return
	}

	hash, err := hashPassword(req.Password)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to register user")
		return
	}

	newUser := &user{
		Username:     req.Username,
		Role:         req.Role,
		PasswordHash: hash,
	}
	if err := saveUserToDB(newUser); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to register user")
		return
	}
	users[req.Username] = newUser

	writeJSON(w, http.StatusCreated, map[string]string{
		"username": req.Username,
		"role":     req.Role,
	})
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req loginRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Username == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "username and password are required")
		return
	}

	usersMu.Lock()
	u, exists := users[req.Username]
	usersMu.Unlock()

	if !exists || !checkPassword(u.PasswordHash, req.Password) {
		writeError(w, http.StatusUnauthorized, "invalid username or password")
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"username": req.Username,
		"token":    "session-" + req.Username,
	})
}
