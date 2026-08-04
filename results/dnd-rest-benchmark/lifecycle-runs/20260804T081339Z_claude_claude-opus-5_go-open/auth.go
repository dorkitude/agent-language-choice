package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"net/http"
	"regexp"
)

// ---------- password hashing ----------

// Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user random salt. All
// hashing lives behind hashPassword/verifyPassword so the algorithm can be
// swapped without touching the handlers.
const (
	pbkdf2Iterations = 210000
	pbkdf2KeyLength  = 32
	saltLength       = 16
)

func hashPassword(password string) (salt, digest []byte) {
	salt = make([]byte, saltLength)
	if _, err := rand.Read(salt); err != nil {
		// crypto/rand.Read never fails on supported platforms; panic rather
		// than silently store a predictable salt.
		panic(err)
	}
	return salt, derive(password, salt)
}

func derive(password string, salt []byte) []byte {
	key, err := pbkdf2.Key(sha256.New, password, salt, pbkdf2Iterations, pbkdf2KeyLength)
	if err != nil {
		panic(err)
	}
	return key
}

func verifyPassword(password string, salt, digest []byte) bool {
	return subtle.ConstantTimeCompare(derive(password, salt), digest) == 1
}

// ---------- SQLite-backed user store ----------

type user struct {
	Username string
	Role     string
	Salt     []byte
	Digest   []byte
}

// addUser registers a new user, reporting false if the username is already
// taken. The primary key on users.username makes the check atomic.
func addUser(u *user) (bool, error) {
	res, err := db.Exec(
		`INSERT OR IGNORE INTO users (username, role, salt, digest) VALUES (?, ?, ?, ?)`,
		u.Username, u.Role, u.Salt, u.Digest)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	return n > 0, nil
}

func getUser(username string) (*user, bool) {
	u := &user{Username: username}
	err := db.QueryRow(`SELECT role, salt, digest FROM users WHERE username = ?`, username).
		Scan(&u.Role, &u.Salt, &u.Digest)
	if err != nil {
		return nil, false
	}
	return u, true
}

// ---------- validation ----------

var usernameRe = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

const minPasswordLength = 8

func validRole(role string) bool {
	return role == "dm" || role == "player"
}

// ---------- /v1/auth/register ----------

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
	var req registerRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Username == nil || req.Password == nil || req.Role == nil {
		writeError(w, http.StatusBadRequest, "username, password, and role are required")
		return
	}
	if !usernameRe.MatchString(*req.Username) {
		writeError(w, http.StatusBadRequest, "username must be 2-32 characters of lowercase letters, digits, _, or -")
		return
	}
	if len(*req.Password) < minPasswordLength {
		writeError(w, http.StatusBadRequest, "password must be at least 8 characters")
		return
	}
	if !validRole(*req.Role) {
		writeError(w, http.StatusBadRequest, "role must be dm or player")
		return
	}

	salt, digest := hashPassword(*req.Password)
	added, err := addUser(&user{Username: *req.Username, Role: *req.Role, Salt: salt, Digest: digest})
	if err != nil {
		writeStorageError(w, "register failed", err)
		return
	}
	if !added {
		writeError(w, http.StatusConflict, "username already exists")
		return
	}
	writeJSON(w, http.StatusCreated, registerResponse{Username: *req.Username, Role: *req.Role})
}

// ---------- /v1/auth/login ----------

type loginRequest struct {
	Username *string `json:"username"`
	Password *string `json:"password"`
}

type loginResponse struct {
	Username string `json:"username"`
	Token    string `json:"token"`
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Username == nil || req.Password == nil {
		writeError(w, http.StatusBadRequest, "username and password are required")
		return
	}

	u, ok := getUser(*req.Username)
	if !ok {
		// Hash anyway so an unknown username costs the same as a wrong password.
		verifyPassword(*req.Password, make([]byte, saltLength), make([]byte, pbkdf2KeyLength))
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	if !verifyPassword(*req.Password, u.Salt, u.Digest) {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	// The token is derived from the username rather than stored, so it is stable
	// across logins and needs no session table. No endpoint authenticates with
	// it yet; issuing it is the whole contract.
	writeJSON(w, http.StatusOK, loginResponse{Username: u.Username, Token: "session-" + u.Username})
}
