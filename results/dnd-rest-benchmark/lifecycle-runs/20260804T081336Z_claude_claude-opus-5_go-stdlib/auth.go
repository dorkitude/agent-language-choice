package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"net/http"
	"regexp"
	"strings"
	"sync"
)

// ---------- password hashing ----------
//
// Passwords are stored as PBKDF2-HMAC-SHA256 derivations over a random
// per-user salt (crypto/pbkdf2, Go standard library). All password handling is
// isolated in hashPassword / verifyPassword so the KDF can be swapped without
// touching the handlers.

const (
	pbkdf2Iterations = 210000
	pbkdf2KeyLen     = 32
	saltLen          = 16
)

type passwordHash struct {
	salt []byte
	key  []byte
}

func hashPassword(password string) (passwordHash, error) {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return passwordHash{}, err
	}
	key, err := pbkdf2.Key(sha256.New, password, salt, pbkdf2Iterations, pbkdf2KeyLen)
	if err != nil {
		return passwordHash{}, err
	}
	return passwordHash{salt: salt, key: key}, nil
}

func verifyPassword(h passwordHash, password string) bool {
	key, err := pbkdf2.Key(sha256.New, password, h.salt, pbkdf2Iterations, pbkdf2KeyLen)
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare(key, h.key) == 1
}

// hashScheme labels the on-disk format so a future KDF change can be detected
// rather than silently misread.
const hashScheme = "pbkdf2-sha256"

// encoded renders the hash for storage as "scheme$salt$key" in hex. There is no
// inverse: parsePasswordHash recovers the salt and key, never the password.
func (h passwordHash) encoded() string {
	return hashScheme + "$" + hex.EncodeToString(h.salt) + "$" + hex.EncodeToString(h.key)
}

// parsePasswordHash reverses encoded. It reports false for anything that is not
// a well-formed hash of the current scheme, so unreadable rows are skipped at
// load time instead of producing an account nobody can log into.
func parsePasswordHash(s string) (passwordHash, bool) {
	parts := strings.Split(s, "$")
	if len(parts) != 3 || parts[0] != hashScheme {
		return passwordHash{}, false
	}
	salt, err := hex.DecodeString(parts[1])
	if err != nil {
		return passwordHash{}, false
	}
	key, err := hex.DecodeString(parts[2])
	if err != nil {
		return passwordHash{}, false
	}
	return passwordHash{salt: salt, key: key}, true
}

// ---------- user store ----------

type user struct {
	Username string
	Role     string
	Hash     passwordHash
}

type userStore struct {
	mu    sync.Mutex
	users map[string]*user
}

var users = &userStore{users: map[string]*user{}}

var usernamePattern = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

func validRole(role string) bool {
	return role == "dm" || role == "player"
}

// ---------- POST /v1/auth/register ----------

type registerRequest struct {
	Username *string `json:"username"`
	Password *string `json:"password"`
	Role     *string `json:"role"`
}

type registerResponse struct {
	Username string `json:"username"`
	Role     string `json:"role"`
}

func handleRegister(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req registerRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Username == nil {
		writeError(w, http.StatusBadRequest, "username is required")
		return
	}
	if req.Password == nil {
		writeError(w, http.StatusBadRequest, "password is required")
		return
	}
	if req.Role == nil {
		writeError(w, http.StatusBadRequest, "role is required")
		return
	}
	username := *req.Username
	if !usernamePattern.MatchString(username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, _ or -")
		return
	}
	if len(*req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	role := strings.TrimSpace(*req.Role)
	if !validRole(role) {
		writeError(w, http.StatusBadRequest, "role must be dm or player")
		return
	}

	hash, err := hashPassword(*req.Password)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not hash password")
		return
	}

	users.mu.Lock()
	if _, exists := users.users[username]; exists {
		users.mu.Unlock()
		writeError(w, http.StatusConflict, "username already exists")
		return
	}
	users.users[username] = &user{Username: username, Role: role, Hash: hash}
	users.mu.Unlock()
	flush()

	// Registration creates a new resource: 201.
	writeJSON(w, http.StatusCreated, registerResponse{Username: username, Role: role})
}

// ---------- POST /v1/auth/login ----------

type loginRequest struct {
	Username *string `json:"username"`
	Password *string `json:"password"`
}

type loginResponse struct {
	Username string `json:"username"`
	Token    string `json:"token"`
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req loginRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Username == nil {
		writeError(w, http.StatusBadRequest, "username is required")
		return
	}
	if req.Password == nil {
		writeError(w, http.StatusBadRequest, "password is required")
		return
	}

	users.mu.Lock()
	u, ok := users.users[*req.Username]
	users.mu.Unlock()
	// Unknown user and wrong password share one message so the response does not
	// reveal which usernames exist.
	if !ok || !verifyPassword(u.Hash, *req.Password) {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}

	// The token is a deterministic placeholder, not a verified credential: no
	// endpoint authenticates with it.
	writeJSON(w, http.StatusOK, loginResponse{Username: u.Username, Token: "session-" + u.Username})
}
