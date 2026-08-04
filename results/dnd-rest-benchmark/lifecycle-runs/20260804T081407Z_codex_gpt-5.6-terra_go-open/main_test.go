package main

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestPlayCampaignStatusMigration(t *testing.T) {
	path := filepath.Join(t.TempDir(), "game.db")
	legacy, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	for _, statement := range []string{
		`PRAGMA foreign_keys = ON`,
		`CREATE TABLE play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('lobby')), max_players INTEGER NOT NULL CHECK(max_players > 0))`,
		`CREATE TABLE play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY(campaign_id, username), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`INSERT INTO play_campaigns VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`,
		`INSERT INTO play_campaign_members VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue')`,
	} {
		if _, err := legacy.Exec(statement); err != nil {
			legacy.Close()
			t.Fatal(err)
		}
	}
	if err := legacy.Close(); err != nil {
		t.Fatal(err)
	}
	if err := initializeStorage(path); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if _, err := currentDB().Exec(`UPDATE play_campaigns SET status = 'active' WHERE id = 'play-1'`); err != nil {
		t.Fatalf("legacy campaign was not migrated: %v", err)
	}
}

func TestPlayCampaignCharacterDeathSaves(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'play-char-a', 'Aria', 'rogue', 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(handler http.HandlerFunc, method, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, "/v1/play/campaigns/play-1/characters/play-char-a", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("char_id", "play-char-a")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		handler(response, req)
		return response
	}
	if response := request(recordPlayCampaignDeathSave, http.MethodPost, "Bearer session-player-a", `{"outcome":"success"}`); response.Code != http.StatusConflict {
		t.Fatalf("conscious roll = %d", response.Code)
	}
	if response := request(damagePlayCampaignCharacter, http.MethodPost, "Bearer session-dm", `{"amount":20}`); response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"target":"play-char-a"`) {
		t.Fatalf("damage = %d: %s", response.Code, response.Body.String())
	}
	if response := request(recordPlayCampaignDeathSave, http.MethodPost, "Bearer session-player-b", `{"outcome":"success"}`); response.Code != http.StatusForbidden {
		t.Fatalf("non-owner roll = %d", response.Code)
	}
	for successes := 1; successes <= 3; successes++ {
		response := request(recordPlayCampaignDeathSave, http.MethodPost, "Bearer session-player-a", `{"outcome":"success"}`)
		if response.Code != http.StatusCreated {
			t.Fatalf("success %d = %d: %s", successes, response.Code, response.Body.String())
		}
	}
	if response := request(recordPlayCampaignDeathSave, http.MethodPost, "Bearer session-player-a", `{"outcome":"success"}`); response.Code != http.StatusConflict {
		t.Fatalf("stable roll = %d", response.Code)
	}
	response := request(getPlayCampaignCharacterStatus, http.MethodGet, "Bearer session-player-a", "")
	if response.Code != http.StatusOK || response.Body.String() != `{"character_id":"play-char-a","hp_current":0,"hp_max":20,"status":"stable"}`+"\n" {
		t.Fatalf("status = %d: %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignCharacterOwnership(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, character_owner) VALUES ('play-1', 'player-a', 'play-char-a', 'Aria', 'rogue', '')`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, character_owner) VALUES ('play-1', 'player-b', 'play-char-b', 'Borin', 'fighter', 'player-b')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(handler http.HandlerFunc, method, token, path, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("char_id", "play-char-a")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		handler(response, req)
		return response
	}
	if response := request(claimPlayCampaignCharacter, http.MethodPost, "Bearer session-player-a", "/claim", ""); response.Code != http.StatusCreated || response.Body.String() != `{"character_id":"play-char-a","owner":"player-a"}`+"\n" {
		t.Fatalf("claim = %d: %s", response.Code, response.Body.String())
	}
	if response := request(getPlayCampaignCharacterOwner, http.MethodGet, "Bearer session-player-b", "/owner", ""); response.Code != http.StatusOK || response.Body.String() != `{"character_id":"play-char-a","owner":"player-a"}`+"\n" {
		t.Fatalf("owner = %d: %s", response.Code, response.Body.String())
	}
	if response := request(claimPlayCampaignCharacter, http.MethodPost, "Bearer session-player-b", "/claim", ""); response.Code != http.StatusConflict {
		t.Fatalf("other claim = %d", response.Code)
	}
	if response := request(transferPlayCampaignCharacter, http.MethodPost, "Bearer session-player-b", "/transfer", `{"new_owner":"player-b"}`); response.Code != http.StatusForbidden {
		t.Fatalf("non-owner transfer = %d", response.Code)
	}
	if response := request(transferPlayCampaignCharacter, http.MethodPost, "Bearer session-player-a", "/transfer", `{"new_owner":"player-b"}`); response.Code != http.StatusOK || response.Body.String() != `{"character_id":"play-char-a","owner":"player-b"}`+"\n" {
		t.Fatalf("transfer = %d: %s", response.Code, response.Body.String())
	}
}

func TestBuildPlayCampaignCharacter(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if _, err := currentDB().Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`); err != nil {
		t.Fatal(err)
	}
	if _, err := currentDB().Exec(`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, character_owner) VALUES ('play-1', 'player-a', 'play-char-a', 'Aria', 'rogue', 'player-a')`); err != nil {
		t.Fatal(err)
	}
	request := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/characters/play-char-a/build", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("char_id", "play-char-a")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		buildPlayCampaignCharacter(response, req)
		return response
	}
	body := `{"race":"elf","class":"rogue","background":"criminal","abilities":{"str":8,"dex":16,"con":12,"int":13,"wis":10,"cha":14}}`
	response := request("Bearer session-player-a", body)
	want := `{"character_id":"play-char-a","race":"elf","class":"rogue","background":"criminal","level":1,"hp_max":9,"proficiency_bonus":2}` + "\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("build = %d: %s", response.Code, response.Body.String())
	}
	if response := request("Bearer session-player-b", body); response.Code != http.StatusForbidden {
		t.Fatalf("non-owner build = %d", response.Code)
	}
	if response := request("Bearer session-player-a", `{"race":"elf","class":"rogue","background":"criminal","abilities":{"str":0,"dex":16,"con":12,"int":13,"wis":10,"cha":14}}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid ability build = %d", response.Code)
	}
	levelUpRequest := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/characters/play-char-a/level-up", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("char_id", "play-char-a")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		levelUpPlayCampaignCharacter(response, req)
		return response
	}
	response = levelUpRequest("Bearer session-player-a", `{"level":2}`)
	want = `{"character_id":"play-char-a","level":2,"hp_max":15,"hit_dice":"1d8","proficiency_bonus":2}` + "\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("level up = %d: %s", response.Code, response.Body.String())
	}
	if response := levelUpRequest("Bearer session-player-a", `{"level":2}`); response.Code != http.StatusBadRequest {
		t.Fatalf("repeated level up = %d", response.Code)
	}
	if response := levelUpRequest("Bearer session-player-b", `{"level":3}`); response.Code != http.StatusForbidden {
		t.Fatalf("non-owner level up = %d", response.Code)
	}
	if response := levelUpRequest("Bearer session-player-a", `{}`); response.Code != http.StatusBadRequest {
		t.Fatalf("missing level = %d", response.Code)
	}
}

func TestPlayCampaignCharacterSkillCheck(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, character_owner, level, dexterity) VALUES ('play-1', 'player-a', 'play-char-a', 'Aria', 'rogue', 'player-a', 1, 16)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/characters/play-char-a/skill-check", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("char_id", "play-char-a")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		skillCheckPlayCampaignCharacter(response, req)
		return response
	}
	response := request("Bearer session-player-a", `{"skill":"stealth","ability":"dex","proficient":true,"roll":15}`)
	want := `{"character_id":"play-char-a","skill":"stealth","ability":"dex","modifier":5,"total":20}` + "\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("skill check = %d: %s", response.Code, response.Body.String())
	}
	if response := request("Bearer session-player-b", `{"skill":"stealth","ability":"dex","proficient":false,"roll":15}`); response.Code != http.StatusForbidden {
		t.Fatalf("non-owner skill check = %d", response.Code)
	}
	if response := request("Bearer session-player-a", `{"skill":"flying","ability":"dex","proficient":false,"roll":15}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid skill = %d", response.Code)
	}
}

func call(handler http.HandlerFunc, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	response := httptest.NewRecorder()
	handler(response, req)
	return response
}

func TestSQLiteStorageRoundTrip(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	account := user{Username: "bard", Role: "player", PasswordHash: []byte("hash"), PasswordSalt: []byte("salt")}
	if err := persistUser(account); err != nil {
		t.Fatal(err)
	}
	session := &combatSession{ID: "sqlite-session", Round: 2, TurnIndex: 1, Order: []combatant{{Name: "bard", Score: 15, dex: 2}}, Conditions: map[string][]condition{"bard": {{Condition: "blessed", RemainingRounds: 1}}}}
	if err := persistSession(session); err != nil {
		t.Fatal(err)
	}
	users.Lock()
	users.users = make(map[string]user)
	users.Unlock()
	sessions.Lock()
	sessions.sessions = make(map[string]*combatSession)
	sessions.Unlock()
	if err := loadDurableData(); err != nil {
		t.Fatal(err)
	}
	users.Lock()
	_, userLoaded := users.users["bard"]
	users.Unlock()
	sessions.Lock()
	loaded := sessions.sessions["sqlite-session"]
	sessions.Unlock()
	if !userLoaded || loaded == nil || loaded.Round != 2 || loaded.Conditions["bard"][0].Condition != "blessed" {
		t.Fatal("durable data was not restored")
	}
}

func TestCreatePlayCampaignEncounterPausesExploration(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'player-a')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		createPlayCampaignEncounter(response, req)
		return response
	}
	if response := request("Bearer session-player-a", `{"id":"enc-road","name":"Road Ambush"}`); response.Code != http.StatusForbidden {
		t.Fatalf("player received %d", response.Code)
	}
	response := request("Bearer session-dm", `{"id":"enc-road","name":"Road Ambush"}`)
	want := "{\"id\":\"enc-road\",\"name\":\"Road Ambush\",\"status\":\"active\",\"combatants\":[]}\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected encounter: %d %s", response.Code, response.Body.String())
	}
	if response := request("Bearer session-dm", `{"id":"enc-other","name":"Second Fight"}`); response.Code != http.StatusConflict {
		t.Fatalf("combat campaign received %d", response.Code)
	}
	var status, actor string
	if err := db.QueryRow(`SELECT status FROM play_campaigns WHERE id = 'play-1'`).Scan(&status); err != nil || status != "combat" {
		t.Fatalf("campaign status = %q, %v", status, err)
	}
	if err := db.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = 'play-1'`).Scan(&actor); err != nil || actor != "player-a" {
		t.Fatalf("exploration turn = %q, %v", actor, err)
	}
}

func TestPlayCampaignEncounterMonsterRoster(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	add := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/monsters", strings.NewReader(`{"monster_id":"goblin-1","name":"Goblin","hp_max":7,"initiative":15}`))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("enc_id", "enc-road")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		addPlayCampaignEncounterMonster(response, req)
		return response
	}
	if response := add("Bearer session-player-a"); response.Code != http.StatusForbidden {
		t.Fatalf("player received %d", response.Code)
	}
	response := add("Bearer session-dm")
	want := `{"monster_id":"goblin-1","name":"Goblin","hp_max":7,"initiative":15,"hp_current":7}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected monster: %d %s", response.Code, response.Body.String())
	}
	if response := add("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("duplicate monster received %d", response.Code)
	}
	req := httptest.NewRequest(http.MethodDelete, "/v1/play/campaigns/play-1/encounters/enc-road/monsters/goblin-1", nil)
	req.SetPathValue("id", "play-1")
	req.SetPathValue("enc_id", "enc-road")
	req.SetPathValue("monster_id", "goblin-1")
	req.Header.Set("Authorization", "Bearer session-dm")
	response = httptest.NewRecorder()
	removePlayCampaignEncounterMonster(response, req)
	if response.Code != http.StatusOK || response.Body.String() != `{"removed":"goblin-1"}`+"\n" {
		t.Fatalf("unexpected removal: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignEncounterDamageAndHealing(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
		`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('play-1', 'enc-road', 'goblin-1', 'Goblin', 7, 7, 15)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(handler http.HandlerFunc, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/damage", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("enc_id", "enc-road")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		handler(response, req)
		return response
	}
	if response := request(damagePlayCampaignEncounterCombatant, "Bearer session-player-a", `{"target":"goblin-1","amount":5}`); response.Code != http.StatusForbidden {
		t.Fatalf("player received %d", response.Code)
	}
	if response := request(damagePlayCampaignEncounterCombatant, "Bearer session-dm", `{"target":"goblin-1","amount":5}`); response.Code != http.StatusOK || response.Body.String() != `{"target":"goblin-1","hp_before":7,"hp_after":2,"damage":5}`+"\n" {
		t.Fatalf("unexpected damage: %d %s", response.Code, response.Body.String())
	}
	if response := request(healPlayCampaignEncounterCombatant, "Bearer session-dm", `{"target":"goblin-1","amount":10}`); response.Code != http.StatusOK || response.Body.String() != `{"target":"goblin-1","hp_before":2,"hp_after":7,"healing":10}`+"\n" {
		t.Fatalf("unexpected healing: %d %s", response.Code, response.Body.String())
	}
	if response := request(damagePlayCampaignEncounterCombatant, "Bearer session-dm", `{"target":"goblin-1","amount":20}`); response.Code != http.StatusOK || response.Body.String() != `{"target":"goblin-1","hp_before":7,"hp_after":0,"damage":20}`+"\n" {
		t.Fatalf("unexpected capped damage: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignEncounterRewardsAndClose(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(path, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	path := "/v1/play/campaigns/play-1/encounters/enc-road/"
	if response := request(path+"rewards", "Bearer session-player-a", `{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}`); response.Code != http.StatusForbidden {
		t.Fatalf("player rewards = %d", response.Code)
	}
	wantReward := `{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}` + "\n"
	if response := request(path+"rewards", "Bearer session-dm", `{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}`); response.Code != http.StatusOK || response.Body.String() != wantReward {
		t.Fatalf("rewards = %d: %s", response.Code, response.Body.String())
	}
	if response := request(path+"rewards", "Bearer session-dm", `{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}`); response.Code != http.StatusConflict {
		t.Fatalf("duplicate rewards = %d", response.Code)
	}
	if response := request(path+"close", "Bearer session-dm", ""); response.Code != http.StatusOK || response.Body.String() != `{"id":"enc-road","status":"closed","xp_awarded":150}`+"\n" {
		t.Fatalf("close = %d: %s", response.Code, response.Body.String())
	}
}

func TestEndPlayCampaignEncounterResumesExploration(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'dm')`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/end", nil)
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	if response := request("Bearer session-player-a"); response.Code != http.StatusForbidden {
		t.Fatalf("player end = %d", response.Code)
	}
	if response := request("Bearer session-dm"); response.Code != http.StatusOK || response.Body.String() != `{"campaign_id":"play-1","status":"active","phase":"exploration","current_actor":"dm"}`+"\n" {
		t.Fatalf("end = %d: %s", response.Code, response.Body.String())
	}
	if response := request("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("end outside combat = %d", response.Code)
	}
}

func TestEndPlayCampaignEncounterAfterCloseResumesExploration(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'player-a')`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(suffix string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/"+suffix, nil)
		req.Header.Set("Authorization", "Bearer session-dm")
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	if response := request("close"); response.Code != http.StatusOK {
		t.Fatalf("close = %d: %s", response.Code, response.Body.String())
	}
	if response := request("end"); response.Code != http.StatusOK || response.Body.String() != `{"campaign_id":"play-1","status":"active","phase":"exploration","current_actor":"player-a"}`+"\n" {
		t.Fatalf("end = %d: %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignEncounterPartyCombatantBinding(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'play-char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	bind := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/combatants", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("enc_id", "enc-road")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		addPlayCampaignEncounterCombatant(response, req)
		return response
	}
	if response := bind("Bearer session-player-a", `{"member":"player-a","initiative":14}`); response.Code != http.StatusForbidden {
		t.Fatalf("player received %d", response.Code)
	}
	response := bind("Bearer session-dm", `{"member":"player-a","initiative":14}`)
	want := `{"member":"player-a","character_id":"play-char-a","name":"Aria","initiative":14}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected combatant: %d %s", response.Code, response.Body.String())
	}
	if response := bind("Bearer session-dm", `{"member":"player-a","initiative":14}`); response.Code != http.StatusConflict {
		t.Fatalf("duplicate member received %d", response.Code)
	}
	if response := bind("Bearer session-dm", `{"member":"player-b","initiative":14}`); response.Code != http.StatusBadRequest {
		t.Fatalf("missing member received %d", response.Code)
	}
	req := httptest.NewRequest(http.MethodDelete, "/v1/play/campaigns/play-1/encounters/enc-road/combatants/player-a", nil)
	req.SetPathValue("id", "play-1")
	req.SetPathValue("enc_id", "enc-road")
	req.SetPathValue("member", "player-a")
	req.Header.Set("Authorization", "Bearer session-dm")
	response = httptest.NewRecorder()
	removePlayCampaignEncounterCombatant(response, req)
	if response.Code != http.StatusOK || response.Body.String() != `{"removed":"player-a"}`+"\n" {
		t.Fatalf("unexpected removal: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignEncounterTurnAuthority(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Borin', 'fighter', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
		`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('play-1', 'enc-road', 'goblin-1', 'Goblin', 7, 7, 15)`,
		`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('play-1', 'enc-road', 'player-a', 'char-a', 'Aria', 14)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(method, token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, "/v1/play/campaigns/play-1/encounters/enc-road/turn", nil)
		if method == http.MethodPost {
			req = httptest.NewRequest(method, "/v1/play/campaigns/play-1/encounters/enc-road/turn/advance", nil)
		}
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	if response := request(http.MethodGet, "Bearer session-player-b"); response.Code != http.StatusOK || response.Body.String() != `{"round":1,"turn_index":0,"active":{"name":"Goblin","kind":"monster","initiative":15}}`+"\n" {
		t.Fatalf("unexpected turn: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodPost, "Bearer session-player-a"); response.Code != http.StatusConflict {
		t.Fatalf("out-of-turn player received %d", response.Code)
	}
	if response := request(http.MethodPost, "Bearer session-dm"); response.Code != http.StatusOK || response.Body.String() != `{"round":1,"turn_index":1,"active":{"name":"Aria","kind":"player","initiative":14}}`+"\n" {
		t.Fatalf("unexpected owner advance: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodPost, "Bearer session-player-a"); response.Code != http.StatusOK || response.Body.String() != `{"round":2,"turn_index":0,"active":{"name":"Goblin","kind":"monster","initiative":15}}`+"\n" {
		t.Fatalf("unexpected player advance: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignEncounterDelayAndReady(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 3)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Borin', 'fighter', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status, turn_index) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active', 1)`,
		`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('play-1', 'enc-road', 'goblin-1', 'Goblin', 7, 7, 15)`,
		`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('play-1', 'enc-road', 'player-a', 'char-a', 'Aria', 14)`,
		`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('play-1', 'enc-road', 'player-b', 'char-b', 'Borin', 12)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(path, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	ready := request("/v1/play/campaigns/play-1/encounters/enc-road/turn/ready", "Bearer session-player-a", `{"trigger":"when the goblin moves"}`)
	if ready.Code != http.StatusCreated || ready.Body.String() != `{"actor":"player-a","trigger":"when the goblin moves"}`+"\n" {
		t.Fatalf("ready = %d: %s", ready.Code, ready.Body.String())
	}
	var before int
	if err := db.QueryRow(`SELECT turn_index FROM play_campaign_encounters WHERE campaign_id = 'play-1' AND id = 'enc-road'`).Scan(&before); err != nil || before != 1 {
		t.Fatalf("ready changed turn index to %d: %v", before, err)
	}
	if response := request("/v1/play/campaigns/play-1/encounters/enc-road/turn/ready", "Bearer session-dm", `{"trigger":"when the goblin moves"}`); response.Code != http.StatusConflict {
		t.Fatalf("owner ready = %d", response.Code)
	}
	delay := request("/v1/play/campaigns/play-1/encounters/enc-road/turn/delay", "Bearer session-player-a", `{"new_index":2}`)
	want := `{"order":[{"name":"Goblin","kind":"monster","initiative":15},{"name":"Borin","kind":"player","initiative":12},{"name":"Aria","kind":"player","initiative":14}]}` + "\n"
	if delay.Code != http.StatusOK || delay.Body.String() != want {
		t.Fatalf("delay = %d: %s", delay.Code, delay.Body.String())
	}
	readyAfterDelay := request("/v1/play/campaigns/play-1/encounters/enc-road/turn/ready", "Bearer session-player-a", `{"trigger":"when the goblin moves"}`)
	if readyAfterDelay.Code != http.StatusCreated || readyAfterDelay.Body.String() != `{"actor":"player-a","trigger":"when the goblin moves"}`+"\n" {
		t.Fatalf("ready after delay = %d: %s", readyAfterDelay.Code, readyAfterDelay.Body.String())
	}
	if response := request("/v1/play/campaigns/play-1/encounters/enc-road/turn/delay", "Bearer session-dm", `{"to_index":1}`); response.Code != http.StatusBadRequest {
		t.Fatalf("illegal delay = %d", response.Code)
	}
	turn := httptest.NewRecorder()
	get := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/encounters/enc-road/turn", nil)
	get.Header.Set("Authorization", "Bearer session-player-b")
	router.ServeHTTP(turn, get)
	if turn.Code != http.StatusOK || !strings.Contains(turn.Body.String(), `"name":"Aria"`) {
		t.Fatalf("delayed turn = %d: %s", turn.Code, turn.Body.String())
	}
}

func TestPlayCampaignEncounterConditionsExpireAtTargetTurnStart(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active')`,
		`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('play-1', 'enc-road', 'goblin-1', 'Goblin', 7, 7, 15)`,
		`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('play-1', 'enc-road', 'player-a', 'char-a', 'Aria', 14)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(method, path, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/conditions", "Bearer session-player-a", `{"target":"goblin-1","condition":"blinded","duration_rounds":2}`); response.Code != http.StatusForbidden {
		t.Fatalf("player condition = %d", response.Code)
	}
	response := request(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/conditions", "Bearer session-dm", `{"target":"goblin-1","condition":"blinded","duration_rounds":2}`)
	if response.Code != http.StatusCreated || response.Body.String() != `{"target":"goblin-1","conditions":[{"condition":"blinded","remaining_rounds":2}]}`+"\n" {
		t.Fatalf("condition = %d: %s", response.Code, response.Body.String())
	}
	response = request(http.MethodGet, "/v1/play/campaigns/play-1/encounters/enc-road/status", "Bearer session-player-a", "")
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"conditions":{"goblin-1":[{"condition":"blinded","remaining_rounds":2}]}`) {
		t.Fatalf("status = %d: %s", response.Code, response.Body.String())
	}
	// Goblin is initially active. Its next two turn starts occur after each
	// pair of advances, decrementing then expiring the condition.
	for i := 0; i < 4; i++ {
		response = request(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/turn/advance", "Bearer session-dm", "")
		if response.Code != http.StatusOK {
			t.Fatalf("advance %d = %d: %s", i, response.Code, response.Body.String())
		}
		if i == 1 && !strings.Contains(response.Body.String(), `"round":2,"turn_index":0`) {
			t.Fatalf("first target turn = %s", response.Body.String())
		}
	}
	response = request(http.MethodGet, "/v1/play/campaigns/play-1/encounters/enc-road/status", "Bearer session-dm", "")
	if response.Code != http.StatusOK || strings.Contains(response.Body.String(), "blinded") {
		t.Fatalf("expired status = %d: %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignCombatActions(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'combat', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Borin', 'fighter', 2)`,
		`INSERT INTO play_campaign_encounters(campaign_id, id, name, status, turn_index) VALUES ('play-1', 'enc-road', 'Road Ambush', 'active', 1)`,
		`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('play-1', 'enc-road', 'goblin-1', 'Goblin', 7, 7, 15)`,
		`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('play-1', 'enc-road', 'player-a', 'char-a', 'Aria', 14)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	router := newRouter()
	request := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/encounters/enc-road/actions", strings.NewReader(body))
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, req)
		return response
	}
	if response := request("Bearer session-player-a", `{"type":"cast","target":"goblin-1","text":"Nope."}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid action received %d", response.Code)
	}
	if response := request("Bearer session-player-b", `{"type":"attack","target":"goblin-1","text":"I strike."}`); response.Code != http.StatusConflict {
		t.Fatalf("out-of-turn action received %d", response.Code)
	}
	response := request("Bearer session-player-a", `{"type":"attack","target":"goblin-1","text":"I strike with my rapier."}`)
	want := `{"sequence":1,"kind":"combat_action","actor":"player-a","type":"attack","target":"goblin-1","text":"I strike with my rapier."}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected combat action: %d %s", response.Code, response.Body.String())
	}
	var round, turnIndex int
	if err := db.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = 'play-1' AND id = 'enc-road'`).Scan(&round, &turnIndex); err != nil || round != 1 || turnIndex != 1 {
		t.Fatalf("combat turn changed to round=%d index=%d: %v", round, turnIndex, err)
	}
}

func TestMyPlayCampaignTurnOnlyExposesCallerContext(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Borin', 'fighter', 2)`,
		`INSERT INTO play_campaign_narrations(campaign_id, sequence, text) VALUES ('play-1', 1, 'The road disappears into fog.')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/my-turn", nil)
	req.SetPathValue("id", "play-1")
	req.Header.Set("Authorization", "Bearer session-player-a")
	response := httptest.NewRecorder()
	getMyPlayCampaignTurn(response, req)
	want := `{"is_my_turn":true,"current_actor":"player-a","character":{"id":"char-a","name":"Aria"},"recent_events":[{"sequence":1,"kind":"narration","actor":"dm","text":"The road disappears into fog."}]}` + "\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("unexpected player context: %d %s", response.Code, response.Body.String())
	}

	for _, header := range []string{"Bearer session-player-c", "Bearer session-dm"} {
		req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/my-turn", nil)
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", header)
		response := httptest.NewRecorder()
		getMyPlayCampaignTurn(response, req)
		if response.Code != http.StatusForbidden {
			t.Fatalf("%s received %d", header, response.Code)
		}
	}
}

func TestGMPlayCampaignStatus(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Borin', 'fighter', 2)`,
		`INSERT INTO play_campaign_narrations(campaign_id, sequence, text) VALUES ('play-1', 1, 'The road disappears into fog.')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}

	request := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/gm/status", nil)
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		getGMPlayCampaignStatus(response, req)
		return response
	}
	if response := request("Bearer session-player-a"); response.Code != http.StatusForbidden {
		t.Fatalf("player received %d", response.Code)
	}
	response := request("Bearer session-dm")
	want := `{"needs_attention":false,"current_actor":"player-a","party":[{"username":"player-a","character_id":"char-a","name":"Aria","class":"rogue"},{"username":"player-b","character_id":"char-b","name":"Borin","class":"fighter"}],"recent_events":[{"sequence":1,"kind":"narration","actor":"dm","text":"The road disappears into fog."}]}` + "\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("unexpected GM status: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignDocumentIsRoleFilteredAndDurable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "game.db")
	if err := initializeStorage(path); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}

	put := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPut, "/v1/play/campaigns/play-1/document", strings.NewReader(`{"story":"The road leads north.","dm_notes":"The cult is watching."}`))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		updatePlayCampaignDocument(response, req)
		return response
	}
	if response := put("Bearer session-player-a"); response.Code != http.StatusForbidden {
		t.Fatalf("player update received %d", response.Code)
	}
	if response := put("Bearer session-dm"); response.Code != http.StatusOK || response.Body.String() != "{\"story\":\"The road leads north.\",\"dm_notes\":\"The cult is watching.\"}\n" {
		t.Fatalf("unexpected owner update: %d %s", response.Code, response.Body.String())
	}

	get := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/document", nil)
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		getPlayCampaignDocument(response, req)
		return response
	}
	if response := get("Bearer session-dm"); response.Code != http.StatusOK || response.Body.String() != "{\"story\":\"The road leads north.\",\"dm_notes\":\"The cult is watching.\"}\n" {
		t.Fatalf("unexpected owner document: %d %s", response.Code, response.Body.String())
	}
	if response := get("Bearer session-player-a"); response.Code != http.StatusOK || response.Body.String() != "{\"story\":\"The road leads north.\"}\n" {
		t.Fatalf("unexpected player document: %d %s", response.Code, response.Body.String())
	}
}

func TestPlayCampaignSceneState(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	request := func(method, path, token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("scene_id", "cave-entrance")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		switch {
		case method == http.MethodPost && strings.HasSuffix(path, "/scenes"):
			createPlayCampaignScene(response, req)
		case strings.HasSuffix(path, "/enter"):
			enterPlayCampaignScene(response, req)
		case strings.HasSuffix(path, "/close"):
			closePlayCampaignScene(response, req)
		default:
			getCurrentPlayCampaignScene(response, req)
		}
		return response
	}

	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/scenes", "Bearer session-dm", `{"id":"cave-entrance","name":"Cave Entrance"}`); response.Code != http.StatusCreated || response.Body.String() != "{\"id\":\"cave-entrance\",\"name\":\"Cave Entrance\",\"status\":\"open\"}\n" {
		t.Fatalf("unexpected scene creation: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/scenes/cave-entrance/enter", "Bearer session-dm", ""); response.Code != http.StatusOK || response.Body.String() != "{\"current_scene_id\":\"cave-entrance\",\"name\":\"Cave Entrance\"}\n" {
		t.Fatalf("unexpected scene entry: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodGet, "/v1/play/campaigns/play-1/scenes/current", "Bearer session-player-a", ""); response.Code != http.StatusOK || response.Body.String() != "{\"id\":\"cave-entrance\",\"name\":\"Cave Entrance\",\"status\":\"open\"}\n" {
		t.Fatalf("unexpected current scene: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/scenes/cave-entrance/close", "Bearer session-dm", ""); response.Code != http.StatusOK || response.Body.String() != "{\"id\":\"cave-entrance\",\"status\":\"closed\"}\n" {
		t.Fatalf("unexpected scene close: %d %s", response.Code, response.Body.String())
	}
	if response := request(http.MethodGet, "/v1/play/campaigns/play-1/scenes/current", "Bearer session-player-a", ""); response.Code != http.StatusNotFound {
		t.Fatalf("closed current scene returned %d", response.Code)
	}
	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/scenes/cave-entrance/enter", "Bearer session-dm", ""); response.Code != http.StatusConflict {
		t.Fatalf("closed scene entry returned %d", response.Code)
	}
	if response := request(http.MethodPost, "/v1/play/campaigns/play-1/scenes", "Bearer session-player-a", `{"id":"camp","name":"Camp"}`); response.Code != http.StatusForbidden {
		t.Fatalf("member creation returned %d", response.Code)
	}
}

func TestPlayCampaignLocationGraph(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}

	createLocation := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/locations", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		createPlayCampaignLocation(response, req)
		return response
	}
	if response := createLocation("Bearer session-player-a", `{"id":"town","name":"Phandalin"}`); response.Code != http.StatusForbidden {
		t.Fatalf("player location create received %d", response.Code)
	}
	for _, location := range []struct{ body, want string }{
		{`{"id":"town","name":"Phandalin"}`, "{\"id\":\"town\",\"name\":\"Phandalin\"}\n"},
		{`{"id":"cave","name":"Wave Echo Cave"}`, "{\"id\":\"cave\",\"name\":\"Wave Echo Cave\"}\n"},
	} {
		response := createLocation("Bearer session-dm", location.body)
		if response.Code != http.StatusCreated || response.Body.String() != location.want {
			t.Fatalf("unexpected location response: %d %s", response.Code, response.Body.String())
		}
	}
	if response := createLocation("Bearer session-dm", `{"id":"cave","name":"Duplicate"}`); response.Code != http.StatusConflict {
		t.Fatalf("duplicate location received %d", response.Code)
	}

	connection := func(to string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/locations/town/connections", strings.NewReader(to))
		req.SetPathValue("id", "play-1")
		req.SetPathValue("from_id", "town")
		req.Header.Set("Authorization", "Bearer session-dm")
		response := httptest.NewRecorder()
		createPlayCampaignLocationConnection(response, req)
		return response
	}
	if response := connection(`{"to_id":"missing","travel_turns":1}`); response.Code != http.StatusBadRequest {
		t.Fatalf("missing destination received %d", response.Code)
	}
	if response := connection(`{"to_id":"cave","travel_turns":1}`); response.Code != http.StatusCreated || response.Body.String() != "{\"from_id\":\"town\",\"to_id\":\"cave\",\"travel_turns\":1}\n" {
		t.Fatalf("unexpected connection response: %d %s", response.Code, response.Body.String())
	}
	if response := connection(`{"to_id":"cave","travel_turns":1}`); response.Code != http.StatusBadRequest {
		t.Fatalf("duplicate connection received %d", response.Code)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/locations/town/travel", nil)
	req.SetPathValue("id", "play-1")
	req.SetPathValue("loc_id", "town")
	req.Header.Set("Authorization", "Bearer session-player-a")
	response := httptest.NewRecorder()
	getPlayCampaignLocationTravel(response, req)
	want := "{\"destinations\":[{\"id\":\"cave\",\"name\":\"Wave Echo Cave\",\"travel_turns\":1}]}\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("unexpected travel response: %d %s", response.Code, response.Body.String())
	}
}

func TestCompendiumRoundTrip(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()

	monster := call(createMonster, `{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7,"tags":["humanoid","goblinoid"]}`)
	if monster.Code != http.StatusCreated || monster.Body.String() != "{\"slug\":\"goblin\",\"name\":\"Goblin\",\"cr\":\"1/4\",\"armor_class\":15,\"hit_points\":7}\n" {
		t.Fatalf("unexpected monster creation: %d %s", monster.Code, monster.Body.String())
	}
	getMonsterRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	getMonsterRequest.SetPathValue("slug", "goblin")
	getMonsterResponse := httptest.NewRecorder()
	getMonster(getMonsterResponse, getMonsterRequest)
	if getMonsterResponse.Code != http.StatusOK || getMonsterResponse.Body.String() != "{\"slug\":\"goblin\",\"name\":\"Goblin\",\"cr\":\"1/4\",\"armor_class\":15,\"hit_points\":7,\"tags\":[\"humanoid\",\"goblinoid\"]}\n" {
		t.Fatalf("unexpected monster read: %d %s", getMonsterResponse.Code, getMonsterResponse.Body.String())
	}
	if duplicate := call(createMonster, `{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7,"tags":[]}`); duplicate.Code != http.StatusConflict {
		t.Fatalf("duplicate monster returned %d", duplicate.Code)
	}

	createdItem := call(createItem, `{"slug":"healing-potion","name":"Potion of Healing","type":"potion","rarity":"common","cost_gp":50}`)
	if createdItem.Code != http.StatusCreated || createdItem.Body.String() != "{\"slug\":\"healing-potion\",\"name\":\"Potion of Healing\",\"type\":\"potion\",\"rarity\":\"common\",\"cost_gp\":50}\n" {
		t.Fatalf("unexpected item creation: %d %s", createdItem.Code, createdItem.Body.String())
	}
	getItemRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	getItemRequest.SetPathValue("slug", "healing-potion")
	getItemResponse := httptest.NewRecorder()
	getItem(getItemResponse, getItemRequest)
	if getItemResponse.Code != http.StatusOK || getItemResponse.Body.String() != "{\"slug\":\"healing-potion\",\"name\":\"Potion of Healing\",\"type\":\"potion\",\"rarity\":\"common\",\"cost_gp\":50}\n" {
		t.Fatalf("unexpected item read: %d %s", getItemResponse.Code, getItemResponse.Body.String())
	}
}

func TestCampaignState(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()

	created := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`)
	if created.Code != http.StatusCreated || created.Body.String() != "{\"id\":\"camp-1\",\"name\":\"Lost Mine\",\"dm\":\"dm\"}\n" {
		t.Fatalf("unexpected campaign creation: %d %s", created.Code, created.Body.String())
	}
	characterRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}`))
	characterRequest.SetPathValue("id", "camp-1")
	characterResponse := httptest.NewRecorder()
	addCampaignCharacter(characterResponse, characterRequest)
	if characterResponse.Code != http.StatusCreated || characterResponse.Body.String() != "{\"id\":\"char-1\",\"name\":\"Nyx\",\"level\":3,\"class\":\"rogue\"}\n" {
		t.Fatalf("unexpected character creation: %d %s", characterResponse.Code, characterResponse.Body.String())
	}
	eventRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"evt-1","kind":"note","summary":"Nyx scouts the goblin trail."}`))
	eventRequest.SetPathValue("id", "camp-1")
	eventResponse := httptest.NewRecorder()
	addCampaignEvent(eventResponse, eventRequest)
	if eventResponse.Code != http.StatusCreated || eventResponse.Body.String() != "{\"id\":\"evt-1\",\"kind\":\"note\"}\n" {
		t.Fatalf("unexpected event creation: %d %s", eventResponse.Code, eventResponse.Body.String())
	}
	stateRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	stateRequest.SetPathValue("id", "camp-1")
	stateResponse := httptest.NewRecorder()
	getCampaignState(stateResponse, stateRequest)
	want := "{\"id\":\"camp-1\",\"name\":\"Lost Mine\",\"dm\":\"dm\",\"characters\":[{\"id\":\"char-1\",\"name\":\"Nyx\",\"level\":3,\"class\":\"rogue\"}],\"log_count\":1}\n"
	if stateResponse.Code != http.StatusOK || stateResponse.Body.String() != want {
		t.Fatalf("unexpected campaign state: %d %s", stateResponse.Code, stateResponse.Body.String())
	}
	if duplicate := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); duplicate.Code != http.StatusConflict {
		t.Fatalf("duplicate campaign returned %d", duplicate.Code)
	}
}

func TestCampaignAuditAndExport(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO campaign_characters(campaign_id, id, name, level, class) VALUES ('camp-1', 'char-1', 'Nyx', 3, 'rogue')`,
		`INSERT INTO campaign_events(campaign_id, id, kind, summary) VALUES ('camp-1', 'evt-1', 'note', 'A note')`,
		`INSERT INTO campaign_factions(campaign_id, id, name, stance) VALUES ('camp-1', 'fac-1', 'Faction', 'friendly')`,
		`INSERT INTO campaign_npcs(campaign_id, id, name, faction_id, disposition) VALUES ('camp-1', 'npc-1', 'NPC', 'fac-1', 1)`,
		`INSERT INTO quests(campaign_id, id, title, status) VALUES ('camp-1', 'quest-1', 'Quest', 'active')`,
		`INSERT INTO campaign_inventory(campaign_id, item_slug, quantity) VALUES ('camp-1', 'healing-potion', 1)`,
		`INSERT INTO campaign_sessions(campaign_id, id, starts_at, duration_minutes) VALUES ('camp-1', 'sess-1', '2026-01-01T00:00:00Z', 60)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	for _, test := range []struct {
		handler http.HandlerFunc
		want    string
	}{
		{getCampaignAudit, `{"campaign_id":"camp-1","events":1,"quests":1,"npcs":1,"sessions":1}` + "\n"},
		{exportCampaign, `{"campaign_id":"camp-1","name":"Lost Mine","characters":1,"quests":1,"npcs":1,"inventory_items":1,"sessions":1,"schema_version":1}` + "\n"},
	} {
		request := httptest.NewRequest(http.MethodGet, "/", nil)
		request.SetPathValue("id", "camp-1")
		response := httptest.NewRecorder()
		test.handler(response, request)
		if response.Code != http.StatusOK || response.Body.String() != test.want {
			t.Fatalf("unexpected campaign summary: %d %s", response.Code, response.Body.String())
		}
	}
}

func TestCampaignAnalytics(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO campaign_characters(campaign_id, id, name, level, class) VALUES ('camp-1', 'char-1', 'Nyx', 3, 'rogue')`,
		`INSERT INTO campaign_factions(campaign_id, id, name, stance) VALUES ('camp-1', 'fac-1', 'Faction', 'friendly')`,
		`INSERT INTO campaign_npcs(campaign_id, id, name, faction_id, disposition) VALUES ('camp-1', 'npc-1', 'NPC', 'fac-1', 1)`,
		`INSERT INTO quests(campaign_id, id, title, status) VALUES ('camp-1', 'quest-1', 'Quest', 'active')`,
		`INSERT INTO campaign_inventory(campaign_id, item_slug, quantity) VALUES ('camp-1', 'healing-potion', 1)`,
		`INSERT INTO campaign_sessions(campaign_id, id, starts_at, duration_minutes) VALUES ('camp-1', 'sess-1', '2026-01-01T00:00:00Z', 60)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	summaryRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	summaryRequest.SetPathValue("id", "camp-1")
	summaryResponse := httptest.NewRecorder()
	campaignAnalyticsSummary(summaryResponse, summaryRequest)
	if want := `{"campaign_id":"camp-1","readiness_score":85,"open_quests":1,"friendly_npcs":1,"scheduled_sessions":1,"inventory_items":1}` + "\n"; summaryResponse.Code != http.StatusOK || summaryResponse.Body.String() != want {
		t.Fatalf("unexpected analytics summary: %d %s", summaryResponse.Code, summaryResponse.Body.String())
	}
	riskRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"include_zeroes":true}`))
	riskRequest.SetPathValue("id", "camp-1")
	riskResponse := httptest.NewRecorder()
	campaignRiskReport(riskResponse, riskRequest)
	if want := `{"campaign_id":"camp-1","risk_level":"low","missing":[],"signals":{"has_dm":true,"has_characters":true,"has_next_session":true,"has_active_quest":true}}` + "\n"; riskResponse.Code != http.StatusOK || riskResponse.Body.String() != want {
		t.Fatalf("unexpected risk report: %d %s", riskResponse.Code, riskResponse.Body.String())
	}
}

func TestSessionScheduling(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	characterRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}`))
	characterRequest.SetPathValue("id", "camp-1")
	characterResponse := httptest.NewRecorder()
	addCampaignCharacter(characterResponse, characterRequest)
	if characterResponse.Code != http.StatusCreated {
		t.Fatal(characterResponse.Body.String())
	}
	scheduleRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"sess-1","starts_at":"2026-07-19T19:00:00Z","duration_minutes":180,"agenda":["Goblin trail","Stonehill Inn fallout"]}`))
	scheduleRequest.SetPathValue("id", "camp-1")
	scheduleResponse := httptest.NewRecorder()
	scheduleSession(scheduleResponse, scheduleRequest)
	if want := "{\"id\":\"sess-1\",\"starts_at\":\"2026-07-19T19:00:00Z\",\"duration_minutes\":180,\"agenda_count\":2}\n"; scheduleResponse.Code != http.StatusCreated || scheduleResponse.Body.String() != want {
		t.Fatalf("unexpected session response: %d %s", scheduleResponse.Code, scheduleResponse.Body.String())
	}
	attendanceRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"present":["char-1"],"absent":[]}`))
	attendanceRequest.SetPathValue("id", "camp-1")
	attendanceRequest.SetPathValue("session_id", "sess-1")
	attendanceResponse := httptest.NewRecorder()
	recordAttendance(attendanceResponse, attendanceRequest)
	if want := "{\"session_id\":\"sess-1\",\"present_count\":1,\"absent_count\":0}\n"; attendanceResponse.Code != http.StatusOK || attendanceResponse.Body.String() != want {
		t.Fatalf("unexpected attendance response: %d %s", attendanceResponse.Code, attendanceResponse.Body.String())
	}
	nextRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	nextRequest.SetPathValue("id", "camp-1")
	nextResponse := httptest.NewRecorder()
	nextSession(nextResponse, nextRequest)
	if want := "{\"id\":\"sess-1\",\"starts_at\":\"2026-07-19T19:00:00Z\",\"agenda_count\":2}\n"; nextResponse.Code != http.StatusOK || nextResponse.Body.String() != want {
		t.Fatalf("unexpected next session response: %d %s", nextResponse.Code, nextResponse.Body.String())
	}
}

func TestCampaignInventoryAndEquipment(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	characterRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}`))
	characterRequest.SetPathValue("id", "camp-1")
	characterResponse := httptest.NewRecorder()
	addCampaignCharacter(characterResponse, characterRequest)
	if characterResponse.Code != http.StatusCreated {
		t.Fatal(characterResponse.Body.String())
	}
	inventoryRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"item_slug":"healing-potion","quantity":3,"owner":"party"}`))
	inventoryRequest.SetPathValue("id", "camp-1")
	inventoryResponse := httptest.NewRecorder()
	addInventoryItem(inventoryResponse, inventoryRequest)
	if want := "{\"item_slug\":\"healing-potion\",\"quantity\":3,\"owner\":\"party\"}\n"; inventoryResponse.Code != http.StatusCreated || inventoryResponse.Body.String() != want {
		t.Fatalf("unexpected inventory response: %d %s", inventoryResponse.Code, inventoryResponse.Body.String())
	}
	equipmentRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"item_slug":"healing-potion","quantity":1}`))
	equipmentRequest.SetPathValue("id", "camp-1")
	equipmentRequest.SetPathValue("character_id", "char-1")
	equipmentResponse := httptest.NewRecorder()
	assignEquipment(equipmentResponse, equipmentRequest)
	if want := "{\"character_id\":\"char-1\",\"item_slug\":\"healing-potion\",\"quantity\":1}\n"; equipmentResponse.Code != http.StatusOK || equipmentResponse.Body.String() != want {
		t.Fatalf("unexpected equipment response: %d %s", equipmentResponse.Code, equipmentResponse.Body.String())
	}
	summaryRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	summaryRequest.SetPathValue("id", "camp-1")
	summaryResponse := httptest.NewRecorder()
	getInventorySummary(summaryResponse, summaryRequest)
	if want := "{\"campaign_id\":\"camp-1\",\"party_items\":1,\"assigned_items\":1,\"healing_potions_available\":2}\n"; summaryResponse.Code != http.StatusOK || summaryResponse.Body.String() != want {
		t.Fatalf("unexpected inventory summary: %d %s", summaryResponse.Code, summaryResponse.Body.String())
	}
}

func TestDowntimeCrafting(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	characterRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}`))
	characterRequest.SetPathValue("id", "camp-1")
	characterResponse := httptest.NewRecorder()
	addCampaignCharacter(characterResponse, characterRequest)
	if characterResponse.Code != http.StatusCreated {
		t.Fatal(characterResponse.Body.String())
	}
	projectRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"craft-1","character_id":"char-1","item_slug":"healing-potion","days_required":2,"cost_gp":25}`))
	projectRequest.SetPathValue("id", "camp-1")
	projectResponse := httptest.NewRecorder()
	createCraftingProject(projectResponse, projectRequest)
	if want := "{\"id\":\"craft-1\",\"character_id\":\"char-1\",\"item_slug\":\"healing-potion\",\"days_required\":2,\"days_completed\":0,\"status\":\"active\"}\n"; projectResponse.Code != http.StatusCreated || projectResponse.Body.String() != want {
		t.Fatalf("unexpected crafting project: %d %s", projectResponse.Code, projectResponse.Body.String())
	}
	advanceRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"days":2}`))
	advanceRequest.SetPathValue("id", "camp-1")
	advanceRequest.SetPathValue("project_id", "craft-1")
	advanceResponse := httptest.NewRecorder()
	advanceCraftingProject(advanceResponse, advanceRequest)
	if want := "{\"id\":\"craft-1\",\"days_completed\":2,\"status\":\"complete\"}\n"; advanceResponse.Code != http.StatusOK || advanceResponse.Body.String() != want {
		t.Fatalf("unexpected crafting advance: %d %s", advanceResponse.Code, advanceResponse.Body.String())
	}
	summaryRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	summaryRequest.SetPathValue("id", "camp-1")
	summaryResponse := httptest.NewRecorder()
	getInventorySummary(summaryResponse, summaryRequest)
	if want := "{\"campaign_id\":\"camp-1\",\"party_items\":1,\"assigned_items\":0,\"healing_potions_available\":1}\n"; summaryResponse.Code != http.StatusOK || summaryResponse.Body.String() != want {
		t.Fatalf("crafted item was not added to inventory: %d %s", summaryResponse.Code, summaryResponse.Body.String())
	}
}

func TestNPCRelationships(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	factionRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"faction-1","name":"Stonehill Inn","stance":"friendly"}`))
	factionRequest.SetPathValue("id", "camp-1")
	factionResponse := httptest.NewRecorder()
	createFaction(factionResponse, factionRequest)
	if want := "{\"id\":\"faction-1\",\"name\":\"Stonehill Inn\",\"stance\":\"friendly\"}\n"; factionResponse.Code != http.StatusCreated || factionResponse.Body.String() != want {
		t.Fatalf("unexpected faction creation: %d %s", factionResponse.Code, factionResponse.Body.String())
	}
	npcRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"npc-1","name":"Toblen Stonehill","faction_id":"faction-1","disposition":2}`))
	npcRequest.SetPathValue("id", "camp-1")
	npcResponse := httptest.NewRecorder()
	createNPC(npcResponse, npcRequest)
	if want := "{\"id\":\"npc-1\",\"name\":\"Toblen Stonehill\",\"faction_id\":\"faction-1\",\"disposition\":2}\n"; npcResponse.Code != http.StatusCreated || npcResponse.Body.String() != want {
		t.Fatalf("unexpected npc creation: %d %s", npcResponse.Code, npcResponse.Body.String())
	}
	relationshipsRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	relationshipsRequest.SetPathValue("id", "camp-1")
	relationshipsResponse := httptest.NewRecorder()
	getRelationships(relationshipsResponse, relationshipsRequest)
	if want := "{\"campaign_id\":\"camp-1\",\"factions\":1,\"npcs\":1,\"friendly_npcs\":1}\n"; relationshipsResponse.Code != http.StatusOK || relationshipsResponse.Body.String() != want {
		t.Fatalf("unexpected relationship summary: %d %s", relationshipsResponse.Code, relationshipsResponse.Body.String())
	}
}

func TestQuestTracker(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	questRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"quest-1","title":"Resolve goblin trail ambush","status":"active","milestones":["Find the trail","Confront the ambushers"]}`))
	questRequest.SetPathValue("id", "camp-1")
	questResponse := httptest.NewRecorder()
	createQuest(questResponse, questRequest)
	if want := "{\"id\":\"quest-1\",\"title\":\"Resolve goblin trail ambush\",\"status\":\"active\",\"milestones_total\":2,\"milestones_done\":0}\n"; questResponse.Code != http.StatusCreated || questResponse.Body.String() != want {
		t.Fatalf("unexpected quest creation: %d %s", questResponse.Code, questResponse.Body.String())
	}
	progressRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"completed":["Find the trail"]}`))
	progressRequest.SetPathValue("id", "camp-1")
	progressRequest.SetPathValue("quest_id", "quest-1")
	progressResponse := httptest.NewRecorder()
	updateQuestProgress(progressResponse, progressRequest)
	if want := "{\"id\":\"quest-1\",\"status\":\"active\",\"milestones_total\":2,\"milestones_done\":1}\n"; progressResponse.Code != http.StatusOK || progressResponse.Body.String() != want {
		t.Fatalf("unexpected quest progress: %d %s", progressResponse.Code, progressResponse.Body.String())
	}
	summaryRequest := httptest.NewRequest(http.MethodGet, "/", nil)
	summaryRequest.SetPathValue("id", "camp-1")
	summaryResponse := httptest.NewRecorder()
	getQuestSummary(summaryResponse, summaryRequest)
	if want := "{\"campaign_id\":\"camp-1\",\"active\":1,\"completed\":0,\"blocked\":0}\n"; summaryResponse.Code != http.StatusOK || summaryResponse.Body.String() != want {
		t.Fatalf("unexpected quest summary: %d %s", summaryResponse.Code, summaryResponse.Body.String())
	}
}

func TestDMTools(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if response := call(createCampaign, `{"id":"camp-1","name":"Lost Mine","dm":"dm"}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	if response := call(createMonster, `{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7,"tags":[]}`); response.Code != http.StatusCreated {
		t.Fatal(response.Body.String())
	}
	eventRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"id":"evt-1","kind":"note","summary":"Nyx scouts the goblin trail."}`))
	eventRequest.SetPathValue("id", "camp-1")
	eventResponse := httptest.NewRecorder()
	addCampaignEvent(eventResponse, eventRequest)
	if eventResponse.Code != http.StatusCreated {
		t.Fatal(eventResponse.Body.String())
	}
	encounter := call(encounterBuilder, `{"campaign_id":"camp-1","party":[{"level":3},{"level":3},{"level":3},{"level":3}],"monster_slugs":["goblin","goblin","goblin"]}`)
	wantEncounter := "{\"campaign_id\":\"camp-1\",\"base_xp\":150,\"adjusted_xp\":300,\"difficulty\":\"easy\",\"monster_count\":3,\"recommendation\":\"safe warm-up\"}\n"
	if encounter.Code != http.StatusOK || encounter.Body.String() != wantEncounter {
		t.Fatalf("unexpected encounter: %d %s", encounter.Code, encounter.Body.String())
	}
	loot := call(lootParcel, `{"campaign_id":"camp-1","tier":1,"seed":42}`)
	if want := "{\"campaign_id\":\"camp-1\",\"coins_gp\":75,\"items\":[{\"slug\":\"healing-potion\",\"quantity\":2}]}\n"; loot.Code != http.StatusOK || loot.Body.String() != want {
		t.Fatalf("unexpected loot: %d %s", loot.Code, loot.Body.String())
	}
	recap := call(sessionRecap, `{"campaign_id":"camp-1"}`)
	if want := "{\"campaign_id\":\"camp-1\",\"summary\":\"Nyx scouts the goblin trail.\",\"open_threads\":[\"Resolve goblin trail ambush\"]}\n"; recap.Code != http.StatusOK || recap.Body.String() != want {
		t.Fatalf("unexpected recap: %d %s", recap.Code, recap.Body.String())
	}
}

func TestDiceStats(t *testing.T) {
	response := call(diceStats, `{"expression":"2d6+3"}`)
	if response.Code != http.StatusOK || response.Body.String() != "{\"average\":10,\"dice_count\":2,\"max\":15,\"min\":5,\"modifier\":3,\"sides\":6}\n" {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
	if response := call(diceStats, `{"expression":"0d6"}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid expression returned %d", response.Code)
	}
}

func TestAbilityAndInitiative(t *testing.T) {
	ability := call(abilityCheck, `{"roll":9,"modifier":5,"dc":15}`)
	if ability.Code != http.StatusOK || ability.Body.String() != "{\"margin\":-1,\"success\":false,\"total\":14}\n" {
		t.Fatalf("unexpected ability response: %s", ability.Body.String())
	}
	initiative := call(initiativeOrder, `{"combatants":[{"name":"ogre","dex":-1,"roll":16},{"name":"rogue","dex":3,"roll":14}]}`)
	if initiative.Code != http.StatusOK || initiative.Body.String() != "{\"order\":[{\"name\":\"rogue\",\"score\":17},{\"name\":\"ogre\",\"score\":15}]}\n" {
		t.Fatalf("unexpected initiative response: %s", initiative.Body.String())
	}
}

func TestAdjustedXP(t *testing.T) {
	response := call(adjustedXP, `{"party":[{"level":3},{"level":3},{"level":3},{"level":3}],"monsters":[{"cr":"1","count":2},{"cr":"2","count":1}]}`)
	want := "{\"adjusted_xp\":1700,\"base_xp\":850,\"difficulty\":\"deadly\",\"monster_count\":3,\"multiplier\":2,\"thresholds\":{\"deadly\":1600,\"easy\":300,\"hard\":900,\"medium\":600}}\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
}

func TestCharacterRules(t *testing.T) {
	modifier := call(abilityModifier, `{"score":9}`)
	if modifier.Code != http.StatusOK || modifier.Body.String() != "{\"modifier\":-1,\"score\":9}\n" {
		t.Fatalf("unexpected modifier response: %d %s", modifier.Code, modifier.Body.String())
	}
	if response := call(abilityModifier, `{"score":31}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid score returned %d", response.Code)
	}

	bonus := call(proficiency, `{"level":9}`)
	if bonus.Code != http.StatusOK || bonus.Body.String() != "{\"level\":9,\"proficiency_bonus\":4}\n" {
		t.Fatalf("unexpected proficiency response: %d %s", bonus.Code, bonus.Body.String())
	}
	if response := call(proficiency, `{"level":0}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid level returned %d", response.Code)
	}
}

func TestPHBRules(t *testing.T) {
	slots := call(spellSlots, `{"class":"wizard","level":5}`)
	if slots.Code != http.StatusOK || slots.Body.String() != "{\"class\":\"wizard\",\"level\":5,\"slots\":{\"1\":4,\"2\":3,\"3\":2}}\n" {
		t.Fatalf("unexpected spell slots response: %d %s", slots.Code, slots.Body.String())
	}
	if response := call(spellSlots, `{"class":"wizard","level":4}`); response.Code != http.StatusBadRequest {
		t.Fatalf("unsupported spell slots returned %d", response.Code)
	}

	rest := call(longRest, `{"level":5,"hp_current":9,"hp_max":35,"hit_dice_spent":3,"exhaustion_level":1}`)
	if rest.Code != http.StatusOK || rest.Body.String() != "{\"hp_current\":35,\"hit_dice_spent\":1,\"exhaustion_level\":0}\n" {
		t.Fatalf("unexpected long rest response: %d %s", rest.Code, rest.Body.String())
	}
	if response := call(longRest, `{"level":0,"hp_current":9,"hp_max":35,"hit_dice_spent":3,"exhaustion_level":1}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid long rest returned %d", response.Code)
	}

	load := call(equipmentLoad, `{"strength":12,"weight":181}`)
	if load.Code != http.StatusOK || load.Body.String() != "{\"capacity\":180,\"weight\":181,\"encumbered\":true}\n" {
		t.Fatalf("unexpected equipment load response: %d %s", load.Code, load.Body.String())
	}
	if response := call(equipmentLoad, `{"strength":0,"weight":181}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid equipment load returned %d", response.Code)
	}
}

func TestDerivedStats(t *testing.T) {
	response := call(derivedStats, `{"level":5,"abilities":{"str":16,"dex":14,"con":13,"int":8,"wis":12,"cha":10},"armor":{"base":12,"shield":true,"dex_cap":2}}`)
	want := "{\"armor_class\":16,\"hp_max\":35,\"level\":5,\"modifiers\":{\"cha\":0,\"con\":1,\"dex\":2,\"int\":-1,\"str\":3,\"wis\":1},\"proficiency_bonus\":3}\n"
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("unexpected derived stats response: %d %s", response.Code, response.Body.String())
	}
	if response := call(derivedStats, `{"level":5,"abilities":{"str":0,"dex":14,"con":13,"int":8,"wis":12,"cha":10},"armor":{"base":12,"shield":true,"dex_cap":2}}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid score returned %d", response.Code)
	}
}

func TestCombatSessions(t *testing.T) {
	sessions.Lock()
	sessions.sessions = make(map[string]*combatSession)
	sessions.Unlock()

	created := call(createCombatSession, `{"id":"enc-1","combatants":[{"name":"fighter","dex":1,"roll":13},{"name":"rogue","dex":3,"roll":14},{"name":"mage","dex":2,"roll":14}]}`)
	wantCreated := "{\"id\":\"enc-1\",\"round\":1,\"turn_index\":0,\"active\":{\"name\":\"rogue\",\"score\":17},\"order\":[{\"name\":\"rogue\",\"score\":17},{\"name\":\"mage\",\"score\":16},{\"name\":\"fighter\",\"score\":14}]}\n"
	if created.Code != http.StatusOK || created.Body.String() != wantCreated {
		t.Fatalf("unexpected session response: %d %s", created.Code, created.Body.String())
	}

	conditionRequest := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"target":"fighter","condition":"blessed","duration_rounds":2}`))
	conditionRequest.SetPathValue("id", "enc-1")
	conditionResponse := httptest.NewRecorder()
	addCondition(conditionResponse, conditionRequest)
	if got := conditionResponse.Body.String(); conditionResponse.Code != http.StatusOK || got != "{\"target\":\"fighter\",\"conditions\":[{\"condition\":\"blessed\",\"remaining_rounds\":2}]}\n" {
		t.Fatalf("unexpected condition response: %d %s", conditionResponse.Code, got)
	}

	for _, want := range []string{
		"{\"id\":\"enc-1\",\"round\":1,\"turn_index\":1,\"active\":{\"name\":\"mage\",\"score\":16},\"conditions\":{\"fighter\":[{\"condition\":\"blessed\",\"remaining_rounds\":2}]}}\n",
		"{\"id\":\"enc-1\",\"round\":1,\"turn_index\":2,\"active\":{\"name\":\"fighter\",\"score\":14},\"conditions\":{\"fighter\":[{\"condition\":\"blessed\",\"remaining_rounds\":1}]}}\n",
		"{\"id\":\"enc-1\",\"round\":2,\"turn_index\":0,\"active\":{\"name\":\"rogue\",\"score\":17},\"conditions\":{\"fighter\":[{\"condition\":\"blessed\",\"remaining_rounds\":1}]}}\n",
		"{\"id\":\"enc-1\",\"round\":2,\"turn_index\":1,\"active\":{\"name\":\"mage\",\"score\":16},\"conditions\":{\"fighter\":[{\"condition\":\"blessed\",\"remaining_rounds\":1}]}}\n",
		"{\"id\":\"enc-1\",\"round\":2,\"turn_index\":2,\"active\":{\"name\":\"fighter\",\"score\":14},\"conditions\":{\"fighter\":[]}}\n",
	} {
		request := httptest.NewRequest(http.MethodPost, "/", nil)
		request.SetPathValue("id", "enc-1")
		response := httptest.NewRecorder()
		advanceTurn(response, request)
		if response.Code != http.StatusOK || response.Body.String() != want {
			t.Fatalf("unexpected advance response: %d %s", response.Code, response.Body.String())
		}
	}

	unknownRequest := httptest.NewRequest(http.MethodPost, "/", nil)
	unknownRequest.SetPathValue("id", "missing")
	unknownResponse := httptest.NewRecorder()
	advanceTurn(unknownResponse, unknownRequest)
	if unknownResponse.Code != http.StatusNotFound {
		t.Fatalf("unknown session returned %d", unknownResponse.Code)
	}
}

func TestUsersAndPasswordLogin(t *testing.T) {
	users.Lock()
	users.users = make(map[string]user)
	users.Unlock()

	registered := call(registerUser, `{"username":"dm","password":"swordfish","role":"dm"}`)
	if registered.Code != http.StatusCreated || registered.Body.String() != "{\"username\":\"dm\",\"role\":\"dm\"}\n" {
		t.Fatalf("unexpected register response: %d %s", registered.Code, registered.Body.String())
	}
	if duplicate := call(registerUser, `{"username":"dm","password":"another-password","role":"dm"}`); duplicate.Code != http.StatusConflict {
		t.Fatalf("duplicate username returned %d", duplicate.Code)
	}
	if invalid := call(registerUser, `{"username":"DM","password":"short","role":"admin"}`); invalid.Code != http.StatusBadRequest {
		t.Fatalf("invalid registration returned %d", invalid.Code)
	}

	login := call(loginUser, `{"username":"dm","password":"swordfish"}`)
	if login.Code != http.StatusOK || login.Body.String() != "{\"username\":\"dm\",\"token\":\"session-dm\"}\n" {
		t.Fatalf("unexpected login response: %d %s", login.Code, login.Body.String())
	}
	if rejected := call(loginUser, `{"username":"dm","password":"wrong-password"}`); rejected.Code != http.StatusUnauthorized {
		t.Fatalf("bad password returned %d", rejected.Code)
	}
}

func TestCreatePlayCampaignRequiresDM(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	users.Lock()
	users.users = make(map[string]user)
	users.Unlock()

	request := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns", strings.NewReader(`{"id":"play-1","name":"Ashen Road","max_players":2}`))
		if token != "" {
			req.Header.Set("Authorization", token)
		}
		response := httptest.NewRecorder()
		createPlayCampaign(response, req)
		return response
	}
	if response := request(""); response.Code != http.StatusUnauthorized {
		t.Fatalf("missing credentials returned %d", response.Code)
	}
	if response := request("Bearer session-player"); response.Code != http.StatusForbidden {
		t.Fatalf("player returned %d", response.Code)
	}
	guestRequest := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns", nil)
	guestRequest.Header.Set("Authorization", "Bearer session-guest")
	if actor, ok := authenticatedUser(guestRequest); !ok || actor.Role != "player" {
		t.Fatal("unregistered session actor was not treated as a player")
	}
	created := request("Bearer session-dm")
	if want := "{\"id\":\"play-1\",\"name\":\"Ashen Road\",\"owner\":\"dm\",\"status\":\"lobby\",\"max_players\":2}\n"; created.Code != http.StatusCreated || created.Body.String() != want {
		t.Fatalf("unexpected campaign creation: %d %s", created.Code, created.Body.String())
	}
	if response := request("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("duplicate campaign returned %d", response.Code)
	}
}

func TestPlayCampaignMembership(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if _, err := currentDB().Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`); err != nil {
		t.Fatal(err)
	}
	join := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/members", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		if token != "" {
			req.Header.Set("Authorization", token)
		}
		response := httptest.NewRecorder()
		joinPlayCampaign(response, req)
		return response
	}
	if response := join("", `{}`); response.Code != http.StatusUnauthorized {
		t.Fatalf("missing credentials returned %d", response.Code)
	}
	if response := join("Bearer session-dm", `{"character_id":"play-char-a","name":"Aria","class":"rogue"}`); response.Code != http.StatusForbidden {
		t.Fatalf("dm join returned %d", response.Code)
	}
	joined := join("Bearer session-aria", `{"character_id":"play-char-a","name":"Aria","class":"rogue"}`)
	if want := "{\"username\":\"aria\",\"character_id\":\"play-char-a\",\"name\":\"Aria\",\"class\":\"rogue\"}\n"; joined.Code != http.StatusCreated || joined.Body.String() != want {
		t.Fatalf("unexpected member response: %d %s", joined.Code, joined.Body.String())
	}
	if response := join("Bearer session-aria", `{"character_id":"play-char-b","name":"Aria","class":"rogue"}`); response.Code != http.StatusConflict {
		t.Fatalf("duplicate player returned %d", response.Code)
	}
	if response := join("Bearer session-bryn", `{"character_id":"play-char-a","name":"Bryn","class":"cleric"}`); response.Code != http.StatusConflict {
		t.Fatalf("duplicate character returned %d", response.Code)
	}
	if response := join("Bearer session-bryn", `{"character_id":"play-char-b","name":"Bryn","class":"cleric"}`); response.Code != http.StatusCreated {
		t.Fatalf("second member returned %d", response.Code)
	}
	if response := join("Bearer session-cato", `{"character_id":"play-char-c","name":"Cato","class":"wizard"}`); response.Code != http.StatusConflict {
		t.Fatalf("full party returned %d", response.Code)
	}
}

func TestStartPlayCampaign(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	if _, err := db.Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 3)`); err != nil {
		t.Fatal(err)
	}
	start := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/start", nil)
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		startPlayCampaign(response, req)
		return response
	}
	if response := start("Bearer session-player-a"); response.Code != http.StatusForbidden {
		t.Fatalf("player start returned %d", response.Code)
	}
	if response := start("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("under-populated start returned %d", response.Code)
	}
	for _, member := range []struct{ username, characterID string }{{"player-b", "char-b"}, {"player-a", "char-a"}} {
		if _, err := db.Exec(`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class) VALUES ('play-1', ?, ?, 'Player', 'rogue')`, member.username, member.characterID); err != nil {
			t.Fatal(err)
		}
	}
	if response := start("Bearer session-dm"); response.Code != http.StatusOK || response.Body.String() != "{\"id\":\"play-1\",\"status\":\"active\",\"current_actor\":\"player-a\",\"turn_number\":1}\n" {
		t.Fatalf("unexpected campaign start: %d %s", response.Code, response.Body.String())
	}
	if response := start("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("second start returned %d", response.Code)
	}
}

func TestPlayCampaignTurnRequiresMembership(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class) VALUES ('play-1', 'player-b', 'char-b', 'Bryn', 'cleric')`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	turn := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/turn", nil)
		req.SetPathValue("id", "play-1")
		if token != "" {
			req.Header.Set("Authorization", token)
		}
		response := httptest.NewRecorder()
		getPlayCampaignTurn(response, req)
		return response
	}
	if response := turn(""); response.Code != http.StatusUnauthorized {
		t.Fatalf("missing credentials returned %d", response.Code)
	}
	if response := turn("Bearer session-outsider"); response.Code != http.StatusForbidden {
		t.Fatalf("non-member returned %d", response.Code)
	}
	for _, token := range []string{"Bearer session-dm", "Bearer session-player-a"} {
		response := turn(token)
		want := "{\"campaign_id\":\"play-1\",\"current_actor\":\"player-a\",\"phase\":\"player\",\"turn_number\":1,\"logical_deadline\":2,\"overdue\":false,\"queue\":[\"player-a\",\"dm\",\"player-b\",\"dm\"]}\n"
		if response.Code != http.StatusOK || response.Body.String() != want {
			t.Fatalf("unexpected turn response: %d %s", response.Code, response.Body.String())
		}
	}
}

func TestPlayCampaignTurnQueueUsesJoinOrder(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if _, err := currentDB().Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`); err != nil {
		t.Fatal(err)
	}
	for _, member := range []struct {
		token string
		body  string
	}{
		{"Bearer session-player-a", `{"character_id":"char-a","name":"Aria","class":"rogue"}`},
		{"Bearer session-player-b", `{"character_id":"char-b","name":"Bryn","class":"cleric"}`},
	} {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/members", strings.NewReader(member.body))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", member.token)
		response := httptest.NewRecorder()
		joinPlayCampaign(response, req)
		if response.Code != http.StatusCreated {
			t.Fatalf("join failed: %d %s", response.Code, response.Body.String())
		}
	}
	startRequest := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/start", nil)
	startRequest.SetPathValue("id", "play-1")
	startRequest.Header.Set("Authorization", "Bearer session-dm")
	startResponse := httptest.NewRecorder()
	startPlayCampaign(startResponse, startRequest)
	if startResponse.Code != http.StatusOK {
		t.Fatalf("start failed: %d %s", startResponse.Code, startResponse.Body.String())
	}
	turnRequest := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/turn", nil)
	turnRequest.SetPathValue("id", "play-1")
	turnRequest.Header.Set("Authorization", "Bearer session-player-a")
	turnResponse := httptest.NewRecorder()
	getPlayCampaignTurn(turnResponse, turnRequest)
	want := `{"campaign_id":"play-1","current_actor":"player-a","phase":"player","turn_number":1,"logical_deadline":2,"overdue":false,"queue":["player-a","dm","player-b","dm"]}` + "\n"
	if turnResponse.Code != http.StatusOK || turnResponse.Body.String() != want {
		t.Fatalf("unexpected turn queue: %d %s", turnResponse.Code, turnResponse.Body.String())
	}
}

func TestNudgePlayCampaignTurn(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'player-a')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	nudge := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/turn/nudge", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		nudgePlayCampaignTurn(response, req)
		return response
	}
	if response := nudge("Bearer session-player-a", `{"message":"Please act."}`); response.Code != http.StatusForbidden {
		t.Fatalf("player nudge returned %d", response.Code)
	}
	if response := nudge("Bearer session-dm", `{"message":" "}`); response.Code != http.StatusBadRequest {
		t.Fatalf("blank nudge returned %d", response.Code)
	}
	for count, message := range []string{"Please act.", "Still waiting."} {
		response := nudge("Bearer session-dm", `{"message":"`+message+`"}`)
		want := `{"actor":"dm","target":"player-a","message":"` + message + `","nudge_count":` + strconv.Itoa(count+1) + `}` + "\n"
		if response.Code != http.StatusCreated || response.Body.String() != want {
			t.Fatalf("unexpected nudge response: %d %s", response.Code, response.Body.String())
		}
	}
}

func TestAppendNarration(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	if _, err := currentDB().Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'lobby', 2)`); err != nil {
		t.Fatal(err)
	}
	narrate := func(token, text string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/narrations", strings.NewReader(text))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		appendNarration(response, req)
		return response
	}
	if response := narrate("Bearer session-aria", `{"text":"The road darkens."}`); response.Code != http.StatusForbidden {
		t.Fatalf("player narration returned %d", response.Code)
	}
	for _, test := range []struct {
		text string
		want string
	}{
		{`{"text":"The road darkens."}`, "{\"sequence\":1,\"kind\":\"narration\",\"actor\":\"dm\",\"text\":\"The road darkens.\"}\n"},
		{`{"text":"A raven calls."}`, "{\"sequence\":2,\"kind\":\"narration\",\"actor\":\"dm\",\"text\":\"A raven calls.\"}\n"},
	} {
		response := narrate("Bearer session-dm", test.text)
		if response.Code != http.StatusCreated || response.Body.String() != test.want {
			t.Fatalf("unexpected narration response: %d %s", response.Code, response.Body.String())
		}
	}
}

func TestRestPlayCampaignTurn(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order, hp_current, hp_max) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1, 9, 20)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Bryn', 'cleric', 2)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'player-a')`,
		`INSERT INTO play_campaign_narrations(campaign_id, sequence, text) VALUES ('play-1', 7, 'The party makes camp.')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	rest := func(token, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/turn/rest", strings.NewReader(body))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		restPlayCampaignTurn(response, req)
		return response
	}
	if response := rest("Bearer session-player-a", `{"type":"nap"}`); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid rest returned %d", response.Code)
	}
	if response := rest("Bearer session-player-b", `{"type":"long"}`); response.Code != http.StatusConflict {
		t.Fatalf("waiting player returned %d", response.Code)
	}
	response := rest("Bearer session-player-a", `{"type":"long"}`)
	want := `{"sequence":8,"kind":"rest","actor":"player-a","type":"long","hp_current":20,"hp_max":20,"next_actor":"dm"}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected rest response: %d %s", response.Code, response.Body.String())
	}
	var hp int
	if err := db.QueryRow(`SELECT hp_current FROM play_campaign_members WHERE campaign_id = 'play-1' AND username = 'player-a'`).Scan(&hp); err != nil || hp != 20 {
		t.Fatalf("long rest did not persist healed HP: %d, %v", hp, err)
	}
	if response := rest("Bearer session-player-a", `{"type":"short"}`); response.Code != http.StatusConflict {
		t.Fatalf("completed player returned %d", response.Code)
	}
	resolutionRequest := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/resolutions", strings.NewReader(`{"text":"Morning comes."}`))
	resolutionRequest.SetPathValue("id", "play-1")
	resolutionRequest.Header.Set("Authorization", "Bearer session-dm")
	resolutionResponse := httptest.NewRecorder()
	submitPlayResolution(resolutionResponse, resolutionRequest)
	resolutionWant := `{"sequence":9,"kind":"resolution","actor":"dm","text":"Morning comes.","next_actor":"player-b","turn_number":2}` + "\n"
	if resolutionResponse.Code != http.StatusCreated || resolutionResponse.Body.String() != resolutionWant {
		t.Fatalf("resolution after rest did not advance queue: %d %s", resolutionResponse.Code, resolutionResponse.Body.String())
	}
}

func TestSubmitPlayResolutionAdvancesAfterTravel(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Bryn', 'cleric', 2)`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'dm')`,
		`INSERT INTO play_campaign_actions(campaign_id, sequence, actor, type, text) VALUES ('play-1', 1, 'player-a', 'search', 'I search.')`,
		`INSERT INTO play_campaign_locations(campaign_id, id, name) VALUES ('play-1', 'cave', 'Cave')`,
		`INSERT INTO play_campaign_travels(campaign_id, sequence, actor, destination_id, travel_turns) VALUES ('play-1', 2, 'player-b', 'cave', 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/resolutions", strings.NewReader(`{"text":"The cave awaits."}`))
	req.SetPathValue("id", "play-1")
	req.Header.Set("Authorization", "Bearer session-dm")
	response := httptest.NewRecorder()
	submitPlayResolution(response, req)
	want := `{"sequence":3,"kind":"resolution","actor":"dm","text":"The cave awaits.","next_actor":"player-a","turn_number":2}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("resolution after travel did not advance queue: %d %s", response.Code, response.Body.String())
	}
}

func TestSubmitPlayActionRequiresActivePlayer(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Bryn', 'cleric', 2)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	action := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/actions", strings.NewReader(`{"type":"search","text":"I examine the trail."}`))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		submitPlayAction(response, req)
		return response
	}
	if response := action("Bearer session-player-b"); response.Code != http.StatusConflict {
		t.Fatalf("waiting player returned %d", response.Code)
	}
	if response := action("Bearer session-dm"); response.Code != http.StatusConflict {
		t.Fatalf("DM returned %d", response.Code)
	}
	response := action("Bearer session-player-a")
	want := `{"sequence":1,"kind":"action","actor":"player-a","type":"search","text":"I examine the trail.","next_actor":"dm"}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected action response: %d %s", response.Code, response.Body.String())
	}
	if response := action("Bearer session-player-a"); response.Code != http.StatusConflict {
		t.Fatalf("completed player returned %d", response.Code)
	}
}

func TestSubmitPlayResolutionRequiresActiveOwner(t *testing.T) {
	if err := initializeStorage(filepath.Join(t.TempDir(), "game.db")); err != nil {
		t.Fatal(err)
	}
	defer func() {
		storage.Lock()
		_ = storage.db.Close()
		storage.db = nil
		storage.initialized = false
		storage.Unlock()
	}()
	db := currentDB()
	for _, statement := range []string{
		`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES ('play-1', 'Ashen Road', 'dm', 'active', 2)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-a', 'char-a', 'Aria', 'rogue', 1)`,
		`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, join_order) VALUES ('play-1', 'player-b', 'char-b', 'Bryn', 'cleric', 2)`,
		`INSERT INTO play_campaign_actions(campaign_id, sequence, actor, type, text) VALUES ('play-1', 1, 'player-a', 'search', 'I examine the trail.')`,
		`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES ('play-1', 'dm')`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	resolution := func(token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/play/campaigns/play-1/resolutions", strings.NewReader(`{"text":"The trail leads east."}`))
		req.SetPathValue("id", "play-1")
		req.Header.Set("Authorization", token)
		response := httptest.NewRecorder()
		submitPlayResolution(response, req)
		return response
	}
	if response := resolution("Bearer session-player-a"); response.Code != http.StatusConflict {
		t.Fatalf("player resolution returned %d", response.Code)
	}
	response := resolution("Bearer session-dm")
	want := `{"sequence":2,"kind":"resolution","actor":"dm","text":"The trail leads east.","next_actor":"player-b","turn_number":2}` + "\n"
	if response.Code != http.StatusCreated || response.Body.String() != want {
		t.Fatalf("unexpected resolution response: %d %s", response.Code, response.Body.String())
	}
	turnRequest := httptest.NewRequest(http.MethodGet, "/v1/play/campaigns/play-1/turn", nil)
	turnRequest.SetPathValue("id", "play-1")
	turnRequest.Header.Set("Authorization", "Bearer session-player-a")
	turnResponse := httptest.NewRecorder()
	getPlayCampaignTurn(turnResponse, turnRequest)
	if turnResponse.Code != http.StatusOK || !strings.Contains(turnResponse.Body.String(), `"current_actor":"player-b"`) || !strings.Contains(turnResponse.Body.String(), `"turn_number":2`) {
		t.Fatalf("unexpected resolution turn state: %d %s", turnResponse.Code, turnResponse.Body.String())
	}
}
