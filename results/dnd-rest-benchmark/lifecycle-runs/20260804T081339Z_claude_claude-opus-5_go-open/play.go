package main

import (
	"database/sql"
	"errors"
	"log"
	"net/http"
	"strings"
)

// The /v1/play surface is the first authenticated area of the API. Everything
// else is open; here a request must carry
//
//	Authorization: Bearer session-<username>
//
// which is the same token /v1/auth/login mints. Tokens stay derived rather than
// stored, so the token itself names the actor: a well-formed token authenticates
// even when the username was never registered through /v1/auth/register. Play
// campaigns have no sign-up step, and an unknown name is a real identity that
// simply has no permissions yet.
//
// The two failure modes are kept strictly apart: 401 means "we cannot tell who
// you are", 403 means "we know who you are and you may not do this".

const bearerPrefix = "Bearer "
const sessionTokenPrefix = "session-"

// authenticate resolves the Authorization header to an actor. A missing header,
// a non-bearer scheme, and a token without a session-<username> shape are all
// indistinguishable to the caller: 401.
func authenticate(r *http.Request) (*user, bool) {
	header := r.Header.Get("Authorization")
	if !strings.HasPrefix(header, bearerPrefix) {
		return nil, false
	}
	token := strings.TrimSpace(strings.TrimPrefix(header, bearerPrefix))
	if !strings.HasPrefix(token, sessionTokenPrefix) {
		return nil, false
	}
	username := strings.TrimPrefix(token, sessionTokenPrefix)
	if username == "" {
		return nil, false
	}
	// A registered user carries the role it signed up with; anyone else gets the
	// role their name implies.
	if u, ok := getUser(username); ok {
		return u, true
	}
	return &user{Username: username, Role: roleForUsername(username)}, true
}

// roleForUsername is the fallback role for an actor with no users row. The DM
// seat is the name "dm" (or a "dm-" qualified variant); every other name plays.
func roleForUsername(username string) string {
	if username == "dm" || strings.HasPrefix(username, "dm-") {
		return "dm"
	}
	return "player"
}

// requireActor writes the 401 for an unauthenticated request so handlers only
// have to deal with the authorization question.
func requireActor(w http.ResponseWriter, r *http.Request) (*user, bool) {
	u, ok := authenticate(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return nil, false
	}
	return u, true
}

// requireRole narrows an authenticated actor to one role, reporting 403 when the
// actor is real but not permitted.
func requireRole(w http.ResponseWriter, u *user, role string) bool {
	if u.Role == role {
		return true
	}
	writeError(w, http.StatusForbidden, "forbidden")
	return false
}

// ---------- POST /v1/play/campaigns ----------

type playCampaignRequest struct {
	ID         *string `json:"id"`
	Name       *string `json:"name"`
	MaxPlayers *int    `json:"max_players"`
}

type playCampaignResponse struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Owner      string `json:"owner"`
	Status     string `json:"status"`
	MaxPlayers int    `json:"max_players"`
}

// The play campaign lifecycle: created in the lobby, moved to active exactly
// once by the owning DM.
const (
	playCampaignStatusLobby  = "lobby"
	playCampaignStatusActive = "active"
)

// playCampaignMinParty is the party size a campaign needs before it can start.
const playCampaignMinParty = 2

func handleCreatePlayCampaign(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	// Credentials are checked before the body: an anonymous caller learns
	// nothing about which payloads would have been valid.
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if !requireRole(w, actor, "dm") {
		return
	}

	var req playCampaignRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	name, ok := requireField(w, req.Name, "name")
	if !ok {
		return
	}
	out := playCampaignResponse{
		ID:     id,
		Name:   name,
		Owner:  actor.Username,
		Status: playCampaignStatusLobby,
	}
	if req.MaxPlayers != nil {
		out.MaxPlayers = *req.MaxPlayers
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if exists, err := playCampaignExists(id); err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "play campaign id already exists")
		return
	}
	if _, err := db.Exec(
		`INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)`,
		out.ID, out.Name, out.Owner, out.Status, out.MaxPlayers,
	); err != nil {
		// A primary-key collision that raced the check above; still a conflict.
		log.Printf("play campaign insert failed: %v", err)
		writeError(w, http.StatusConflict, "play campaign id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

func playCampaignExists(id string) (bool, error) {
	return rowExists(`SELECT 1 FROM play_campaigns WHERE id = ?`, id)
}

// ---------- POST /v1/play/campaigns/{id}/members ----------

type playMemberRequest struct {
	CharacterID *string `json:"character_id"`
	Name        *string `json:"name"`
	Class       *string `json:"class"`
}

type playMemberResponse struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// handleJoinPlayCampaign seats one player in a lobby campaign. The seat is the
// actor: a player joins as themselves and cannot enroll anyone else, so the
// body carries only the character they bring.
//
// Three distinct situations all report 409, because each one means the party
// cannot take this request as it stands: the player already holds a seat, the
// character id is already in the party, or the party is full. A campaign that
// has left the lobby is the same shape of failure — the seat is gone, not
// forbidden.
func handleJoinPlayCampaign(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if !requireRole(w, actor, "player") {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	var req playMemberRequest
	if !decodeBody(w, r, &req) {
		return
	}
	characterID, ok := requireField(w, req.CharacterID, "character_id")
	if !ok {
		return
	}
	name, ok := requireField(w, req.Name, "name")
	if !ok {
		return
	}
	class, ok := requireField(w, req.Class, "class")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var status string
	var maxPlayers int
	err := db.QueryRow(`SELECT status, max_players FROM play_campaigns WHERE id = ?`, campaignID).
		Scan(&status, &maxPlayers)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	if status != playCampaignStatusLobby {
		writeError(w, http.StatusConflict, "play campaign is not accepting members")
		return
	}

	if seated, err := rowExists(
		`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`,
		campaignID, actor.Username,
	); err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	} else if seated {
		writeError(w, http.StatusConflict, "player already joined this campaign")
		return
	}
	if taken, err := rowExists(
		`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`,
		campaignID, characterID,
	); err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	} else if taken {
		writeError(w, http.StatusConflict, "character id already joined this campaign")
		return
	}

	// max_players of 0 means the creator named no limit, so the party is never
	// full; any positive value is a hard cap.
	var seated int
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?`, campaignID,
	).Scan(&seated); err != nil {
		writeStorageFailure(w, "play membership count failed", err)
		return
	}
	if maxPlayers > 0 && seated >= maxPlayers {
		writeError(w, http.StatusConflict, "play campaign party is full")
		return
	}

	position, err := nextPosition("play_campaign_members", campaignID)
	if err != nil {
		writeStorageFailure(w, "play membership position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO play_campaign_members (campaign_id, username, position, character_id, name, class)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, actor.Username, position, characterID, name, class,
	); err != nil {
		// A unique-constraint violation that raced the checks above.
		log.Printf("play membership insert failed: %v", err)
		writeError(w, http.StatusConflict, "player already joined this campaign")
		return
	}
	writeJSON(w, http.StatusCreated, playMemberResponse{
		Username:    actor.Username,
		CharacterID: characterID,
		Name:        name,
		Class:       class,
	})
}

// ---------- POST /v1/play/campaigns/{id}/start ----------

type playStartResponse struct {
	ID           string `json:"id"`
	Status       string `json:"status"`
	CurrentActor string `json:"current_actor"`
	TurnNumber   int    `json:"turn_number"`
}

// handleStartPlayCampaign takes a lobby campaign live. Only the DM who created
// it may do so: any other actor is a real identity without the permission, so
// 403 — including a DM who owns a different table.
//
// Starting is idempotent in the sense that it can succeed only once. A campaign
// that is already active, and one whose party is still short of
// playCampaignMinParty, both report 409: the request is well-formed and
// permitted but the campaign is not in a state that can accept it.
//
// The first turn belongs to the player who joined first, which is the lowest
// position in the party — the same ordering the members endpoint records.
func handleStartPlayCampaign(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	if !requireRole(w, actor, "dm") {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var owner, status string
	err := db.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).
		Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	if owner != actor.Username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if status != playCampaignStatusLobby {
		writeError(w, http.StatusConflict, "play campaign is not in the lobby")
		return
	}

	var currentActor string
	err = db.QueryRow(
		`SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY position LIMIT 1`,
		campaignID,
	).Scan(&currentActor)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	}

	var seated int
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?`, campaignID,
	).Scan(&seated); err != nil {
		writeStorageFailure(w, "play membership count failed", err)
		return
	}
	if seated < playCampaignMinParty {
		writeError(w, http.StatusConflict, "play campaign needs at least two party members")
		return
	}

	// Turn 1 opens at whatever the log already stands at, so pre-start narration
	// does not eat into the first turn's budget.
	startedSeq, err := latestPlayEventSequence(campaignID)
	if err != nil {
		writeStorageFailure(w, "play event sequence lookup failed", err)
		return
	}

	// The status guard is repeated in the UPDATE so two concurrent starts cannot
	// both write the first turn; the loser sees zero rows affected.
	result, err := db.Exec(
		`UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = 1, turn_started_seq = ?
		 WHERE id = ? AND status = ?`,
		playCampaignStatusActive, currentActor, startedSeq, campaignID, playCampaignStatusLobby,
	)
	if err != nil {
		writeStorageFailure(w, "play campaign start failed", err)
		return
	}
	if affected, err := result.RowsAffected(); err == nil && affected == 0 {
		writeError(w, http.StatusConflict, "play campaign is not in the lobby")
		return
	}
	writeJSON(w, http.StatusOK, playStartResponse{
		ID:           campaignID,
		Status:       playCampaignStatusActive,
		CurrentActor: currentActor,
		TurnNumber:   1,
	})
}

// ---------- POST /v1/play/campaigns/{id}/narrations ----------

type playNarrationRequest struct {
	Text *string `json:"text"`
}

// playEventResponse is the wire shape of one entry in a campaign's event log.
// Narration is the first kind to write one; later kinds reuse the same shape so
// the log stays uniform when it is read back.
// Type carries the flavour of an action event and NextActor the seat the clock
// moved to; both are omitted for kinds that have neither, so a narration reads
// exactly as it did before actions existed.
type playEventResponse struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Text      string `json:"text"`
	Type      string `json:"type,omitempty"`
	NextActor string `json:"next_actor,omitempty"`
}

const (
	playEventKindNarration  = "narration"
	playEventKindAction     = "action"
	playEventKindResolution = "resolution"
)

// handleNarratePlayCampaign appends narration to a campaign's event log. Only
// the owning DM narrates: a player is a real identity without the permission
// (403), and so is a DM who owns a different table.
//
// The log is append-only and numbered per campaign starting at 1, so a
// narration never renumbers or replaces an earlier event.
func handleNarratePlayCampaign(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	// Permission is settled before the body is read, so an actor who may not
	// narrate learns nothing about which payloads would have been accepted.
	storeMu.Lock()
	defer storeMu.Unlock()

	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	if owner != actor.Username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req playNarrationRequest
	if !decodeBody(w, r, &req) {
		return
	}
	text, ok := requireField(w, req.Text, "text")
	if !ok {
		return
	}

	sequence, err := nextPlayEventSequence(campaignID)
	if err != nil {
		writeStorageFailure(w, "play event sequence lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)`,
		campaignID, sequence, playEventKindNarration, actor.Username, text,
	); err != nil {
		writeStorageFailure(w, "play event insert failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, playEventResponse{
		Sequence: sequence,
		Kind:     playEventKindNarration,
		Actor:    actor.Username,
		Text:     text,
	})
}

// ---------- GET /v1/play/campaigns/{id}/turn ----------

type playTurnResponse struct {
	CampaignID   string   `json:"campaign_id"`
	CurrentActor string   `json:"current_actor"`
	Phase        string   `json:"phase"`
	TurnNumber   int      `json:"turn_number"`
	Queue        []string `json:"queue"`
	Overdue      bool     `json:"overdue"`
	Deadline     int      `json:"deadline"`
	NudgeCount   int      `json:"nudge_count"`
}

// handlePlayCampaignTurn reads the play clock. The table is visible to the
// people sitting at it: the owning DM, and any player holding a seat in the
// party. Everyone else is a real identity without a reason to see this
// campaign's turn, so 403 — a DM who owns a different table included.
//
// The phase names who the clock is waiting on rather than the campaign's
// lifecycle status: an active campaign is in the "dm" phase while the owning DM
// holds the turn and the "player" phase otherwise. A campaign that has not
// started has no turn holder, so it reports its lifecycle status ("lobby")
// alongside the empty actor and turn 0 it was created with.
//
// The timeout policy rides along: deadline is the logical event-log position
// the current turn must be closed by, overdue says whether the log has run past
// it, and nudge_count is how often the owner has prodded the table. All three
// are computed from stored counters, never from the wall clock, so two reads of
// an untouched campaign always agree.
func handlePlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var owner, status string
	var turnStartedSeq int
	out := playTurnResponse{CampaignID: campaignID}
	err := db.QueryRow(
		`SELECT owner, status, current_actor, turn_number, turn_started_seq, nudge_count
		 FROM play_campaigns WHERE id = ?`,
		campaignID,
	).Scan(&owner, &status, &out.CurrentActor, &out.TurnNumber, &turnStartedSeq, &out.NudgeCount)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	out.Phase = playTurnPhase(status, owner, out.CurrentActor)
	out.Deadline = turnStartedSeq + playTurnEventBudget
	latest, err := latestPlayEventSequence(campaignID)
	if err != nil {
		writeStorageFailure(w, "play event sequence lookup failed", err)
		return
	}
	out.Overdue = latest > out.Deadline
	out.Queue, err = playTurnQueue(campaignID, status, owner)
	if err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	}

	if owner != actor.Username {
		member, err := rowExists(
			`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`,
			campaignID, actor.Username,
		)
		if err != nil {
			writeStorageFailure(w, "play membership lookup failed", err)
			return
		}
		if !member {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}
	writeJSON(w, http.StatusOK, out)
}

const (
	playTurnPhaseDM     = "dm"
	playTurnPhasePlayer = "player"
)

// playTurnEventBudget is how much of the event log one turn is allowed to
// consume before it counts as overdue. The log is the campaign's only clock —
// there is no wall-clock time anywhere in this program — so a turn that opened
// at sequence s must be closed by sequence s+budget. A turn spends two entries
// in the ordinary case (the player's action and the DM's resolution); the
// budget leaves room for narration on either side of them, so a table playing
// normally is never overdue and a fresh turn never is by construction.
const playTurnEventBudget = 4

// playTurnPhase names who the clock waits on. Before a campaign starts there is
// no turn holder, so the lifecycle status stands in for the phase.
func playTurnPhase(status, owner, currentActor string) string {
	if status != playCampaignStatusActive {
		return status
	}
	if currentActor == owner {
		return playTurnPhaseDM
	}
	return playTurnPhasePlayer
}

// playTurnQueue is the round a started campaign walks: every seated player in
// join order, each one followed by the DM who answers them. A two-player table
// joined A then B reads ["player-a", "dm", "player-b", "dm"], so the round holds
// two entries per seat and always ends on the DM.
//
// A campaign still in the lobby has no round yet and reports an empty queue —
// the party can still change, so any order would be a guess. The queue is
// always a list rather than null so a caller can index it without a nil check.
func playTurnQueue(campaignID, status, owner string) ([]string, error) {
	queue := []string{}
	if status != playCampaignStatusActive {
		return queue, nil
	}
	rows, err := db.Query(
		`SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY position`,
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			return nil, err
		}
		queue = append(queue, username, owner)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return queue, nil
}

// ---------- GET /v1/play/campaigns/{id}/my-turn ----------

type playCharacterRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type playMyTurnResponse struct {
	CampaignID   string              `json:"campaign_id"`
	IsMyTurn     bool                `json:"is_my_turn"`
	CurrentActor string              `json:"current_actor"`
	Character    playCharacterRef    `json:"character"`
	RecentEvents []playEventResponse `json:"recent_events"`
}

// playRecentEventLimit caps how much of the log the player's own view carries.
// The log is unbounded, so "recent" is the tail of it rather than all of it.
const playRecentEventLimit = 10

// handlePlayCampaignMyTurn answers "is it my turn, and who am I here?" for one
// seated player. It is deliberately narrower than /turn: the caller reads their
// own seat only, so the response names no other player's character and the DM
// has no view here at all (403) — the DM already reads the table through /turn.
//
// The character block is the seat the caller joined with, so a player can never
// read another player's character through this route. The event log carried
// back is the same append-only narration every seat at the table can already
// see; nothing DM-private is stored on an event, and no document fields are
// read here at all.
func handlePlayCampaignMyTurn(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	// The route belongs to the player seat. A DM is a real identity without a
	// character in the party, so it is a permission failure rather than a 404.
	if !requireRole(w, actor, "player") {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	out := playMyTurnResponse{CampaignID: campaignID, RecentEvents: []playEventResponse{}}
	var status string
	err := db.QueryRow(
		`SELECT status, current_actor FROM play_campaigns WHERE id = ?`, campaignID,
	).Scan(&status, &out.CurrentActor)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}

	err = db.QueryRow(
		`SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?`,
		campaignID, actor.Username,
	).Scan(&out.Character.ID, &out.Character.Name)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	}

	// A campaign that has not started has no turn holder, so no one's turn is
	// pending even though current_actor is empty for everybody.
	out.IsMyTurn = status == playCampaignStatusActive && out.CurrentActor == actor.Username

	events, err := recentPlayEvents(campaignID, playRecentEventLimit)
	if err != nil {
		writeStorageFailure(w, "play event lookup failed", err)
		return
	}
	out.RecentEvents = events
	writeJSON(w, http.StatusOK, out)
}

// ---------- GET /v1/play/campaigns/{id}/gm/status ----------

// playPartyMemberSummary is one seat as the GM reads it: who holds it, what
// they brought, and whether the clock is on them right now.
type playPartyMemberSummary struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
	IsCurrent   bool   `json:"is_current"`
}

type playGMStatusResponse struct {
	CampaignID     string                   `json:"campaign_id"`
	Status         string                   `json:"status"`
	NeedsAttention bool                     `json:"needs_attention"`
	CurrentActor   string                   `json:"current_actor"`
	TurnNumber     int                      `json:"turn_number"`
	Party          []playPartyMemberSummary `json:"party"`
	RecentEvents   []playEventResponse      `json:"recent_events"`
}

// handlePlayCampaignGMStatus is the owning DM's view of the table: the whole
// party at once, the tail of the log, and the one bit the DM actually acts on —
// needs_attention, true exactly when the clock is on the DM's own seat.
//
// This is the mirror of /my-turn: that route reads one player's own seat and
// refuses the DM, this one reads every seat and refuses the players. A player
// with a seat here is a real identity without the permission, so 403, and so is
// a DM who owns a different table.
func handlePlayCampaignGMStatus(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	out := playGMStatusResponse{
		CampaignID:   campaignID,
		Party:        []playPartyMemberSummary{},
		RecentEvents: []playEventResponse{},
	}
	var owner string
	err := db.QueryRow(
		`SELECT owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?`,
		campaignID,
	).Scan(&owner, &out.Status, &out.CurrentActor, &out.TurnNumber)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	if owner != actor.Username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	// A campaign in the lobby has no turn holder, so the clock is on nobody
	// rather than on the DM.
	out.NeedsAttention = out.CurrentActor != "" && out.CurrentActor == owner

	party, err := playPartySummaries(campaignID, out.CurrentActor)
	if err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	}
	out.Party = party

	events, err := recentPlayEvents(campaignID, playRecentEventLimit)
	if err != nil {
		writeStorageFailure(w, "play event lookup failed", err)
		return
	}
	out.RecentEvents = events
	writeJSON(w, http.StatusOK, out)
}

// ---------- POST /v1/play/campaigns/{id}/actions ----------

type playActionRequest struct {
	Type *string `json:"type"`
	Text *string `json:"text"`
}

// playNextActorDM names the seat the clock moves to after a player acts. It is
// the role rather than the DM's username: the answer to "who goes next" at this
// table is always the DM, whoever that happens to be.
const playNextActorDM = "dm"

// handleSubmitPlayAction records what the player whose turn it is does, and
// hands the clock back to the DM to answer it.
//
// Only the one seat the clock is on may act. Everyone else at the table gets
// 409 rather than 403, because the refusal is about timing and not permission:
// a waiting player will hold this turn later in the round, and the owning DM is
// the very seat the action is about to wake up. Both would succeed at another
// moment, which is what 409 says and 403 does not.
//
// An actor with no seat at this table is a different matter — no moment makes
// them the active player — so they keep the 403 the rest of the play surface
// gives them, and an unstarted campaign has no active seat at all (409).
func handleSubmitPlayAction(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var owner, status, currentActor string
	err := db.QueryRow(
		`SELECT owner, status, current_actor FROM play_campaigns WHERE id = ?`, campaignID,
	).Scan(&owner, &status, &currentActor)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}

	// The DM owns a seat at this table without holding one in the party, so its
	// turn check comes before the membership check.
	if owner != actor.Username {
		seated, err := rowExists(
			`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`,
			campaignID, actor.Username,
		)
		if err != nil {
			writeStorageFailure(w, "play membership lookup failed", err)
			return
		}
		if !seated {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}
	if status != playCampaignStatusActive {
		writeError(w, http.StatusConflict, "play campaign is not active")
		return
	}
	if currentActor != actor.Username || actor.Username == owner {
		writeError(w, http.StatusConflict, "not the active player")
		return
	}

	var req playActionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	actionType, ok := requireField(w, req.Type, "type")
	if !ok {
		return
	}
	text, ok := requireField(w, req.Text, "text")
	if !ok {
		return
	}

	sequence, err := nextPlayEventSequence(campaignID)
	if err != nil {
		writeStorageFailure(w, "play event sequence lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, action_type)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, sequence, playEventKindAction, actor.Username, text, actionType,
	); err != nil {
		writeStorageFailure(w, "play event insert failed", err)
		return
	}
	// The clock moves to the DM's own seat, which is what the queue expects after
	// every player entry and what the GM view reports as needing attention.
	if _, err := db.Exec(
		`UPDATE play_campaigns SET current_actor = ? WHERE id = ?`, owner, campaignID,
	); err != nil {
		writeStorageFailure(w, "play campaign turn advance failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, playEventResponse{
		Sequence:  sequence,
		Kind:      playEventKindAction,
		Actor:     actor.Username,
		Text:      text,
		Type:      actionType,
		NextActor: playNextActorDM,
	})
}

// ---------- POST /v1/play/campaigns/{id}/resolutions ----------

type playResolutionRequest struct {
	Text *string `json:"text"`
}

// playResolutionResponse is the action response plus the turn the resolution
// closed. Resolution is the only entry that ends a turn, so it is the only one
// that reports a number.
type playResolutionResponse struct {
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Actor      string `json:"actor"`
	Text       string `json:"text"`
	NextActor  string `json:"next_actor"`
	TurnNumber int    `json:"turn_number"`
}

// handleResolvePlayTurn is the DM's half of the round: it answers the action the
// clock just handed over and passes play to the next seat in join order.
//
// Only the owning DM resolves, and only while the clock is on the DM's own
// seat. A player at this table gets 409 rather than 403 for the same reason a
// waiting player gets 409 from /actions — the refusal is about timing, not
// identity, and a player never becomes the resolver at any moment. The stronger
// reading (403) would say the seat is wrong; the stage asks for the weaker one.
//
// An actor with no seat at all keeps the 403 the rest of the play surface gives
// them, and an unstarted campaign has no turn to resolve (409).
//
// The next seat follows from the turn number rather than from the log: turn n is
// held by the player at position (n-1) mod party size, so resolving turn 1 at a
// table joined A then B advances to B, and the round wraps back to A after the
// last seat.
func handleResolvePlayTurn(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	var owner, status, currentActor string
	var turnNumber int
	err := db.QueryRow(
		`SELECT owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?`,
		campaignID,
	).Scan(&owner, &status, &currentActor, &turnNumber)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}

	if owner != actor.Username {
		seated, err := rowExists(
			`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`,
			campaignID, actor.Username,
		)
		if err != nil {
			writeStorageFailure(w, "play membership lookup failed", err)
			return
		}
		if !seated {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		writeError(w, http.StatusConflict, "resolution belongs to the DM")
		return
	}
	if status != playCampaignStatusActive {
		writeError(w, http.StatusConflict, "play campaign is not active")
		return
	}
	if currentActor != owner {
		writeError(w, http.StatusConflict, "the DM does not hold the turn")
		return
	}

	var req playResolutionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	text, ok := requireField(w, req.Text, "text")
	if !ok {
		return
	}

	party, err := playPartyOrder(campaignID)
	if err != nil {
		writeStorageFailure(w, "play membership lookup failed", err)
		return
	}
	if len(party) == 0 {
		writeError(w, http.StatusConflict, "play campaign has no party")
		return
	}
	nextTurn := turnNumber + 1
	nextActor := party[(nextTurn-1)%len(party)]

	sequence, err := nextPlayEventSequence(campaignID)
	if err != nil {
		writeStorageFailure(w, "play event sequence lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)`,
		campaignID, sequence, playEventKindResolution, actor.Username, text,
	); err != nil {
		writeStorageFailure(w, "play event insert failed", err)
		return
	}
	// The resolution closes this turn and opens the next one at the log position
	// it was just written to, which restarts the timeout budget.
	if _, err := db.Exec(
		`UPDATE play_campaigns SET current_actor = ?, turn_number = ?, turn_started_seq = ? WHERE id = ?`,
		nextActor, nextTurn, sequence, campaignID,
	); err != nil {
		writeStorageFailure(w, "play campaign turn advance failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, playResolutionResponse{
		Sequence:   sequence,
		Kind:       playEventKindResolution,
		Actor:      actor.Username,
		Text:       text,
		NextActor:  nextActor,
		TurnNumber: nextTurn,
	})
}

// ---------- POST /v1/play/campaigns/{id}/turn/nudge ----------

type playNudgeRequest struct {
	Message *string `json:"message"`
}

// playNudgeResponse names who nudged, which seat was nudged and how many
// nudges this table has seen. CurrentActor and Target are the same seat under
// two names: the target is whoever the clock is on when the nudge lands.
type playNudgeResponse struct {
	CampaignID    string `json:"campaign_id"`
	Actor         string `json:"actor"`
	CurrentActor  string `json:"current_actor"`
	CurrentTarget string `json:"current_target"`
	Target        string `json:"target"`
	Message       string `json:"message"`
	NudgeCount    int    `json:"nudge_count"`
	TurnNumber    int    `json:"turn_number"`
}

// handleNudgePlayTurn lets the owning DM prod whichever seat the clock is on.
// A nudge is a message, not a move: it never changes the current actor, the
// turn number or the event log, so the only thing it advances is nudge_count,
// which counts every nudge this campaign has ever taken and so is monotonically
// increasing.
//
// The route is the owner's, like narration: a player at this table and a DM who
// owns a different one are both real identities without the permission (403).
// A campaign that has not started has no seat to nudge (409).
func handleNudgePlayTurn(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	actor, ok := requireActor(w, r)
	if !ok {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	out := playNudgeResponse{CampaignID: campaignID, Actor: actor.Username}
	var owner, status string
	err := db.QueryRow(
		`SELECT owner, status, current_actor, turn_number, nudge_count FROM play_campaigns WHERE id = ?`,
		campaignID,
	).Scan(&owner, &status, &out.CurrentActor, &out.TurnNumber, &out.NudgeCount)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "play campaign lookup failed", err)
		return
	}
	// Permission is settled before the body is read, so an actor who may not
	// nudge learns nothing about which payloads would have been accepted.
	if owner != actor.Username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if status != playCampaignStatusActive {
		writeError(w, http.StatusConflict, "play campaign is not active")
		return
	}

	var req playNudgeRequest
	if !decodeBody(w, r, &req) {
		return
	}
	message, ok := requireField(w, req.Message, "message")
	if !ok {
		return
	}

	out.NudgeCount++
	if _, err := db.Exec(
		`UPDATE play_campaigns SET nudge_count = ? WHERE id = ?`, out.NudgeCount, campaignID,
	); err != nil {
		writeStorageFailure(w, "play campaign nudge failed", err)
		return
	}
	out.CurrentTarget = out.CurrentActor
	out.Target = out.CurrentActor
	out.Message = message
	writeJSON(w, http.StatusCreated, out)
}

// playPartyOrder is every seated player in join order — the player half of the
// turn queue, without the DM entries the queue interleaves.
func playPartyOrder(campaignID string) ([]string, error) {
	rows, err := db.Query(
		`SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY position`,
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	party := []string{}
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			return nil, err
		}
		party = append(party, username)
	}
	return party, rows.Err()
}

// playPartySummaries reads every seat in join order — the same ordering the
// turn queue walks — flagging the one the clock is on.
func playPartySummaries(campaignID, currentActor string) ([]playPartyMemberSummary, error) {
	rows, err := db.Query(
		`SELECT username, character_id, name, class FROM play_campaign_members
		 WHERE campaign_id = ? ORDER BY position`,
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	party := []playPartyMemberSummary{}
	for rows.Next() {
		var m playPartyMemberSummary
		if err := rows.Scan(&m.Username, &m.CharacterID, &m.Name, &m.Class); err != nil {
			return nil, err
		}
		m.IsCurrent = currentActor != "" && m.Username == currentActor
		party = append(party, m)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return party, nil
}

// recentPlayEvents returns the tail of a campaign's log — at most limit events,
// still in the order they were told, so the newest entry reads last exactly as
// it does in the full log.
func recentPlayEvents(campaignID string, limit int) ([]playEventResponse, error) {
	rows, err := db.Query(
		`SELECT sequence, kind, actor, text, action_type FROM play_campaign_events
		 WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?`,
		campaignID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	events := []playEventResponse{}
	for rows.Next() {
		var e playEventResponse
		if err := rows.Scan(&e.Sequence, &e.Kind, &e.Actor, &e.Text, &e.Type); err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// The query took the tail newest-first; flip it back to chronological.
	for i, j := 0, len(events)-1; i < j; i, j = i+1, j-1 {
		events[i], events[j] = events[j], events[i]
	}
	return events, nil
}

// nextPlayEventSequence returns the next per-campaign event number, 1 for the
// first event. It mirrors nextPosition but reads the sequence column.
func nextPlayEventSequence(campaignID string) (int, error) {
	var sequence int
	err := db.QueryRow(
		`SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?`,
		campaignID,
	).Scan(&sequence)
	return sequence, err
}

// latestPlayEventSequence is the log position a campaign currently stands at,
// 0 for a campaign that has not been narrated in yet. It is the reading the
// turn deadline is compared against.
func latestPlayEventSequence(campaignID string) (int, error) {
	var sequence int
	err := db.QueryRow(
		`SELECT COALESCE(MAX(sequence), 0) FROM play_campaign_events WHERE campaign_id = ?`,
		campaignID,
	).Scan(&sequence)
	return sequence, err
}
