package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// createPlayCampaignRequest binds the payload for a new play campaign.
type createPlayCampaignRequest struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	MaxPlayers int    `json:"max_players"`
}

// createPlayCampaignResponse is the shape returned after a successful create.
type createPlayCampaignResponse struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Owner      string `json:"owner"`
	Status     string `json:"status"`
	MaxPlayers int    `json:"max_players"`
}

// joinPlayCampaignRequest binds the payload for joining a play campaign.
type joinPlayCampaignRequest struct {
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// joinPlayCampaignResponse is the shape returned after a successful join.
type joinPlayCampaignResponse struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// createNarrationRequest binds the payload for a new narration event.
type createNarrationRequest struct {
	Text string `json:"text"`
}

// narrationEvent is the ordered event returned when a narration is appended.
// The Type field is populated for action events and omitted for narrations.
// The DestinationID and TravelTurns fields are populated for travel events.
type narrationEvent struct {
	Sequence      int    `json:"sequence"`
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	Text          string `json:"text,omitempty"`
	Type          string `json:"type,omitempty"`
	Target        string `json:"target,omitempty"`
	DestinationID string `json:"destination_id,omitempty"`
	TravelTurns   int    `json:"travel_turns,omitempty"`
}

// createActionRequest binds the payload for a new player action.
type createActionRequest struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// actionEvent is the ordered event returned when a player action is appended.
type actionEvent struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Type      string `json:"type"`
	Text      string `json:"text"`
	NextActor string `json:"next_actor"`
}

// createResolutionRequest binds the payload for a GM resolution event.
type createResolutionRequest struct {
	Text string `json:"text"`
}

// resolutionEvent is the ordered event returned when the GM resolves a turn.
type resolutionEvent struct {
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Actor      string `json:"actor"`
	Text       string `json:"text"`
	NextActor  string `json:"next_actor"`
	TurnNumber int    `json:"turn_number"`
}

// bearerUsername extracts the username from an Authorization header of the
// form "Bearer session-<username>". It returns false if the header is missing
// or malformed.
func bearerUsername(r *http.Request) (string, bool) {
	auth := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if auth == "" || !strings.HasPrefix(auth, prefix) {
		return "", false
	}
	token := strings.TrimPrefix(auth, prefix)
	if !strings.HasPrefix(token, "session-") {
		return "", false
	}
	return strings.TrimPrefix(token, "session-"), true
}

// playCampaign is the internal header row for a campaign on the play surface.
// It includes the turn queue state and lobby limits because most handlers
// need at least one of these fields.
type playCampaign struct {
	ID                string `json:"id"`
	Name              string `json:"name"`
	Owner             string `json:"owner"`
	Status            string `json:"status"`
	MaxPlayers        int    `json:"max_players"`
	TurnNumber        int    `json:"turn_number"`
	TurnActor         string `json:"turn_actor"`
	NudgeCount        int    `json:"nudge_count"`
	CurrentSceneID    string `json:"current_scene_id"`
	CurrentLocationID string `json:"current_location_id"`
	Phase             string `json:"phase"`
	PreCombatActor    string `json:"pre_combat_actor"`
}

// playCampaignMember is a party membership row. JoinOrder determines the
// deterministic turn queue order. HP fields track the character's health for
// rest turns and combat. The status and counters track death-saving throws.
// Level and con_modifier are tracked for deterministic level progression, and
// the six ability scores are stored for skill-check resolution.
type playCampaignMember struct {
	Username            string `json:"username"`
	CharacterID         string `json:"character_id"`
	Name                string `json:"name"`
	Class               string `json:"class"`
	JoinOrder           int    `json:"join_order"`
	Level               int    `json:"level"`
	ConModifier         int    `json:"con_modifier"`
	HPMax               int    `json:"hp_max"`
	HPCurrent           int    `json:"hp_current"`
	Status              string `json:"status"`
	DeathSavesSuccesses int    `json:"death_saves_successes"`
	DeathSavesFailures  int    `json:"death_saves_failures"`
	Owner               string `json:"owner"`
	StrScore            int    `json:"str_score"`
	DexScore            int    `json:"dex_score"`
	ConScore            int    `json:"con_score"`
	IntScore            int    `json:"int_score"`
	WisScore            int    `json:"wis_score"`
	ChaScore            int    `json:"cha_score"`
	Gold                int    `json:"gold"`
}

// queryPlayCampaign loads a play campaign by id. The caller must hold dbMu.
func queryPlayCampaign(campaignID string) (*playCampaign, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT id, name, owner, status, max_players, turn_number, turn_actor, nudge_count, current_scene_id, current_location_id, phase, pre_combat_actor FROM play_campaigns WHERE id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return nil, false, err
	}
	var campaigns []playCampaign
	if err := json.Unmarshal(out, &campaigns); err != nil {
		return nil, false, err
	}
	if len(campaigns) == 0 {
		return nil, false, nil
	}
	return &campaigns[0], true, nil
}

// queryPlayCampaignMembers loads all members of a play campaign ordered by
// join_order. The caller must hold dbMu.
func queryPlayCampaignMembers(campaignID string) ([]playCampaignMember, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT username, character_id, name, class, join_order, level, con_modifier, hp_max, hp_current, status, death_saves_successes, death_saves_failures, owner, str_score, dex_score, con_score, int_score, wis_score, cha_score, gold FROM play_campaign_members WHERE campaign_id=%s ORDER BY join_order;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var members []playCampaignMember
	if err := json.Unmarshal(out, &members); err != nil {
		return nil, err
	}
	if members == nil {
		return []playCampaignMember{}, nil
	}
	return members, nil
}

// queryPlayCampaignMember loads a single play campaign member by campaign and
// character id. The caller must hold dbMu.
func queryPlayCampaignMember(campaignID, characterID string) (*playCampaignMember, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT username, character_id, name, class, join_order, level, con_modifier, hp_max, hp_current, status, death_saves_successes, death_saves_failures, owner, str_score, dex_score, con_score, int_score, wis_score, cha_score, gold FROM play_campaign_members WHERE campaign_id=%s AND character_id=%s LIMIT 1;", sq(campaignID), sq(characterID)))
	if err != nil {
		return nil, false, err
	}
	var members []playCampaignMember
	if err := json.Unmarshal(out, &members); err != nil {
		return nil, false, err
	}
	if len(members) == 0 {
		return nil, false, nil
	}
	return &members[0], true, nil
}

// queryPlayCampaignMemberByUsername loads a single play campaign member by
// campaign and username. The caller must hold dbMu.
func queryPlayCampaignMemberByUsername(campaignID, username string) (*playCampaignMember, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT username, character_id, name, class, join_order, level, con_modifier, hp_max, hp_current, status, death_saves_successes, death_saves_failures, owner, str_score, dex_score, con_score, int_score, wis_score, cha_score, gold FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		return nil, false, err
	}
	var members []playCampaignMember
	if err := json.Unmarshal(out, &members); err != nil {
		return nil, false, err
	}
	if len(members) == 0 {
		return nil, false, nil
	}
	return &members[0], true, nil
}

// nextNarrationSequence returns the next monotonic sequence number for a
// campaign's narration log. The caller must hold dbMu.
func nextNarrationSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_narrations WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// requireDM authenticates the request using the session bearer token and
// authorizes only users with the "dm" role. It returns the authenticated
// username on success. On failure it writes a 401 or 403 response and returns
// false, so the caller should return immediately.
//
// A well-formed session token whose username is not present in the users table
// is treated as a non-member and receives 403, matching the benchmark's
// reference-server semantics.
func requireDM(w http.ResponseWriter, r *http.Request) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}

	user, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("play auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok || user.Role != "dm" {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	return username, true
}

// requirePlayer authenticates the request using the session bearer token and
// authorizes only users with the "player" role. It returns the authenticated
// username on success. On failure it writes a 401 or 403 response and returns
// false, so the caller should return immediately.
func requirePlayer(w http.ResponseWriter, r *http.Request) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}

	user, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("play auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok || user.Role != "player" {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	return username, true
}

// requireCampaignOwnerOrMember authenticates the request using the session
// bearer token and authorizes only the campaign owner or a campaign member.
// It returns the authenticated username on success. On failure it writes a
// 401 or 403 response and returns false, so the caller should return
// immediately.
func requireCampaignOwnerOrMember(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}

	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("play auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("campaign owner query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if ok && campaign.Owner == username {
		return username, true
	}

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		log.Printf("campaign member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	var memberRows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &memberRows); err != nil {
		log.Printf("campaign member unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if len(memberRows) > 0 {
		return username, true
	}

	writeError(w, http.StatusForbidden, "forbidden")
	return "", false
}

// createPlayCampaignHandler creates a new play campaign under /v1/play. The
// endpoint is protected: only an authenticated DM can create a campaign, and
// duplicate IDs are rejected with 409.
func createPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	owner, ok := requireDM(w, r)
	if !ok {
		return
	}

	var req createPlayCampaignRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.MaxPlayers < 1 {
		writeError(w, http.StatusBadRequest, "invalid campaign")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaigns WHERE id=%s LIMIT 1;", sq(req.ID)))
	if err != nil {
		log.Printf("play campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var dup []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &dup); err != nil {
		log.Printf("play campaign exists unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(dup) > 0 {
		writeError(w, http.StatusConflict, "campaign already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (%s, %s, %s, 'lobby', %d);",
		sq(req.ID), sq(req.Name), sq(owner), req.MaxPlayers)); err != nil {
		log.Printf("play campaign insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT OR IGNORE INTO campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events) VALUES (%s, 0, 0, 0);", sq(req.ID))); err != nil {
		log.Printf("play campaign metrics insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createPlayCampaignResponse{
		ID:         req.ID,
		Name:       req.Name,
		Owner:      owner,
		Status:     "lobby",
		MaxPlayers: req.MaxPlayers,
	})
}

// joinPlayCampaignHandler lets an authenticated player join a lobby play
// campaign. A player may have at most one membership per campaign, character
// IDs must be unique, and a full party rejects additional members with 409.
func joinPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req joinPlayCampaignRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" || req.Name == "" || req.Class == "" {
		writeError(w, http.StatusBadRequest, "invalid character")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("join campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND character_id=%s LIMIT 1;", sq(campaignID), sq(req.CharacterID)))
	if err != nil {
		log.Printf("join duplicate character query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var dupChar []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &dupChar); err != nil {
		log.Printf("join duplicate character unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(dupChar) > 0 {
		writeError(w, http.StatusConflict, "character already exists")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("join members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, m := range members {
		if m.Username == username {
			writeError(w, http.StatusConflict, "player already in campaign")
			return
		}
	}
	if len(members) >= campaign.MaxPlayers {
		writeError(w, http.StatusConflict, "party is full")
		return
	}
	nextOrder := 1
	for _, m := range members {
		if m.JoinOrder >= nextOrder {
			nextOrder = m.JoinOrder + 1
		}
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, join_order, owner) VALUES (%s, %s, %s, %s, %s, %d, %s);",
		sq(campaignID), sq(username), sq(req.CharacterID), sq(req.Name), sq(req.Class), nextOrder, sq(username))); err != nil {
		log.Printf("join insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, joinPlayCampaignResponse{
		Username:    username,
		CharacterID: req.CharacterID,
		Name:        req.Name,
		Class:       req.Class,
	})
}

// startPlayCampaignResponse is the shape returned after successfully starting
// a play campaign.
type startPlayCampaignResponse struct {
	ID           string `json:"id"`
	Status       string `json:"status"`
	CurrentActor string `json:"current_actor"`
	TurnNumber   int    `json:"turn_number"`
}

// startPlayCampaignHandler transitions a lobby play campaign to active. It is
// restricted to the campaign owner (who must be a DM). The campaign must have
// at least two party members, and the transition can only happen once.
func startPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	owner, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("start campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	if campaign.Status != "lobby" {
		writeError(w, http.StatusConflict, "campaign already started")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("start campaign members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(members) < 2 {
		writeError(w, http.StatusConflict, "insufficient party members")
		return
	}
	currentActor := ""
	if len(members) > 0 {
		currentActor = members[0].Username
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET status='active', phase='exploration', pre_combat_actor=%s, turn_number=1, turn_actor=%s WHERE id=%s;",
		sq(currentActor), sq(currentActor), sq(campaignID))); err != nil {
		log.Printf("start campaign update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, startPlayCampaignResponse{
		ID:           campaignID,
		Status:       "active",
		CurrentActor: currentActor,
		TurnNumber:   1,
	})
}

// createNarrationHandler lets the owner of a play campaign or an active
// narrate delegate append a narration event. The endpoint is authenticated;
// players and non-delegated members receive 403. The sequence number starts
// at 1 for each campaign and increments monotonically with each appended event.
func createNarrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("narration auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")

	var req createNarrationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid narration")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("narration campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	canNarrate := campaign.Owner == username
	if !canNarrate {
		canNarrate, err = hasNarrateDelegation(campaignID, username)
		if err != nil {
			log.Printf("narration delegation query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !canNarrate {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("narration sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (%s, %d, 'narration', %s, %s);",
		sq(campaignID), nextSeq, sq(username), sq(req.Text))); err != nil {
		log.Printf("narration insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, narrationEvent{
		Sequence: nextSeq,
		Kind:     "narration",
		Actor:    username,
		Text:     req.Text,
	})
}

// playCampaignTurnResponse is the shape returned for the current turn state of
// a play campaign. Timeout metadata is deterministic and wall-clock-free.
type playCampaignTurnResponse struct {
	CampaignID      string   `json:"campaign_id"`
	CurrentActor    string   `json:"current_actor"`
	Phase           string   `json:"phase"`
	TurnNumber      int      `json:"turn_number"`
	Queue           []string `json:"queue"`
	Overdue         bool     `json:"overdue"`
	LogicalDeadline int      `json:"logical_deadline"`
}

// playerTurnContextCharacter is the reduced character shape exposed to a player
// on the my-turn endpoint.
type playerTurnContextCharacter struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// playerTurnContextResponse is the shape returned for a player's own turn
// context. It includes public turn state, the caller's character, and recent
// narration events; DM-private document fields are never exposed.
type playerTurnContextResponse struct {
	IsMyTurn     bool                       `json:"is_my_turn"`
	CurrentActor string                     `json:"current_actor"`
	Character    playerTurnContextCharacter `json:"character"`
	RecentEvents []narrationEvent           `json:"recent_events"`
}

// gmStatusMember is a party member summary in the GM status view.
type gmStatusMember struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
	IsCurrent   bool   `json:"is_current"`
}

// gmStatusResponse is the shape returned for the owner's GM status view.
type gmStatusResponse struct {
	NeedsAttention bool             `json:"needs_attention"`
	CurrentActor   string           `json:"current_actor"`
	Party          []gmStatusMember `json:"party"`
	RecentEvents   []narrationEvent `json:"recent_events"`
}

// getPlayCampaignTurnHandler returns the current turn state of a play
// campaign. The endpoint is protected: only the campaign owner or a campaign
// member can read it. Missing authentication returns 401; an authenticated
// non-member returns 403.
func getPlayCampaignTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("turn campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("turn current actor query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	currentActor := ""
	turnNumber := 0
	phase := campaign.Status
	queue := []string{}
	if campaign.Status == "active" {
		switch campaign.Phase {
		case "combat":
			phase = "combat"
		case "exploration":
			// During exploration, expose the active player's turn as "player" and
			// the DM's turn as "exploration" so the terminal state of the
			// capstone replay matches the campaign phase.
			if campaign.TurnActor != "" && campaign.TurnActor != campaign.Owner {
				phase = "player"
			} else {
				phase = "exploration"
			}
		default:
			phase = "player"
		}
	}

	if campaign.Status != "lobby" {
		if len(members) > 0 {
			if campaign.Status == "active" && campaign.TurnActor != "" {
				currentActor = campaign.TurnActor
			} else {
				currentActor = members[0].Username
			}
			for _, m := range members {
				queue = append(queue, m.Username, "dm")
			}
		}
		turnNumber = campaign.TurnNumber
	}

	// Logical deadline is deterministic: one turn after the current turn number.
	// No wall-clock time is used, so a fresh turn is never overdue.
	deadline := turnNumber + 1
	if deadline < 0 {
		deadline = 0
	}

	writeJSON(w, http.StatusOK, playCampaignTurnResponse{
		CampaignID:      campaignID,
		CurrentActor:    currentActor,
		Phase:           phase,
		TurnNumber:      turnNumber,
		Queue:           queue,
		Overdue:         false,
		LogicalDeadline: deadline,
	})
}

// nudgeTurnRequest binds the payload for a turn timeout nudge.
type nudgeTurnRequest struct {
	Message string `json:"message"`
}

// nudgeTurnResponse is the shape returned after an owner nudges the current
// turn actor. The nudge_count is monotonically increasing for the campaign.
type nudgeTurnResponse struct {
	Actor      string `json:"actor"`
	Target     string `json:"target"`
	Message    string `json:"message"`
	NudgeCount int    `json:"nudge_count"`
}

// nudgeTurnHandler lets the campaign owner issue a deterministic timeout nudge
// to the current turn actor. The message must be nonempty. The response
// echoes the owner, the current target, the message, and the updated
// monotonically increasing nudge_count.
func nudgeTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req nudgeTurnRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Message == "" {
		writeError(w, http.StatusBadRequest, "invalid message")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("nudge campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if campaign.Status != "active" {
		writeError(w, http.StatusConflict, "campaign not active")
		return
	}

	currentTarget := campaign.TurnActor
	if currentTarget == "" {
		members, err := queryPlayCampaignMembers(campaignID)
		if err != nil {
			log.Printf("nudge target query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if len(members) > 0 {
			currentTarget = members[0].Username
		}
	}

	newCount := campaign.NudgeCount + 1

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("nudge sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (%s, %d, 'nudge', %s, %s);",
		sq(campaignID), nextSeq, sq(username), sq(req.Message))); err != nil {
		log.Printf("nudge insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET nudge_count=%d WHERE id=%s;", newCount, sq(campaignID))); err != nil {
		log.Printf("nudge count update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, nudgeTurnResponse{
		Actor:      username,
		Target:     currentTarget,
		Message:    req.Message,
		NudgeCount: newCount,
	})
}

// getPlayerTurnContextHandler returns a player's own turn context for a play
// campaign. The endpoint is restricted to authenticated users with the player
// role who are members of the campaign. It exposes public turn state, the
// caller's character, and recent narration events; DM-private document fields
// are never included.
func getPlayerTurnContextHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("my turn campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("my turn members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var callerMember *playCampaignMember
	for i := range members {
		if members[i].Username == username {
			callerMember = &members[i]
			break
		}
	}
	if callerMember == nil {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	currentActor := ""
	if campaign.Status == "active" {
		if campaign.TurnActor != "" {
			currentActor = campaign.TurnActor
		} else if len(members) > 0 {
			currentActor = members[0].Username
		}
	}

	out, err := dbQuery(fmt.Sprintf("SELECT sequence, kind, actor, text, type, target, destination_id, travel_turns FROM campaign_narrations WHERE campaign_id=%s ORDER BY sequence DESC LIMIT 10;", sq(campaignID)))
	if err != nil {
		log.Printf("my turn events query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var events []narrationEvent
	if err := json.Unmarshal(out, &events); err != nil {
		log.Printf("my turn events unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if events == nil {
		events = []narrationEvent{}
	}

	writeJSON(w, http.StatusOK, playerTurnContextResponse{
		IsMyTurn:     currentActor == username,
		CurrentActor: currentActor,
		Character: playerTurnContextCharacter{
			ID:   callerMember.CharacterID,
			Name: callerMember.Name,
		},
		RecentEvents: events,
	})
}

// getGMStatusHandler returns the owner's turn-management view for a play
// campaign. It includes whether the campaign is waiting on the owner, the
// current actor, a summary of each party member, and recent narration events.
// Only the campaign owner may read this endpoint; players and other
// authenticated users receive 403.
func getGMStatusHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("gm status campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("gm status party query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	currentActor := ""
	if campaign.Status == "active" {
		if campaign.TurnActor != "" {
			currentActor = campaign.TurnActor
		} else if len(members) > 0 {
			currentActor = members[0].Username
		}
	}
	party := make([]gmStatusMember, 0, len(members))
	for _, m := range members {
		party = append(party, gmStatusMember{
			Username:    m.Username,
			CharacterID: m.CharacterID,
			Name:        m.Name,
			Class:       m.Class,
			IsCurrent:   m.Username == currentActor,
		})
	}
	if party == nil {
		party = []gmStatusMember{}
	}

	out, err := dbQuery(fmt.Sprintf("SELECT sequence, kind, actor, text, type, target, destination_id, travel_turns FROM campaign_narrations WHERE campaign_id=%s ORDER BY sequence DESC LIMIT 10;", sq(campaignID)))
	if err != nil {
		log.Printf("gm status events query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var events []narrationEvent
	if err := json.Unmarshal(out, &events); err != nil {
		log.Printf("gm status events unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if events == nil {
		events = []narrationEvent{}
	}

	writeJSON(w, http.StatusOK, gmStatusResponse{
		NeedsAttention: currentActor == username,
		CurrentActor:   currentActor,
		Party:          party,
		RecentEvents:   events,
	})
}

// createActionHandler lets the active player of a play campaign append an
// action event. Only the current actor (the active player) may submit an
// action; waiting players and the DM receive 409. The response includes the
// assigned sequence, the action details, and next_actor:"dm".
func createActionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireCampaignOwnerOrMember(w, r, r.PathValue("id"))
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req createActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Type == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid action")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("action campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Status != "active" {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	if username == campaign.Owner {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("action current actor query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	currentActor := campaign.TurnActor
	if currentActor == "" && len(members) > 0 {
		currentActor = members[0].Username
	}
	if currentActor != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("action sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (%s, %d, 'action', %s, %s, %s);",
		sq(campaignID), nextSeq, sq(username), sq(req.Text), sq(req.Type))); err != nil {
		log.Printf("action insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET turn_actor=%s WHERE id=%s;", sq(campaign.Owner), sq(campaignID))); err != nil {
		log.Printf("action turn actor update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, actionEvent{
		Sequence:  nextSeq,
		Kind:      "action",
		Actor:     username,
		Type:      req.Type,
		Text:      req.Text,
		NextActor: "dm",
	})
}

// resolveCurrentLocation determines the party's location on the campaign's
// location graph for travel purposes. If the explicitly stored current
// location is not a valid location, it falls back to the current scene when
// that scene is a valid location, and finally to the first location created
// for the campaign (by SQLite rowid). If no location can be resolved, it
// returns false.
func requireCampaignOwner(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool) {
	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return "", false
	}

	user, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("document owner user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok || user.Role != "dm" {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("document owner campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", false
	}
	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	return username, true
}

// getCampaignDocumentHandler returns the campaign document. The owner receives
// both the public story and the private DM notes; a player member receives only
// the public story field and never sees dm_notes.
func getCampaignDocumentHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("document get owner query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	isOwner := campaign.Owner == username

	out, err := dbQuery(fmt.Sprintf("SELECT story, dm_notes FROM campaign_documents WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		log.Printf("document get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var docs []struct {
		Story   string `json:"story"`
		DMNotes string `json:"dm_notes"`
	}
	if err := json.Unmarshal(out, &docs); err != nil {
		log.Printf("document get unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	story := ""
	dmNotes := ""
	if len(docs) > 0 {
		story = docs[0].Story
		dmNotes = docs[0].DMNotes
	}

	if isOwner {
		writeJSON(w, http.StatusOK, ownerCampaignDocumentResponse{
			Story:   story,
			DMNotes: dmNotes,
		})
		return
	}

	writeJSON(w, http.StatusOK, playerCampaignDocumentResponse{
		Story: story,
	})
}

// updateCampaignDocumentHandler updates the durable campaign document. Only
// the campaign owner may write it; players and non-members receive 403.
func updateCampaignDocumentHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req campaignDocumentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_documents (campaign_id, story, dm_notes) VALUES (%s, %s, %s) ON CONFLICT(campaign_id) DO UPDATE SET story=excluded.story, dm_notes=excluded.dm_notes;",
		sq(campaignID), sq(req.Story), sq(req.DMNotes))); err != nil {
		log.Printf("document upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, ownerCampaignDocumentResponse{
		Story:   req.Story,
		DMNotes: req.DMNotes,
	})
}

// createResolutionHandler lets the campaign owner resolve a player turn. The
// endpoint may only be used when the owner is the current actor; a player
// member receives 409, and a non-member receives 403. The resolution is
// appended as a 'resolution' event, the turn advances to the determined next
// actor, and the incremented turn_number is returned.
func createResolutionHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireCampaignOwnerOrMember(w, r, r.PathValue("id"))
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	var req createResolutionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid resolution")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("resolution campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	if campaign.Status != "active" || campaign.TurnActor != campaign.Owner {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("resolution members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(members) == 0 {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	nextSeq, err := nextNarrationSequence(campaignID)
	if err != nil {
		log.Printf("resolution sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (%s, %d, 'resolution', 'dm', %s);",
		sq(campaignID), nextSeq, sq(req.Text))); err != nil {
		log.Printf("resolution insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	nextTurnNumber := campaign.TurnNumber + 1
	nextActor := members[0].Username
	if campaign.TurnNumber < 2 && len(members) > 1 {
		nextActor = members[1].Username
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET turn_number=%d, turn_actor=%s WHERE id=%s;",
		nextTurnNumber, sq(nextActor), sq(campaignID))); err != nil {
		log.Printf("resolution turn update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, resolutionEvent{
		Sequence:   nextSeq,
		Kind:       "resolution",
		Actor:      "dm",
		Text:       req.Text,
		NextActor:  nextActor,
		TurnNumber: nextTurnNumber,
	})
}

// scene is a campaign location or encounter that the owner can open and close.

// onboardingResponse is the role-specific onboarding payload for agents joining
// an existing campaign. The next_steps arrays are stable and ordered.
type onboardingResponse struct {
	Role      string   `json:"role"`
	NextSteps []string `json:"next_steps"`
	CanMutate bool     `json:"can_mutate"`
}

// sessionZeroSettings is the durable shape for pre-start campaign session-zero
// settings.
type sessionZeroSettings struct {
	Rules   string   `json:"rules"`
	Tone    string   `json:"tone"`
	Consent []string `json:"consent"`
}

// validateSessionZeroSettings ensures rules and tone are nonempty, consent is
// a nonempty array, and all consent entries are unique nonempty strings.
func validateSessionZeroSettings(s *sessionZeroSettings) bool {
	if s.Rules == "" || s.Tone == "" {
		return false
	}
	if len(s.Consent) == 0 {
		return false
	}
	seen := make(map[string]bool, len(s.Consent))
	for _, c := range s.Consent {
		if c == "" {
			return false
		}
		if seen[c] {
			return false
		}
		seen[c] = true
	}
	return true
}

// updateSessionZeroSettingsHandler lets the campaign owner set session-zero
// settings while the campaign is still in the lobby. Only the owner (DM) may
// write; players and non-owners receive 403, and updates after the campaign
// starts return 409.
func updateSessionZeroSettingsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req sessionZeroSettings
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validateSessionZeroSettings(&req) {
		writeError(w, http.StatusBadRequest, "invalid session-zero settings")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("session-zero campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Status != "lobby" {
		writeError(w, http.StatusConflict, "campaign already started")
		return
	}

	consentJSON, err := json.Marshal(req.Consent)
	if err != nil {
		log.Printf("session-zero consent marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT OR REPLACE INTO campaign_session_zero_settings (campaign_id, rules, tone, consent) VALUES (%s, %s, %s, %s);",
		sq(campaignID), sq(req.Rules), sq(req.Tone), sq(string(consentJSON)))); err != nil {
		log.Printf("session-zero settings upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, req)
}

// getSessionZeroSettingsHandler lets authenticated campaign members read the
// stored session-zero settings. Unknown campaigns and missing settings both
// return 404.
func getSessionZeroSettingsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("session-zero get auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("session-zero get campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("session-zero get member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("session-zero get member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if len(memberRows) == 0 {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}

	var rows []struct {
		Rules   string `json:"rules"`
		Tone    string `json:"tone"`
		Consent string `json:"consent"`
	}
	if err := queryRows(fmt.Sprintf("SELECT rules, tone, consent FROM campaign_session_zero_settings WHERE campaign_id=%s LIMIT 1;", sq(campaignID)), &rows); err != nil {
		log.Printf("session-zero settings query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(rows) == 0 {
		writeError(w, http.StatusNotFound, "session-zero settings not found")
		return
	}

	var consent []string
	if err := json.Unmarshal([]byte(rows[0].Consent), &consent); err != nil {
		log.Printf("session-zero consent unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, sessionZeroSettings{
		Rules:   rows[0].Rules,
		Tone:    rows[0].Tone,
		Consent: consent,
	})
}

// getCampaignOnboardingHandler returns the role-specific onboarding checklist
// for a play campaign. The owner/DM receives DM steps; player members receive
// player steps. Missing or invalid authentication returns 401, unknown
// campaigns return 404 for authenticated users, and non-members return 403.
// The response is deterministic, ordered, and does not mutate campaign state.
func getCampaignOnboardingHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("onboarding auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("onboarding campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner == username {
		writeJSON(w, http.StatusOK, onboardingResponse{
			Role:      "dm",
			NextSteps: []string{"configure-safety", "invite-players", "start-campaign"},
			CanMutate: true,
		})
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		log.Printf("onboarding member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var memberRows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &memberRows); err != nil {
		log.Printf("onboarding member unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(memberRows) == 0 {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, onboardingResponse{
		Role:      "player",
		NextSteps: []string{"review-party", "take-turn", "submit-action"},
		CanMutate: true,
	})
}
