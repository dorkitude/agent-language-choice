package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"sync"
)

// Durable storage.
//
// The in-memory stores (users, sessions, compendium, campaigns) stay
// authoritative for request handling; SQLite is a mirror. After every mutation a
// handler calls flush(), which re-renders the entire world as a fresh database
// file, and initStorage() loads that file back at startup. Whole-file rewrites
// keep the writer trivial and the on-disk state always internally consistent;
// they are affordable because the data set is small and bounded.
//
// Ordering rule: flush() acquires each store's lock in turn, so a handler must
// release its own lock before calling it.

const (
	storageDriver = "sqlite"
	schemaVersion = 1
	databaseFile  = "game.db"
)

// Table names, used both to declare the schema and to attach rows to it.
const (
	tableMeta        = "meta"
	tableUsers       = "users"
	tableSessions    = "combat_sessions"
	tableMonsters    = "monsters"
	tableItems       = "items"
	tableCampaigns   = "campaigns"
	tableCharacters  = "campaign_characters"
	tableEvents      = "campaign_events"
	tableQuests      = "campaign_quests"
	tableFactions    = "campaign_factions"
	tableNPCs        = "campaign_npcs"
	tableInventory   = "campaign_inventory"
	tableEquipment   = "campaign_equipment"
	tableCrafting    = "campaign_crafting"
	tableSchedule    = "campaign_sessions"
	tablePlay        = "play_campaigns"
	tablePlayMembers = "play_campaign_members"
	tablePlayEvents  = "play_campaign_events"
)

// schema is the full table list, in file order. Rows are filled in by snapshot.
//
// Lists that must round-trip in order (campaign rosters, event logs, and the
// campaign list itself) carry an explicit `position` column, because the reader
// walks rowids and rowid order is not part of the contract.
var schema = []sqliteTable{
	{Name: tableMeta, SQL: "CREATE TABLE meta(key TEXT, value TEXT)"},
	{Name: tableUsers, SQL: "CREATE TABLE users(username TEXT, role TEXT, password_hash TEXT)"},
	{Name: tableSessions, SQL: "CREATE TABLE combat_sessions(id TEXT, round INTEGER, turn_index INTEGER, initiative_order TEXT, conditions TEXT)"},
	{Name: tableMonsters, SQL: "CREATE TABLE monsters(slug TEXT, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER, tags TEXT)"},
	{Name: tableItems, SQL: "CREATE TABLE items(slug TEXT, name TEXT, type TEXT, rarity TEXT, cost_gp INTEGER)"},
	{Name: tableCampaigns, SQL: "CREATE TABLE campaigns(id TEXT, name TEXT, dm TEXT, position INTEGER)"},
	{Name: tableCharacters, SQL: "CREATE TABLE campaign_characters(campaign_id TEXT, id TEXT, name TEXT, level INTEGER, class TEXT, position INTEGER)"},
	{Name: tableEvents, SQL: "CREATE TABLE campaign_events(campaign_id TEXT, id TEXT, kind TEXT, summary TEXT, position INTEGER)"},
	{Name: tableQuests, SQL: "CREATE TABLE campaign_quests(campaign_id TEXT, id TEXT, title TEXT, status TEXT, milestones TEXT, milestones_done TEXT, position INTEGER)"},
	{Name: tableFactions, SQL: "CREATE TABLE campaign_factions(campaign_id TEXT, id TEXT, name TEXT, stance TEXT, position INTEGER)"},
	{Name: tableNPCs, SQL: "CREATE TABLE campaign_npcs(campaign_id TEXT, id TEXT, name TEXT, faction_id TEXT, disposition INTEGER, position INTEGER)"},
	{Name: tableInventory, SQL: "CREATE TABLE campaign_inventory(campaign_id TEXT, item_slug TEXT, quantity INTEGER, owner TEXT, position INTEGER)"},
	{Name: tableEquipment, SQL: "CREATE TABLE campaign_equipment(campaign_id TEXT, character_id TEXT, item_slug TEXT, quantity INTEGER, position INTEGER)"},
	{Name: tableCrafting, SQL: "CREATE TABLE campaign_crafting(campaign_id TEXT, id TEXT, character_id TEXT, item_slug TEXT, days_required INTEGER, days_completed INTEGER, cost_gp INTEGER, status TEXT, position INTEGER)"},
	{Name: tableSchedule, SQL: "CREATE TABLE campaign_sessions(campaign_id TEXT, id TEXT, starts_at TEXT, duration_minutes INTEGER, agenda TEXT, present TEXT, absent TEXT, position INTEGER)"},
	{Name: tablePlay, SQL: "CREATE TABLE play_campaigns(id TEXT, name TEXT, owner TEXT, status TEXT, max_players INTEGER, position INTEGER, current_actor TEXT, turn_number INTEGER)"},
	{Name: tablePlayMembers, SQL: "CREATE TABLE play_campaign_members(campaign_id TEXT, username TEXT, character_id TEXT, name TEXT, class TEXT, position INTEGER)"},
	{Name: tablePlayEvents, SQL: "CREATE TABLE play_campaign_events(campaign_id TEXT, sequence INTEGER, kind TEXT, actor TEXT, text TEXT, type TEXT)"},
}

type storage struct {
	mu          sync.Mutex
	path        string
	initialized bool
}

var db = &storage{path: databaseFile}

// ---------- snapshot / flush ----------

// snapshot renders the current in-memory world as populated schema tables. It
// takes each store's lock in turn, so callers must hold none of them.
func snapshot() []sqliteTable {
	rows := map[string][][]any{
		tableMeta: {
			{"schema_version", strconv.Itoa(schemaVersion)},
			{"driver", storageDriver},
		},
	}
	rows[tableUsers] = snapshotUsers()
	rows[tableSessions] = snapshotSessions()
	rows[tableMonsters], rows[tableItems] = snapshotCompendium()
	for name, campaignRows := range snapshotCampaigns() {
		rows[name] = campaignRows
	}
	rows[tablePlay], rows[tablePlayMembers], rows[tablePlayEvents] = snapshotPlayCampaigns()

	tables := make([]sqliteTable, len(schema))
	copy(tables, schema)
	for i := range tables {
		tables[i].Rows = rows[tables[i].Name]
	}
	return tables
}

// sortedKeys returns a map's keys in ascending order, so map iteration order
// never leaks into the database file.
func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func snapshotUsers() [][]any {
	users.mu.Lock()
	defer users.mu.Unlock()
	out := make([][]any, 0, len(users.users))
	for _, name := range sortedKeys(users.users) {
		u := users.users[name]
		out = append(out, []any{u.Username, u.Role, u.Hash.encoded()})
	}
	return out
}

func snapshotSessions() [][]any {
	sessions.mu.Lock()
	defer sessions.mu.Unlock()
	out := make([][]any, 0, len(sessions.sessions))
	for _, id := range sortedKeys(sessions.sessions) {
		s := sessions.sessions[id]
		// Nested structures are stored as JSON text: the writer only handles
		// flat TEXT/INTEGER columns.
		order, _ := json.Marshal(s.Order)
		conds, _ := json.Marshal(s.Conditions)
		out = append(out, []any{
			s.ID, int64(s.Round), int64(s.TurnIndex), string(order), string(conds),
		})
	}
	return out
}

func snapshotCompendium() (monsterRows, itemRows [][]any) {
	compendium.mu.Lock()
	defer compendium.mu.Unlock()

	monsterRows = make([][]any, 0, len(compendium.monsters))
	for _, slug := range sortedKeys(compendium.monsters) {
		m := compendium.monsters[slug]
		tags, _ := json.Marshal(m.Tags)
		monsterRows = append(monsterRows, []any{
			m.Slug, m.Name, m.CR, int64(m.ArmorClass), int64(m.HitPoints), string(tags),
		})
	}

	itemRows = make([][]any, 0, len(compendium.items))
	for _, slug := range sortedKeys(compendium.items) {
		it := compendium.items[slug]
		itemRows = append(itemRows, []any{it.Slug, it.Name, it.Type, it.Rarity, int64(it.CostGP)})
	}
	return monsterRows, itemRows
}

// snapshotPlayCampaigns renders the protected play surface's campaigns in
// creation order, plus their parties in join order and their event logs in
// sequence order.
func snapshotPlayCampaigns() (campaignRows, memberRows, eventRows [][]any) {
	playCampaigns.mu.Lock()
	defer playCampaigns.mu.Unlock()
	campaignRows = make([][]any, 0, len(playCampaigns.order))
	memberRows = [][]any{}
	eventRows = [][]any{}
	for i, id := range playCampaigns.order {
		c, ok := playCampaigns.campaigns[id]
		if !ok {
			continue
		}
		campaignRows = append(campaignRows, []any{
			c.ID, c.Name, c.Owner, c.Status, int64(c.MaxPlayers), int64(i),
			c.CurrentActor, int64(c.TurnNumber),
		})
		for j, m := range c.Members {
			memberRows = append(memberRows, []any{c.ID, m.Username, m.CharacterID, m.Name, m.Class, int64(j)})
		}
		for _, e := range c.Events {
			eventRows = append(eventRows, []any{c.ID, int64(e.Sequence), e.Kind, e.Actor, e.Text, e.Type})
		}
	}
	return campaignRows, memberRows, eventRows
}

// snapshotCampaigns renders every campaign-owned table, keyed by table name, so
// adding a new child collection does not change the function's signature.
func snapshotCampaigns() map[string][][]any {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()

	out := map[string][][]any{
		tableCampaigns:  make([][]any, 0, len(campaigns.order)),
		tableCharacters: {},
		tableEvents:     {},
		tableQuests:     {},
		tableFactions:   {},
		tableNPCs:       {},
		tableInventory:  {},
		tableEquipment:  {},
		tableCrafting:   {},
		tableSchedule:   {},
	}
	for i, id := range campaigns.order {
		c, ok := campaigns.campaigns[id]
		if !ok {
			continue
		}
		out[tableCampaigns] = append(out[tableCampaigns], []any{c.ID, c.Name, c.DM, int64(i)})
		for j, ch := range c.Characters {
			out[tableCharacters] = append(out[tableCharacters], []any{
				c.ID, ch.ID, ch.Name, int64(ch.Level), ch.Class, int64(j),
			})
		}
		for j, e := range c.Events {
			out[tableEvents] = append(out[tableEvents], []any{c.ID, e.ID, e.Kind, e.Summary, int64(j)})
		}
		out[tableQuests] = append(out[tableQuests], questRows(c)...)
		for j, f := range c.Factions {
			out[tableFactions] = append(out[tableFactions], []any{
				c.ID, f.ID, f.Name, f.Stance, int64(j),
			})
		}
		for j, n := range c.NPCs {
			out[tableNPCs] = append(out[tableNPCs], []any{
				c.ID, n.ID, n.Name, n.FactionID, int64(n.Disposition), int64(j),
			})
		}
		for j, it := range c.Inventory {
			out[tableInventory] = append(out[tableInventory], []any{
				c.ID, it.ItemSlug, int64(it.Quantity), it.Owner, int64(j),
			})
		}
		for j, e := range c.Equipment {
			out[tableEquipment] = append(out[tableEquipment], []any{
				c.ID, e.CharacterID, e.ItemSlug, int64(e.Quantity), int64(j),
			})
		}
		for j, p := range c.Crafting {
			out[tableCrafting] = append(out[tableCrafting], []any{
				c.ID, p.ID, p.CharacterID, p.ItemSlug, int64(p.DaysRequired),
				int64(p.DaysCompleted), int64(p.CostGP), p.Status, int64(j),
			})
		}
		out[tableSchedule] = append(out[tableSchedule], sessionRows(c)...)
	}
	return out
}

// flush rewrites the whole database file from the in-memory world. A failed
// write is logged and swallowed: durability is best-effort and must never turn a
// successful mutation into a failed request. Callers must hold no store lock.
func flush() {
	tables := snapshot()
	db.mu.Lock()
	defer db.mu.Unlock()
	if err := writeDatabase(db.path, tables); err != nil {
		log.Printf("storage flush failed: %v", err)
		return
	}
	db.initialized = true
}

// ---------- startup load ----------

// initStorage restores the persisted world, then flushes so the file exists and
// matches the schema even on a first run.
func initStorage() {
	loadFromDatabase()
	flush()
}

// loadFromDatabase repopulates the in-memory stores from the database file. A
// missing or unreadable file simply leaves an empty world. Individual rows that
// fail their invariants are skipped rather than aborting the load, so one bad
// row cannot make the service unstartable.
func loadFromDatabase() {
	r, err := openDatabase(db.path)
	if err != nil {
		return
	}
	loadUsers(r)
	loadSessions(r)
	loadCompendium(r)
	loadCampaigns(r)
	loadPlayCampaigns(r)
}

// loadPlayCampaigns restores the play surface's campaigns, re-sorting them by
// the persisted position column so creation order survives a restart.
func loadPlayCampaigns(r *sqliteReader) {
	rows, err := r.selectAll(tablePlay)
	if err != nil {
		return
	}
	type positioned struct {
		pos int64
		c   *playCampaign
	}
	list := make([]positioned, 0, len(rows))
	for _, row := range rows {
		if len(row) < 6 {
			continue
		}
		id, _ := row[0].(string)
		name, _ := row[1].(string)
		owner, _ := row[2].(string)
		status, _ := row[3].(string)
		maxPlayers, _ := row[4].(int64)
		pos, _ := row[5].(int64)
		if id == "" {
			continue
		}
		// The turn cursor columns were added after the first play rows were
		// written, so a shorter row is an older campaign that never started.
		var currentActor string
		var turnNumber int64
		if len(row) >= 8 {
			currentActor, _ = row[6].(string)
			turnNumber, _ = row[7].(int64)
		}
		list = append(list, positioned{pos: pos, c: &playCampaign{
			ID:           id,
			Name:         name,
			Owner:        owner,
			Status:       status,
			MaxPlayers:   int(maxPlayers),
			CurrentActor: currentActor,
			TurnNumber:   int(turnNumber),
		}})
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].pos < list[j].pos })

	playCampaigns.mu.Lock()
	defer playCampaigns.mu.Unlock()
	for _, p := range list {
		if _, exists := playCampaigns.campaigns[p.c.ID]; exists {
			continue
		}
		playCampaigns.add(p.c)
	}
	loadPlayMembers(r)
	loadPlayEvents(r)
}

// loadPlayEvents restores each play campaign's append-only log, re-sorting by
// the persisted sequence so the log's order survives a restart. Callers must
// hold playCampaigns.mu; rows naming an unknown campaign are dropped.
func loadPlayEvents(r *sqliteReader) {
	rows, err := r.selectAll(tablePlayEvents)
	if err != nil {
		return
	}
	type positioned struct {
		campaignID string
		e          *playEvent
	}
	list := make([]positioned, 0, len(rows))
	for _, row := range rows {
		if len(row) < 5 {
			continue
		}
		campaignID, _ := row[0].(string)
		sequence, _ := row[1].(int64)
		kind, _ := row[2].(string)
		actorName, _ := row[3].(string)
		text, _ := row[4].(string)
		if campaignID == "" || sequence < 1 {
			continue
		}
		// The type column was added with player actions, so a shorter row is an
		// older event — a narration — that never carried one.
		var eventType string
		if len(row) >= 6 {
			eventType, _ = row[5].(string)
		}
		list = append(list, positioned{campaignID: campaignID, e: &playEvent{
			Sequence: int(sequence),
			Kind:     kind,
			Actor:    actorName,
			Type:     eventType,
			Text:     text,
		}})
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].e.Sequence < list[j].e.Sequence })

	for _, p := range list {
		c, ok := playCampaigns.campaigns[p.campaignID]
		if !ok {
			continue
		}
		c.Events = append(c.Events, p.e)
	}
}

// loadPlayMembers restores each play campaign's party, re-sorting by the
// persisted position column so join order survives a restart. Callers must hold
// playCampaigns.mu; rows naming an unknown campaign are dropped.
func loadPlayMembers(r *sqliteReader) {
	rows, err := r.selectAll(tablePlayMembers)
	if err != nil {
		return
	}
	type positioned struct {
		campaignID string
		pos        int64
		m          *playMember
	}
	list := make([]positioned, 0, len(rows))
	for _, row := range rows {
		if len(row) < 6 {
			continue
		}
		campaignID, _ := row[0].(string)
		username, _ := row[1].(string)
		characterID, _ := row[2].(string)
		name, _ := row[3].(string)
		class, _ := row[4].(string)
		pos, _ := row[5].(int64)
		if campaignID == "" || username == "" || characterID == "" {
			continue
		}
		list = append(list, positioned{campaignID: campaignID, pos: pos, m: &playMember{
			Username:    username,
			CharacterID: characterID,
			Name:        name,
			Class:       class,
		}})
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].pos < list[j].pos })

	for _, p := range list {
		c, ok := playCampaigns.campaigns[p.campaignID]
		if !ok {
			continue
		}
		if c.member(p.m.Username) != nil || c.memberByCharacter(p.m.CharacterID) != nil {
			continue
		}
		c.Members = append(c.Members, p.m)
	}
}

func loadUsers(r *sqliteReader) {
	rows, err := r.selectAll(tableUsers)
	if err != nil {
		return
	}
	users.mu.Lock()
	defer users.mu.Unlock()
	for _, row := range rows {
		if len(row) < 3 {
			continue
		}
		username, _ := row[0].(string)
		role, _ := row[1].(string)
		encoded, _ := row[2].(string)
		h, ok := parsePasswordHash(encoded)
		if !ok || username == "" {
			continue
		}
		users.users[username] = &user{Username: username, Role: role, Hash: h}
	}
}

func loadSessions(r *sqliteReader) {
	rows, err := r.selectAll(tableSessions)
	if err != nil {
		return
	}
	sessions.mu.Lock()
	defer sessions.mu.Unlock()
	for _, row := range rows {
		if len(row) < 5 {
			continue
		}
		id, _ := row[0].(string)
		round, _ := row[1].(int64)
		turn, _ := row[2].(int64)
		orderJSON, _ := row[3].(string)
		condJSON, _ := row[4].(string)

		var order []initiativeEntry
		if err := json.Unmarshal([]byte(orderJSON), &order); err != nil || len(order) == 0 {
			continue
		}
		conds := map[string][]conditionState{}
		_ = json.Unmarshal([]byte(condJSON), &conds)
		// Enforce combatSession's invariant: TurnIndex must index Order.
		if id == "" || int(turn) < 0 || int(turn) >= len(order) {
			continue
		}
		sessions.sessions[id] = &combatSession{
			ID:         id,
			Round:      int(round),
			TurnIndex:  int(turn),
			Order:      order,
			Conditions: conds,
		}
	}
}

func loadCompendium(r *sqliteReader) {
	if rows, err := r.selectAll(tableMonsters); err == nil {
		compendium.mu.Lock()
		for _, row := range rows {
			if len(row) < 6 {
				continue
			}
			slug, _ := row[0].(string)
			name, _ := row[1].(string)
			cr, _ := row[2].(string)
			ac, _ := row[3].(int64)
			hp, _ := row[4].(int64)
			tagsJSON, _ := row[5].(string)
			if slug == "" {
				continue
			}
			// Tags must stay a JSON array, never null, in responses.
			tags := []string{}
			_ = json.Unmarshal([]byte(tagsJSON), &tags)
			compendium.monsters[slug] = &monsterEntry{
				Slug:       slug,
				Name:       name,
				CR:         cr,
				ArmorClass: int(ac),
				HitPoints:  int(hp),
				Tags:       tags,
			}
		}
		compendium.mu.Unlock()
	}

	if rows, err := r.selectAll(tableItems); err == nil {
		compendium.mu.Lock()
		for _, row := range rows {
			if len(row) < 5 {
				continue
			}
			slug, _ := row[0].(string)
			name, _ := row[1].(string)
			typ, _ := row[2].(string)
			rarity, _ := row[3].(string)
			cost, _ := row[4].(int64)
			if slug == "" {
				continue
			}
			compendium.items[slug] = &itemEntry{
				Slug: slug, Name: name, Type: typ, Rarity: rarity, CostGP: int(cost),
			}
		}
		compendium.mu.Unlock()
	}
}

// loadCampaigns restores campaigns plus their rosters and session logs,
// re-sorting each list by its persisted position column. Children are collected
// as deferred appends so every list can be sorted before anything is attached,
// which keeps roster and log order stable across a save/load cycle.
func loadCampaigns(r *sqliteReader) {
	rows, err := r.selectAll(tableCampaigns)
	if err != nil {
		return
	}

	type positioned struct {
		pos int64
		c   *campaign
	}
	list := make([]positioned, 0, len(rows))
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	for _, row := range rows {
		if len(row) < 4 {
			continue
		}
		id, _ := row[0].(string)
		name, _ := row[1].(string)
		dm, _ := row[2].(string)
		pos, _ := row[3].(int64)
		if id == "" {
			continue
		}
		list = append(list, positioned{pos: pos, c: &campaign{
			ID:         id,
			Name:       name,
			DM:         dm,
			Characters: []*campaignCharacter{},
			Events:     []*campaignEvent{},
			Quests:     []*quest{},
			Factions:   []*faction{},
			NPCs:       []*npc{},
			Inventory:  []*inventoryItem{},
			Equipment:  []*equipmentAssignment{},
			Crafting:   []*craftingProject{},
			Sessions:   []*campaignSession{},
		}})
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].pos < list[j].pos })
	for _, p := range list {
		campaigns.add(p.c)
	}

	type deferredAppend struct {
		pos int64
		add func()
	}
	pending := []deferredAppend{}

	if rows, err := r.selectAll(tableCharacters); err == nil {
		for _, row := range rows {
			if len(row) < 6 {
				continue
			}
			campaignID, _ := row[0].(string)
			id, _ := row[1].(string)
			name, _ := row[2].(string)
			level, _ := row[3].(int64)
			class, _ := row[4].(string)
			pos, _ := row[5].(int64)
			c, ok := campaigns.campaigns[campaignID]
			if !ok || id == "" {
				continue
			}
			entry := &campaignCharacter{ID: id, Name: name, Level: int(level), Class: class}
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Characters = append(c.Characters, entry)
			}})
		}
	}

	if rows, err := r.selectAll(tableEvents); err == nil {
		for _, row := range rows {
			if len(row) < 5 {
				continue
			}
			campaignID, _ := row[0].(string)
			id, _ := row[1].(string)
			kind, _ := row[2].(string)
			summary, _ := row[3].(string)
			pos, _ := row[4].(int64)
			c, ok := campaigns.campaigns[campaignID]
			if !ok || id == "" {
				continue
			}
			entry := &campaignEvent{ID: id, Kind: kind, Summary: summary}
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Events = append(c.Events, entry)
			}})
		}
	}

	if rows, err := r.selectAll(tableQuests); err == nil {
		for _, row := range rows {
			campaignID, q, ok := questFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos := int64(0)
			if len(row) >= 7 {
				pos, _ = row[6].(int64)
			}
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Quests = append(c.Quests, q)
			}})
		}
	}

	if rows, err := r.selectAll(tableFactions); err == nil {
		for _, row := range rows {
			campaignID, f, ok := factionFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos, _ := row[4].(int64)
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Factions = append(c.Factions, f)
			}})
		}
	}

	if rows, err := r.selectAll(tableNPCs); err == nil {
		for _, row := range rows {
			campaignID, n, ok := npcFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos := int64(0)
			if len(row) >= 6 {
				pos, _ = row[5].(int64)
			}
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.NPCs = append(c.NPCs, n)
			}})
		}
	}

	if rows, err := r.selectAll(tableInventory); err == nil {
		for _, row := range rows {
			campaignID, it, ok := inventoryFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos, _ := row[4].(int64)
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Inventory = append(c.Inventory, it)
			}})
		}
	}

	if rows, err := r.selectAll(tableEquipment); err == nil {
		for _, row := range rows {
			campaignID, e, ok := equipmentFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos, _ := row[4].(int64)
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Equipment = append(c.Equipment, e)
			}})
		}
	}

	if rows, err := r.selectAll(tableCrafting); err == nil {
		for _, row := range rows {
			campaignID, p, ok := craftingFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos, _ := row[8].(int64)
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Crafting = append(c.Crafting, p)
			}})
		}
	}

	if rows, err := r.selectAll(tableSchedule); err == nil {
		for _, row := range rows {
			campaignID, s, ok := sessionFromRow(row)
			if !ok {
				continue
			}
			c, found := campaigns.campaigns[campaignID]
			if !found {
				continue
			}
			pos, _ := row[7].(int64)
			pending = append(pending, deferredAppend{pos: pos, add: func() {
				c.Sessions = append(c.Sessions, s)
			}})
		}
	}

	sort.SliceStable(pending, func(i, j int) bool { return pending[i].pos < pending[j].pos })
	for _, p := range pending {
		p.add()
	}
}

// ---------- GET /v1/storage/status ----------

type storageStatusResponse struct {
	Driver        string `json:"driver"`
	SchemaVersion int    `json:"schema_version"`
	Initialized   bool   `json:"initialized"`
}

func handleStorageStatus(w http.ResponseWriter, r *http.Request) {
	if !requireGet(w, r) {
		return
	}
	db.mu.Lock()
	initialized := db.initialized
	db.mu.Unlock()
	writeJSON(w, http.StatusOK, storageStatusResponse{
		Driver:        storageDriver,
		SchemaVersion: schemaVersion,
		Initialized:   initialized,
	})
}

// ---------- POST /v1/storage/reset ----------

type storageResetResponse struct {
	OK            bool `json:"ok"`
	SchemaVersion int  `json:"schema_version"`
}

// handleStorageReset empties every store and recreates an empty database. Test
// suites use it to isolate runs, so it must leave storage usable, not merely
// blank.
func handleStorageReset(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}

	users.mu.Lock()
	users.users = map[string]*user{}
	users.mu.Unlock()

	sessions.mu.Lock()
	sessions.sessions = map[string]*combatSession{}
	sessions.mu.Unlock()

	compendium.mu.Lock()
	compendium.monsters = map[string]*monsterEntry{}
	compendium.items = map[string]*itemEntry{}
	compendium.mu.Unlock()

	campaigns.mu.Lock()
	campaigns.campaigns = map[string]*campaign{}
	campaigns.order = nil
	campaigns.mu.Unlock()

	playCampaigns.mu.Lock()
	playCampaigns.campaigns = map[string]*playCampaign{}
	playCampaigns.order = nil
	playCampaigns.mu.Unlock()

	db.mu.Lock()
	_ = os.Remove(db.path)
	db.initialized = false
	db.mu.Unlock()

	// Recreate the schema over the now-empty world; this is what flips
	// initialized back to true.
	flush()

	db.mu.Lock()
	initialized := db.initialized
	db.mu.Unlock()
	if !initialized {
		writeError(w, http.StatusInternalServerError, "could not recreate storage")
		return
	}

	writeJSON(w, http.StatusOK, storageResetResponse{OK: true, SchemaVersion: schemaVersion})
}
