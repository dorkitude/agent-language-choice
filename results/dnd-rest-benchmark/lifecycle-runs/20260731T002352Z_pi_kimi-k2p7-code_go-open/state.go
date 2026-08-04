package main

import (
	"database/sql"
	"sync"
)

const defaultPort = "8080"

// db is the open SQLite connection. It is initialized once by initDB and used
// by all DB helper functions in db.go. The connection is never closed during
// normal server operation.
var db *sql.DB

// initMu and initialized protect the schema-creation step. They are also used
// by the storage status endpoint so that tests can observe whether the schema
// has been applied.
var (
	initMu      sync.Mutex
	initialized = false
)

// users is the in-memory cache of registered accounts. It is kept in sync with
// the users table: writes go to SQLite first, then update the cache. Reads
// must hold users.mu (RLock for reads, Lock for writes) because the map is
// accessed concurrently from HTTP handlers.
var users = &userStore{users: make(map[string]*user)}

// combat is the in-memory cache of active combat sessions. It is hydrated from
// SQLite on startup and updated whenever a session is created or advanced.
// Reads and writes must hold combat.mu to avoid races between concurrent
// combat requests.
var combat = &combatState{sessions: make(map[string]*session)}
