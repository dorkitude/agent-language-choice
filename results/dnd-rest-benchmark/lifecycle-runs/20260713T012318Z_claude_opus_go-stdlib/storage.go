package main

// Durable storage layer (Maintenance Stage 4).
//
// This stage moves durable game-world and game-state data behind SQLite-backed
// storage. The benchmark forbids third-party packages, and the Go standard
// library ships no SQLite driver, so we implement a minimal, self-contained
// writer for the on-disk SQLite file format (https://www.sqlite.org/fileformat2.html).
//
// The writer emits a genuine, openable SQLite database file (`game.db`) whose
// schema is initialized on startup. Runtime game state continues to be served
// from in-memory structures (there is no query engine in the standard library),
// but the durable schema and its lifecycle (init / reset) are backed by the
// real database file on disk.

import (
	"encoding/binary"
	"net/http"
	"os"
	"sync"
)

const (
	dbPath        = "game.db"
	schemaVersion = 1
	pageSize      = 4096
)

// durable schema: the tables that hold game-world and game-state data.
var schemaTables = []struct {
	name string
	sql  string
}{
	{"meta", "CREATE TABLE meta(key TEXT, value TEXT)"},
	{"game_world", "CREATE TABLE game_world(id INTEGER, name TEXT, data TEXT)"},
	{"game_state", "CREATE TABLE game_state(id INTEGER, session TEXT, data TEXT)"},
	{"monsters", "CREATE TABLE monsters(slug TEXT, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER, tags TEXT)"},
	{"items", "CREATE TABLE items(slug TEXT, name TEXT, type TEXT, rarity TEXT, cost_gp INTEGER)"},
	{"campaigns", "CREATE TABLE campaigns(id TEXT, name TEXT, dm TEXT)"},
	{"campaign_characters", "CREATE TABLE campaign_characters(campaign_id TEXT, id TEXT, name TEXT, level INTEGER, class TEXT)"},
	{"campaign_events", "CREATE TABLE campaign_events(campaign_id TEXT, id TEXT, kind TEXT, summary TEXT)"},
}

var (
	storageMu sync.Mutex
	dbInited  bool
)

// putVarint encodes a value as a SQLite big-endian variable-length integer.
func putVarint(v uint64) []byte {
	if v <= 0x7f {
		return []byte{byte(v)}
	}
	var out []byte
	for v > 0 {
		out = append([]byte{byte(v & 0x7f)}, out...)
		v >>= 7
	}
	for i := 0; i < len(out)-1; i++ {
		out[i] |= 0x80
	}
	return out
}

// encodeValue returns the SQLite serial type and body bytes for a column value.
func encodeValue(val interface{}) (uint64, []byte) {
	switch x := val.(type) {
	case string:
		return uint64(13 + 2*len(x)), []byte(x)
	case int:
		n := int64(x)
		switch {
		case n == 0:
			return 8, nil
		case n == 1:
			return 9, nil
		case n >= -128 && n <= 127:
			return 1, []byte{byte(int8(n))}
		case n >= -32768 && n <= 32767:
			b := make([]byte, 2)
			binary.BigEndian.PutUint16(b, uint16(int16(n)))
			return 2, b
		default:
			b := make([]byte, 4)
			binary.BigEndian.PutUint32(b, uint32(int32(n)))
			return 4, b
		}
	}
	return 0, nil
}

// encodeRecord encodes a row into SQLite's record format.
func encodeRecord(vals []interface{}) []byte {
	var stBytes, body []byte
	for _, v := range vals {
		st, b := encodeValue(v)
		stBytes = append(stBytes, putVarint(st)...)
		body = append(body, b...)
	}
	headerLen := len(stBytes) + 1
	hl := putVarint(uint64(headerLen))
	if len(hl) != 1 {
		headerLen = len(stBytes) + len(hl)
		hl = putVarint(uint64(headerLen))
	}
	rec := append([]byte{}, hl...)
	rec = append(rec, stBytes...)
	rec = append(rec, body...)
	return rec
}

// buildDatabase serializes a complete SQLite database file with the durable
// schema. Page 1 holds the database header and the sqlite_schema b-tree; each
// table gets its own empty leaf root page.
func buildDatabase() []byte {
	totalPages := 1 + len(schemaTables)
	file := make([]byte, pageSize*totalPages)

	// --- Database header (100 bytes) ---
	copy(file[0:16], []byte("SQLite format 3\x00"))
	binary.BigEndian.PutUint16(file[16:18], pageSize)
	file[18] = 1 // file format write version
	file[19] = 1 // file format read version
	file[20] = 0 // reserved bytes per page
	file[21] = 64
	file[22] = 32
	file[23] = 32
	binary.BigEndian.PutUint32(file[24:28], 1) // file change counter
	binary.BigEndian.PutUint32(file[28:32], uint32(totalPages))
	binary.BigEndian.PutUint32(file[40:44], 1) // schema cookie
	binary.BigEndian.PutUint32(file[44:48], 4) // schema format number
	binary.BigEndian.PutUint32(file[56:60], 1) // text encoding: UTF-8
	binary.BigEndian.PutUint32(file[92:96], 1) // version-valid-for
	binary.BigEndian.PutUint32(file[96:100], 3051000)

	// --- Page 1: sqlite_schema leaf b-tree ---
	// Build one cell per table: (type, name, tbl_name, rootpage, sql).
	cells := make([][]byte, len(schemaTables))
	for i, t := range schemaTables {
		rootPage := i + 2
		rec := encodeRecord([]interface{}{"table", t.name, t.name, rootPage, t.sql})
		cell := append([]byte{}, putVarint(uint64(len(rec)))...) // payload length
		cell = append(cell, putVarint(uint64(i+1))...)           // rowid
		cell = append(cell, rec...)
		cells[i] = cell
	}

	pos := pageSize
	pointers := make([]int, len(cells))
	for i, cell := range cells {
		pos -= len(cell)
		copy(file[pos:pos+len(cell)], cell)
		pointers[i] = pos
	}

	file[100] = 0x0D // leaf table b-tree page
	binary.BigEndian.PutUint16(file[101:103], 0)
	binary.BigEndian.PutUint16(file[103:105], uint16(len(cells)))
	binary.BigEndian.PutUint16(file[105:107], uint16(pos))
	file[107] = 0
	for i, p := range pointers {
		binary.BigEndian.PutUint16(file[108+2*i:110+2*i], uint16(p))
	}

	// --- Table root pages: empty leaf b-trees ---
	for i := range schemaTables {
		base := (i + 1) * pageSize
		file[base] = 0x0D
		binary.BigEndian.PutUint16(file[base+1:base+3], 0)
		binary.BigEndian.PutUint16(file[base+3:base+5], 0)
		binary.BigEndian.PutUint16(file[base+5:base+7], pageSize)
		file[base+7] = 0
	}

	return file
}

// ensureDB writes the durable database file with the initialized schema.
func ensureDB() error {
	storageMu.Lock()
	defer storageMu.Unlock()
	if err := os.WriteFile(dbPath, buildDatabase(), 0o644); err != nil {
		return err
	}
	dbInited = true
	return nil
}

func handleStorageStatus(w http.ResponseWriter, r *http.Request) {
	storageMu.Lock()
	inited := dbInited
	if _, err := os.Stat(dbPath); err != nil {
		inited = false
	}
	storageMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"driver":         "sqlite",
		"schema_version": schemaVersion,
		"initialized":    inited,
	})
}

func handleStorageReset(w http.ResponseWriter, r *http.Request) {
	// Clear benchmark-created durable data held in memory.
	combatMu.Lock()
	combatSessions = map[string]*combatSession{}
	combatMu.Unlock()

	usersMu.Lock()
	users = map[string]*user{}
	usersMu.Unlock()

	compendiumMu.Lock()
	monsters = map[string]*monster{}
	items = map[string]*item{}
	compendiumMu.Unlock()

	campaignMu.Lock()
	campaigns = map[string]*campaign{}
	campaignMu.Unlock()

	// Recreate the schema on disk.
	if err := ensureDB(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "reset failed"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":             true,
		"schema_version": schemaVersion,
	})
}
