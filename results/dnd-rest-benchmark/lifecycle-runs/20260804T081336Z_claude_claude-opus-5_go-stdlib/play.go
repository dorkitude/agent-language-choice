package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
)

// The protected campaign-play surface under /v1/play.
//
// Unlike every earlier group, these endpoints authenticate the caller. The
// credential is the placeholder token login already hands out
// ("session-<username>"), presented as `Authorization: Bearer session-<user>`.
// Authentication failures are 401; an authenticated actor whose role does not
// permit the action is 403. Both checks run before body validation, so an
// unauthorized caller never learns whether its payload was well-formed.

const (
	bearerPrefix = "Bearer "
	tokenPrefix  = "session-"
)

// actor is the identity behind a play-surface request: the username named by
// the session token plus the role it acts with.
type actor struct {
	Username string
	Role     string
}

// roleFor answers the role a session token acts with. A registered account is
// authoritative; a session for an account that was never registered still
// authenticates (the play surface is reachable before anyone signs up), and its
// role is derived from the name so `session-dm` runs the table and everyone
// else sits at it.
func roleFor(username string) string {
	users.mu.Lock()
	u, ok := users.users[username]
	users.mu.Unlock()
	if ok {
		return u.Role
	}
	if username == "dm" || strings.HasPrefix(username, "dm-") {
		return "dm"
	}
	return "player"
}

// authenticate resolves the request's bearer token to an actor. It reports
// false for a missing header, a non-bearer scheme, a token that is not of the
// session form, and a session naming something that is not a legal username.
func authenticate(r *http.Request) (*actor, bool) {
	header := r.Header.Get("Authorization")
	if !strings.HasPrefix(header, bearerPrefix) {
		return nil, false
	}
	token := strings.TrimSpace(strings.TrimPrefix(header, bearerPrefix))
	if !strings.HasPrefix(token, tokenPrefix) {
		return nil, false
	}
	username := strings.TrimPrefix(token, tokenPrefix)
	if !usernamePattern.MatchString(username) {
		return nil, false
	}
	return &actor{Username: username, Role: roleFor(username)}, true
}

// requireActor authenticates the caller, answering 401 and returning nil when
// the credential is missing or unusable.
func requireActor(w http.ResponseWriter, r *http.Request) *actor {
	a, ok := authenticate(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return nil
	}
	return a
}

// requireRole authenticates the caller and then checks its role, answering 401
// for a bad credential and 403 for a valid actor without permission.
func requireRole(w http.ResponseWriter, r *http.Request, role string) *actor {
	a := requireActor(w, r)
	if a == nil {
		return nil
	}
	if a.Role != role {
		writeError(w, http.StatusForbidden, "forbidden")
		return nil
	}
	return a
}

// ---------- play campaign store ----------

// playCampaign is the play-surface campaign. It is deliberately separate from
// the unauthenticated `campaign` in campaign.go: that one is keyed by a `dm`
// name supplied in the body, while this one is owned by the authenticated
// creator and carries a lifecycle `status`.
type playCampaign struct {
	ID         string
	Name       string
	Owner      string
	Status     string
	MaxPlayers int
	Members    []*playMember
	// CurrentActor and TurnNumber are the turn cursor. They stay zero-valued
	// while the campaign is in the lobby and are set once, at start.
	CurrentActor string
	TurnNumber   int
	// Events is the campaign's append-only log. Its position in the slice is
	// the event's sequence, which therefore starts at 1 per campaign.
	Events []*playEvent
}

// playEvent is one entry in a campaign's append-only log: what happened, who
// caused it, and the narrated text. Type is the caller-supplied sub-kind an
// action carries ("search", "attack", ...); a narration has none.
type playEvent struct {
	Sequence int
	Kind     string
	Actor    string
	Type     string
	Text     string
}

// appendEvent logs an event and returns it. The sequence is assigned from the
// current log length, so it starts at 1 and never repeats or rewinds. Callers
// must hold playCampaigns.mu.
func (c *playCampaign) appendEvent(kind, actor, eventType, text string) *playEvent {
	e := &playEvent{Sequence: len(c.Events) + 1, Kind: kind, Actor: actor, Type: eventType, Text: text}
	c.Events = append(c.Events, e)
	return e
}

// playMember is one seat at a play campaign's table: the player who claimed it
// and the character they brought. The party is a slice because join order is
// part of the contract for anything that reads the roster back.
type playMember struct {
	Username    string
	CharacterID string
	Name        string
	Class       string
}

// member returns the campaign's membership for username, or nil. Callers must
// hold playCampaigns.mu.
func (c *playCampaign) member(username string) *playMember {
	for _, m := range c.Members {
		if m.Username == username {
			return m
		}
	}
	return nil
}

// memberByCharacter returns the membership holding characterID, or nil.
// Callers must hold playCampaigns.mu.
func (c *playCampaign) memberByCharacter(characterID string) *playMember {
	for _, m := range c.Members {
		if m.CharacterID == characterID {
			return m
		}
	}
	return nil
}

// playCampaignStore holds play campaigns by id plus the id list in creation
// order, so snapshots do not inherit map iteration order.
type playCampaignStore struct {
	mu        sync.Mutex
	campaigns map[string]*playCampaign
	order     []string
}

var playCampaigns = &playCampaignStore{campaigns: map[string]*playCampaign{}}

// add registers a play campaign, preserving creation order. Callers must hold
// s.mu and must have already rejected duplicate ids.
func (s *playCampaignStore) add(c *playCampaign) {
	s.campaigns[c.ID] = c
	s.order = append(s.order, c.ID)
}

// statusLobby is the status a freshly created play campaign starts in;
// statusActive is what starting it promotes it to.
const (
	statusLobby  = "lobby"
	statusActive = "active"
)

// minPartyToStart is the party size a lobby campaign must reach before its DM
// can start it.
const minPartyToStart = 2

// ---------- POST /v1/play/campaigns ----------

type playCampaignRequest struct {
	ID         *string          `json:"id"`
	Name       *string          `json:"name"`
	MaxPlayers *json.RawMessage `json:"max_players"`
}

type playCampaignResponse struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Owner      string `json:"owner"`
	Status     string `json:"status"`
	MaxPlayers int    `json:"max_players"`
}

func handleCreatePlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor := requireRole(w, r, "dm")
	if actor == nil {
		return
	}

	var req playCampaignRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	maxPlayers, ok := asInt(req.MaxPlayers)
	if !ok {
		writeError(w, http.StatusBadRequest, "max_players must be an integer")
		return
	}
	if maxPlayers < 1 {
		writeError(w, http.StatusBadRequest, "max_players must be at least 1")
		return
	}

	c := &playCampaign{
		ID:         id,
		Name:       name,
		Owner:      actor.Username,
		Status:     statusLobby,
		MaxPlayers: maxPlayers,
	}

	playCampaigns.mu.Lock()
	if _, exists := playCampaigns.campaigns[id]; exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "play campaign already exists")
		return
	}
	playCampaigns.add(c)
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, playCampaignResponse{
		ID:         c.ID,
		Name:       c.Name,
		Owner:      c.Owner,
		Status:     c.Status,
		MaxPlayers: c.MaxPlayers,
	})
}

// ---------- POST /v1/play/campaigns/{id}/members ----------

type playMemberRequest struct {
	CharacterID *string `json:"character_id"`
	Name        *string `json:"name"`
	Class       *string `json:"class"`
}

type playMemberResponse struct {
	CampaignID  string `json:"campaign_id"`
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// handleJoinPlayCampaign seats an authenticated player in a lobby campaign.
// Only players join: a DM already runs the table, so its role is rejected with
// 403 before the body is read. A player holds at most one seat per campaign and
// a character id is claimed by at most one seat, and the party cannot outgrow
// max_players; each of those collisions is a 409.
func handleJoinPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor := requireRole(w, r, "player")
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	var req playMemberRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	characterID, ok := requiredString(req.CharacterID)
	if !ok {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	class, ok := requiredString(req.Class)
	if !ok {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if c.Status != statusLobby {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "campaign is not accepting members")
		return
	}
	if c.member(actor.Username) != nil {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "player already joined this campaign")
		return
	}
	if c.memberByCharacter(characterID) != nil {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "character already joined this campaign")
		return
	}
	if len(c.Members) >= c.MaxPlayers {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "campaign party is full")
		return
	}
	m := &playMember{
		Username:    actor.Username,
		CharacterID: characterID,
		Name:        name,
		Class:       class,
	}
	c.Members = append(c.Members, m)
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, playMemberResponse{
		CampaignID:  c.ID,
		Username:    m.Username,
		CharacterID: m.CharacterID,
		Name:        m.Name,
		Class:       m.Class,
	})
}

// ---------- POST /v1/play/campaigns/{id}/start ----------

type playStartResponse struct {
	ID           string `json:"id"`
	Status       string `json:"status"`
	CurrentActor string `json:"current_actor"`
	TurnNumber   int    `json:"turn_number"`
}

// handleStartPlayCampaign promotes a lobby campaign to active exactly once.
// Only a DM may start a campaign and only the one they own, so a player is 403
// before the campaign is even looked up and a DM who is not the owner is 403
// after. A campaign that has already started, or whose party is still short of
// minPartyToStart, is 409. The turn cursor opens on the first player to join —
// join order is the turn order — at turn 1.
func handleStartPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor := requireRole(w, r, "dm")
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	if c.Owner != actor.Username {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if c.Status != statusLobby {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "campaign is not in the lobby")
		return
	}
	if len(c.Members) < minPartyToStart {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "campaign needs at least two party members")
		return
	}
	c.Status = statusActive
	c.CurrentActor = c.Members[0].Username
	c.TurnNumber = 1
	resp := playStartResponse{
		ID:           c.ID,
		Status:       c.Status,
		CurrentActor: c.CurrentActor,
		TurnNumber:   c.TurnNumber,
	}
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// ---------- POST /v1/play/campaigns/{id}/narrations ----------

type narrationRequest struct {
	Text *string `json:"text"`
}

// playEventResponse is one log entry on the wire. `type` is omitted for the
// kinds that carry none, so a narration reads back exactly as it always has.
type playEventResponse struct {
	Sequence int    `json:"sequence"`
	Kind     string `json:"kind"`
	Actor    string `json:"actor"`
	Type     string `json:"type,omitempty"`
	Text     string `json:"text"`
}

// eventResponse renders a log entry for the wire.
func eventResponse(e *playEvent) playEventResponse {
	return playEventResponse{Sequence: e.Sequence, Kind: e.Kind, Actor: e.Actor, Type: e.Type, Text: e.Text}
}

// handleNarrate appends a narration event to a campaign's log. Narration is the
// owner's voice, so only the DM who owns the campaign may write it: anyone else
// with a valid session — a player, or another DM — is 403. The campaign is
// looked up before the ownership check so an unknown id is 404 rather than a
// forbidden that leaks nothing about whether it exists.
func handleNarrate(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	owner := c.Owner
	playCampaigns.mu.Unlock()

	if actor.Role != "dm" || owner != actor.Username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req narrationRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	text, ok := requiredString(req.Text)
	if !ok {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaigns.mu.Lock()
	c, exists = playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	e := c.appendEvent("narration", actor.Username, "", text)
	resp := eventResponse(e)
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- GET /v1/play/campaigns/{id}/turn ----------

type playTurnResponse struct {
	CampaignID   string   `json:"campaign_id"`
	CurrentActor string   `json:"current_actor"`
	Phase        string   `json:"phase"`
	TurnNumber   int      `json:"turn_number"`
	Queue        []string `json:"queue"`
}

// phaseLobby is the phase a campaign reports before it has a turn cursor;
// phasePlayer and phaseGM say whether the cursor rests on a seated player or
// on the owning DM.
const (
	phaseLobby  = "lobby"
	phasePlayer = "player"
	phaseGM     = "gm"
)

// phase derives the turn phase from the cursor: who holds the turn matters to
// clients more than the campaign's lifecycle status does, and a campaign that
// has not started has no holder at all. Callers must hold playCampaigns.mu.
func (c *playCampaign) phase() string {
	if c.CurrentActor == "" {
		return phaseLobby
	}
	if c.member(c.CurrentActor) != nil {
		return phasePlayer
	}
	return phaseGM
}

// queue is the campaign's turn order: each seated player in join order, each
// followed by the owning DM, who answers every player in turn. A campaign
// still in the lobby has no order to report, so the queue reads back empty
// rather than guessing at a roster that may still grow. Callers must hold
// playCampaigns.mu.
func (c *playCampaign) queue() []string {
	q := make([]string, 0, len(c.Members)*2)
	if c.Status == statusLobby {
		return q
	}
	for _, m := range c.Members {
		q = append(q, m.Username, c.Owner)
	}
	return q
}

// recentEventLimit caps how many log entries a player's turn context carries:
// the tail of the log, oldest first, so a long campaign still answers in a
// bounded, deterministic payload.
const recentEventLimit = 10

// recentEvents returns the last recentEventLimit entries of the log in sequence
// order. Callers must hold playCampaigns.mu.
func (c *playCampaign) recentEvents() []playEventResponse {
	start := 0
	if len(c.Events) > recentEventLimit {
		start = len(c.Events) - recentEventLimit
	}
	out := make([]playEventResponse, 0, len(c.Events)-start)
	for _, e := range c.Events[start:] {
		out = append(out, eventResponse(e))
	}
	return out
}

// handleTurn reports the turn cursor to the table. Reading it is a membership
// right, not a role one: the owning DM and any seated player may look, and any
// other authenticated caller — including a DM who owns some other campaign — is
// 403. A lobby campaign has no cursor yet, so it reads back with an empty
// current_actor at turn 0 while its phase says why.
func handleTurn(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	permitted := c.Owner == actor.Username || c.member(actor.Username) != nil
	resp := playTurnResponse{
		CampaignID:   c.ID,
		CurrentActor: c.CurrentActor,
		Phase:        c.phase(),
		TurnNumber:   c.TurnNumber,
		Queue:        c.queue(),
	}
	playCampaigns.mu.Unlock()

	if !permitted {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// ---------- GET /v1/play/campaigns/{id}/my-turn ----------

// playCharacterRef is the caller's own character, reduced to the two fields a
// player's turn context needs. Nothing else about the character — and nothing
// at all from the DM's private documents — crosses this boundary.
type playCharacterRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type playMyTurnResponse struct {
	CampaignID   string              `json:"campaign_id"`
	IsMyTurn     bool                `json:"is_my_turn"`
	CurrentActor string              `json:"current_actor"`
	TurnNumber   int                 `json:"turn_number"`
	Character    playCharacterRef    `json:"character"`
	RecentEvents []playEventResponse `json:"recent_events"`
}

// handleMyTurn answers a seated player's own turn context: whether the cursor
// rests on them, who it rests on, the character they brought, and the tail of
// the campaign log. This is a player's view by construction — the caller's own
// membership is the only character it can name — so a DM, even the owner, is
// 403 rather than being handed a player-shaped payload, and so is a player who
// never joined. The campaign is resolved first, so an unknown id is 404.
func handleMyTurn(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	m := c.member(actor.Username)
	var resp playMyTurnResponse
	if m != nil {
		resp = playMyTurnResponse{
			CampaignID:   c.ID,
			IsMyTurn:     c.CurrentActor == actor.Username,
			CurrentActor: c.CurrentActor,
			TurnNumber:   c.TurnNumber,
			Character:    playCharacterRef{ID: m.CharacterID, Name: m.Name},
			RecentEvents: c.recentEvents(),
		}
	}
	playCampaigns.mu.Unlock()

	if actor.Role != "player" || m == nil {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// ---------- GET /v1/play/campaigns/{id}/gm/status ----------

// playPartyMember is one seat as the GM sees it: who holds it, what they
// brought, and whether the cursor rests on them. It is the mirror of the
// player's single-character view — the owner sees the whole table.
type playPartyMember struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
	IsCurrent   bool   `json:"is_current"`
}

type playGMStatusResponse struct {
	CampaignID     string              `json:"campaign_id"`
	Status         string              `json:"status"`
	NeedsAttention bool                `json:"needs_attention"`
	CurrentActor   string              `json:"current_actor"`
	Phase          string              `json:"phase"`
	TurnNumber     int                 `json:"turn_number"`
	Party          []playPartyMember   `json:"party"`
	RecentEvents   []playEventResponse `json:"recent_events"`
}

// party summarises every seat in join order. Callers must hold
// playCampaigns.mu.
func (c *playCampaign) party() []playPartyMember {
	out := make([]playPartyMember, 0, len(c.Members))
	for _, m := range c.Members {
		out = append(out, playPartyMember{
			Username:    m.Username,
			CharacterID: m.CharacterID,
			Name:        m.Name,
			Class:       m.Class,
			IsCurrent:   c.CurrentActor != "" && c.CurrentActor == m.Username,
		})
	}
	return out
}

// handleGMStatus answers the owning DM's view of the table: whether the
// campaign is waiting on them, where the cursor rests, the whole party, and the
// tail of the log. This is the counterpart to my-turn and is owner-only by
// construction — a player, a non-member, and a DM who owns some other campaign
// are all 403 — because it reports every seat at once. needs_attention is true
// exactly when the cursor rests on the owner, which is the GM's cue to narrate.
// The campaign is resolved first, so an unknown id is 404.
func handleGMStatus(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	owned := actor.Role == "dm" && c.Owner == actor.Username
	var resp playGMStatusResponse
	if owned {
		resp = playGMStatusResponse{
			CampaignID:     c.ID,
			Status:         c.Status,
			NeedsAttention: c.CurrentActor != "" && c.CurrentActor == c.Owner,
			CurrentActor:   c.CurrentActor,
			Phase:          c.phase(),
			TurnNumber:     c.TurnNumber,
			Party:          c.party(),
			RecentEvents:   c.recentEvents(),
		}
	}
	playCampaigns.mu.Unlock()

	if !owned {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// ---------- POST /v1/play/campaigns/{id}/actions ----------

type playActionRequest struct {
	Type *string `json:"type"`
	Text *string `json:"text"`
}

type playActionResponse struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Type      string `json:"type"`
	Text      string `json:"text"`
	NextActor string `json:"next_actor"`
}

// actorRoleDM is the role the turn passes to once a player has acted: the table
// always answers a declared action with the DM's ruling, so an accepted action
// names the DM as the next actor.
const actorRoleDM = "dm"

// handleAction records the acting player's declared action. Only the player the
// cursor rests on may declare one: a seated player who is still waiting, and the
// DM — whose move is to narrate, not to act — are both 409, because the request
// is well-formed and merely out of turn. A caller who is neither the owner nor a
// seated member has no standing at this table at all and is 403; an unknown
// campaign is 404, checked first.
//
// Accepting an action hands the turn to the owning DM, which is what
// next_actor announces, and appends an `action` event to the shared log so both
// the player's and the GM's turn context see it immediately.
func handleAction(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	seated := c.member(actor.Username) != nil
	owner := c.Owner == actor.Username
	active := c.CurrentActor != "" && c.CurrentActor == actor.Username
	playCampaigns.mu.Unlock()

	if !seated && !owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if !seated || !active {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	var req playActionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	actionType, ok := requiredString(req.Type)
	if !ok {
		writeError(w, http.StatusBadRequest, "type is required")
		return
	}
	text, ok := requiredString(req.Text)
	if !ok {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaigns.mu.Lock()
	c, exists = playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	// Re-check the cursor under the lock: two concurrent actions from the same
	// seat must not both be accepted.
	if c.CurrentActor != actor.Username {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	e := c.appendEvent("action", actor.Username, actionType, text)
	c.CurrentActor = c.Owner
	resp := playActionResponse{
		Sequence:  e.Sequence,
		Kind:      e.Kind,
		Actor:     e.Actor,
		Type:      e.Type,
		Text:      e.Text,
		NextActor: actorRoleDM,
	}
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/play/campaigns/{id}/resolutions ----------

type resolutionRequest struct {
	Text *string `json:"text"`
}

type playResolutionResponse struct {
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Actor      string `json:"actor"`
	Text       string `json:"text"`
	NextActor  string `json:"next_actor"`
	TurnNumber int    `json:"turn_number"`
}

// nextPlayer returns the seat the turn passes to once the DM has resolved the
// action in front of them: the seat after whoever declared the most recent
// action, in join order, wrapping at the end of the party. Deriving it from the
// log keeps the cursor a function of what happened rather than of extra state,
// so a campaign reloaded from storage resumes on the same seat. A campaign that
// has seen no action yet — the DM held the cursor some other way — opens on the
// first seat. Callers must hold playCampaigns.mu.
func (c *playCampaign) nextPlayer() string {
	if len(c.Members) == 0 {
		return ""
	}
	last := ""
	for _, e := range c.Events {
		if e.Kind == "action" {
			last = e.Actor
		}
	}
	for i, m := range c.Members {
		if m.Username == last {
			return c.Members[(i+1)%len(c.Members)].Username
		}
	}
	return c.Members[0].Username
}

// handleResolution records the owning DM's ruling on the action in front of
// them. Resolution is the GM's move, so only the owner may make it, and only
// while the cursor rests on them: a seated player — even the one who just acted
// — is 409, because the request is well-formed and merely out of turn, and so
// is the owner whose table is still waiting on a player. A caller with no seat
// and no ownership has no standing here at all and is 403; an unknown campaign
// is 404, checked first.
//
// Accepting a resolution appends a `resolution` event to the shared log and
// hands the turn to the next player in join order, opening a new turn — which
// is what next_actor and the incremented turn_number announce.
func handleResolution(w http.ResponseWriter, r *http.Request) {
	actor := requireActor(w, r)
	if actor == nil {
		return
	}

	id := strings.TrimSpace(r.PathValue("id"))

	playCampaigns.mu.Lock()
	c, exists := playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	seated := c.member(actor.Username) != nil
	owner := actor.Role == "dm" && c.Owner == actor.Username
	active := c.CurrentActor != "" && c.CurrentActor == actor.Username
	playCampaigns.mu.Unlock()

	if !seated && !owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if !owner || !active {
		writeError(w, http.StatusConflict, "not your turn")
		return
	}

	var req resolutionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	text, ok := requiredString(req.Text)
	if !ok {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playCampaigns.mu.Lock()
	c, exists = playCampaigns.campaigns[id]
	if !exists {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	// Re-check the cursor under the lock: two concurrent resolutions must not
	// both be accepted and advance the turn twice.
	if c.CurrentActor != actor.Username {
		playCampaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "not your turn")
		return
	}
	e := c.appendEvent("resolution", actor.Username, "", text)
	c.CurrentActor = c.nextPlayer()
	c.TurnNumber++
	resp := playResolutionResponse{
		Sequence:   e.Sequence,
		Kind:       e.Kind,
		Actor:      e.Actor,
		Text:       e.Text,
		NextActor:  c.CurrentActor,
		TurnNumber: c.TurnNumber,
	}
	playCampaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}
