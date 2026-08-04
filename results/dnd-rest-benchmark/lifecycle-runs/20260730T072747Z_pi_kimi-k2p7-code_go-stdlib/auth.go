package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"regexp"
)

// userRe matches the allowed username format for registration: 2-32 characters
// drawn from lowercase letters, digits, underscore, and hyphen.
var userRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

type User struct {
	Username string `json:"username"`
	Role     string `json:"role"`
	Salt     string `json:"salt"`
	Hash     string `json:"hash"`
}

// hashPassword generates a random 16-byte salt and returns the SHA-256 digest
// of salt+password, encoded with base64 (no padding) for both values.
func hashPassword(password string) (salt string, hash string, err error) {
	buf := make([]byte, 16)
	if _, err = rand.Read(buf); err != nil {
		return "", "", err
	}
	salt = base64.RawStdEncoding.EncodeToString(buf)
	h := sha256.New()
	h.Write([]byte(salt))
	h.Write([]byte(password))
	hash = base64.RawStdEncoding.EncodeToString(h.Sum(nil))
	return salt, hash, nil
}

// verifyPassword recomputes the password digest and compares it to the stored
// hash using a constant-time comparison.
func verifyPassword(password, salt, hash string) bool {
	h := sha256.New()
	h.Write([]byte(salt))
	h.Write([]byte(password))
	expected := base64.RawStdEncoding.EncodeToString(h.Sum(nil))
	return subtle.ConstantTimeCompare([]byte(expected), []byte(hash)) == 1
}

type registerRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

type authUserResponse struct {
	Username string `json:"username"`
	Role     string `json:"role"`
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type loginResponse struct {
	Username string `json:"username"`
	Token    string `json:"token"`
}

// registerUserHandler creates a new user with a hashed password. Usernames must
// match the allowed pattern, passwords must be at least 8 characters, and the
// role must be either "dm" or "player".
func registerUserHandler(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !userRe.MatchString(req.Username) || req.Username == "" {
		writeError(w, http.StatusBadRequest, "invalid username")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "invalid password")
		return
	}
	if req.Role != "dm" && req.Role != "player" {
		writeError(w, http.StatusBadRequest, "invalid role")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM users WHERE username=%s LIMIT 1;", sq(req.Username)))
	if err != nil {
		log.Printf("register query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "username already exists")
		return
	}

	salt, hash, err := hashPassword(req.Password)
	if err != nil {
		log.Printf("password hash error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO users (username, role, salt, hash) VALUES (%s, %s, %s, %s);",
		sq(req.Username), sq(req.Role), sq(salt), sq(hash))); err != nil {
		log.Printf("register insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, authUserResponse{Username: req.Username, Role: req.Role})
}

// loadUserByUsername loads a user row by username. The caller must hold dbMu.
// The bool result indicates whether the row exists.
func loadUserByUsername(username string) (User, bool, error) {
	var users []User
	if err := queryRows(fmt.Sprintf("SELECT username, role, salt, hash FROM users WHERE username=%s LIMIT 1;", sq(username)), &users); err != nil {
		return User{}, false, err
	}
	if len(users) == 0 {
		return User{}, false, nil
	}
	return users[0], true, nil
}

// loginHandler validates credentials and returns a deterministic session token
// of the form "session-<username>". The token is not a signed JWT; it is simply
// a marker that callers may pass back in later requests.
func loginHandler(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Username == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	user, ok, err := loadUserByUsername(req.Username)
	if err != nil {
		log.Printf("login query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || !verifyPassword(req.Password, user.Salt, user.Hash) {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}

	writeJSON(w, http.StatusOK, loginResponse{
		Username: user.Username,
		Token:    "session-" + user.Username,
	})
}
