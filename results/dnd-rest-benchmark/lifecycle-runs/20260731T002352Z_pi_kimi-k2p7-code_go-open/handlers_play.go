package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// authenticate validates the Authorization: Bearer session-<username> header
// against the in-memory user cache. It returns the authenticated user and 0 on
// success; otherwise it returns nil and an HTTP status code (401 for missing or
// malformed credentials, 403 for a valid-looking token whose user is unknown).
func authenticate(r *http.Request) (*user, int) {
	auth := r.Header.Get("Authorization")
	if auth == "" {
		return nil, http.StatusUnauthorized
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(auth, prefix) {
		return nil, http.StatusUnauthorized
	}
	token := strings.TrimPrefix(auth, prefix)
	const sessionPrefix = "session-"
	if !strings.HasPrefix(token, sessionPrefix) {
		return nil, http.StatusUnauthorized
	}
	username := strings.TrimPrefix(token, sessionPrefix)
	if username == "" {
		return nil, http.StatusUnauthorized
	}

	users.mu.RLock()
	defer users.mu.RUnlock()
	u, exists := users.users[username]
	if !exists {
		return nil, http.StatusForbidden
	}
	return u, 0
}

// requirePlayCampaign loads a play campaign and writes the standard 400/404
// response when the load fails or the campaign is missing. It returns the
// loaded campaign or nil when a response has already been written.
func requirePlayCampaign(w http.ResponseWriter, id string) *playCampaign {
	p, err := dbGetPlayCampaign(id)
	if err != nil {
		log.Printf("get play campaign: %v", err)
		badRequest(w, "failed to read campaign")
		return nil
	}
	if p == nil {
		notFound(w, "campaign not found")
		return nil
	}
	return p
}

// requirePlayEncounter loads a play encounter belonging to a campaign and
// writes the standard 400/404 response when the load fails or the encounter is
// missing. It returns the loaded encounter or nil when a response has already
// been written.
func requirePlayEncounter(w http.ResponseWriter, campaignID, encounterID string) *playEncounter {
	e, err := dbGetPlayEncounter(campaignID, encounterID)
	if err != nil {
		log.Printf("get play encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return nil
	}
	if e == nil {
		notFound(w, "encounter not found")
		return nil
	}
	return e
}

// isPlayCampaignMember reports whether the user is allowed to observe a play
// campaign: the owner is always allowed, and any bound party member is allowed.
func isPlayCampaignMember(u *user, p *playCampaign) bool {
	if p.Owner == u.Username {
		return true
	}
	m, err := dbGetPlayMembershipByUserAndCampaign(u.Username, p.ID)
	if err != nil || m == nil {
		return false
	}
	return true
}

func createPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create play campaigns")
		return
	}

	var req playCampaignCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if req.MaxPlayers <= 0 {
		badRequest(w, "max_players must be a positive integer")
		return
	}

	p := &playCampaign{
		ID:         req.ID,
		Name:       req.Name,
		Owner:      u.Username,
		Status:     campaignStatusLobby,
		MaxPlayers: req.MaxPlayers,
	}

	if err := dbCreatePlayCampaign(p); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "campaign id already exists")
			return
		}
		log.Printf("create play campaign: %v", err)
		badRequest(w, "failed to create play campaign")
		return
	}

	writeJSON(w, http.StatusCreated, p)
}

func joinPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may join")
		return
	}

	id := r.PathValue("id")

	var req playMembershipRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.CharacterID) == "" {
		badRequest(w, "character_id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if strings.TrimSpace(req.Class) == "" {
		badRequest(w, "class is required")
		return
	}

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if p.Status != campaignStatusLobby {
		conflict(w, "campaign is not accepting members")
		return
	}

	existing, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if existing != nil {
		conflict(w, "player already has a membership in this campaign")
		return
	}

	count, err := dbCountPlayMembersByCampaign(id)
	if err != nil {
		log.Printf("count members: %v", err)
		badRequest(w, "failed to count members")
		return
	}
	if count >= p.MaxPlayers {
		conflict(w, "campaign is full")
		return
	}

	if err := dbCreatePlayMembership(id, u.Username, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "membership already exists")
			return
		}
		log.Printf("create membership: %v", err)
		badRequest(w, "failed to create membership")
		return
	}

	writeJSON(w, http.StatusCreated, playMembershipResponse{
		Username:    u.Username,
		CharacterID: req.CharacterID,
		Name:        req.Name,
		Class:       req.Class,
	})
}

func startPlayCampaignHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can start campaigns")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can start this campaign")
		return
	}
	if p.Status != campaignStatusLobby {
		conflict(w, "campaign is not in the lobby state")
		return
	}

	members, err := dbGetPlayMembersByCampaign(id)
	if err != nil {
		log.Printf("get members: %v", err)
		badRequest(w, "failed to read campaign members")
		return
	}
	if len(members) < 2 {
		conflict(w, "campaign needs at least two party members to start")
		return
	}

	if err := dbStartPlayCampaign(id, members[0]); err != nil {
		log.Printf("start campaign: %v", err)
		badRequest(w, "failed to start campaign")
		return
	}

	writeJSON(w, http.StatusOK, playCampaignStartResponse{
		ID:           id,
		Status:       campaignStatusActive,
		CurrentActor: members[0],
		TurnNumber:   1,
	})
}

func createPlayEncounterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create encounters")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create encounters")
		return
	}

	var req encounterCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}

	active, err := dbGetActivePlayEncounterByCampaign(id)
	if err != nil {
		log.Printf("get active encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return
	}
	if active != nil {
		conflict(w, "campaign already in combat")
		return
	}

	currentActor, _, _, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get play campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}

	e := &playEncounter{
		ID:             req.ID,
		CampaignID:     id,
		Name:           req.Name,
		Status:         encounterStatusActive,
		PreCombatActor: currentActor,
	}

	if err := dbCreatePlayEncounter(e); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "encounter id already exists")
			return
		}
		log.Printf("create play encounter: %v", err)
		badRequest(w, "failed to create encounter")
		return
	}

	combatants, err := dbGetPlayEncounterCombatants(id, e.ID)
	if err != nil {
		log.Printf("get encounter combatants: %v", err)
		badRequest(w, "failed to read encounter combatants")
		return
	}

	writeJSON(w, http.StatusCreated, encounterResponse{
		ID:         e.ID,
		Name:       e.Name,
		Status:     e.Status,
		Combatants: combatants,
	})
}

func addNarrationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	canNarrate := p.Owner == u.Username
	if !canNarrate {
		has, err := dbHasDelegationPower(id, u.Username, powerNarrate)
		if err != nil {
			log.Printf("check delegation power: %v", err)
			badRequest(w, "failed to read delegation")
			return
		}
		canNarrate = has
	}
	if !canNarrate {
		forbidden(w, "only the campaign owner or a delegated narrator can narrate")
		return
	}

	var req narrationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	n, err := dbCreateNarration(id, u.Username, req.Text)
	if err != nil {
		log.Printf("create narration: %v", err)
		badRequest(w, "failed to create narration")
		return
	}

	writeJSON(w, http.StatusCreated, n)
}

func getPlayCampaignTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
	}

	currentActor, turnNumber, found, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get play campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}
	if !found {
		notFound(w, "campaign not found")
		return
	}

	phase := p.Status
	if currentActor != "" {
		if currentActor == p.Owner {
			phase = "dm"
		} else {
			phase = "player"
		}
	}

	// The turn queue is built as a round-robin sequence: each player acts,
	// then the DM resolves, repeating for every party member. This order is
	// deterministic because members are read in insertion (rowid) order.
	var queue []string
	if currentActor != "" {
		members, err := dbGetPlayMembersByCampaign(id)
		if err != nil {
			log.Printf("get play members: %v", err)
			badRequest(w, "failed to read campaign members")
			return
		}
		for _, username := range members {
			queue = append(queue, username, p.Owner)
		}
	}

	logicalDeadline := turnNumber
	if currentActor != "" {
		for i, actor := range queue {
			if actor == currentActor {
				logicalDeadline = turnNumber + len(queue) - i - 1
				break
			}
		}
	}

	writeJSON(w, http.StatusOK, playCampaignTurnResponse{
		CampaignID:      id,
		CurrentActor:    currentActor,
		Phase:           phase,
		TurnNumber:      turnNumber,
		Queue:           queue,
		Overdue:         false,
		LogicalDeadline: logicalDeadline,
	})
}

func nudgeTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can nudge")
		return
	}

	var req nudgeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Message) == "" {
		badRequest(w, "message is required")
		return
	}

	actor, nudgeCount, ok, err := dbNudge(id, req.Message)
	if err != nil {
		log.Printf("nudge campaign: %v", err)
		badRequest(w, "failed to nudge")
		return
	}
	if !ok {
		conflict(w, "campaign is not active")
		return
	}

	writeJSON(w, http.StatusCreated, nudgeResponse{
		Actor:      u.Username,
		Target:     actor,
		Message:    req.Message,
		NudgeCount: nudgeCount,
	})
}

func getPlayCampaignMyTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may read their turn context")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	currentActor, _, found, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get play campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}
	if !found {
		notFound(w, "campaign not found")
		return
	}

	events, err := dbGetPlayNarrationsByCampaign(id)
	if err != nil {
		log.Printf("get play narrations: %v", err)
		badRequest(w, "failed to read recent events")
		return
	}

	writeJSON(w, http.StatusOK, playerTurnResponse{
		IsMyTurn:     currentActor == u.Username,
		CurrentActor: currentActor,
		Character: playerTurnChar{
			ID:   membership.CharacterID,
			Name: membership.Name,
		},
		RecentEvents: events,
	})
}

func submitPlayerActionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	var req actionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Type) == "" {
		badRequest(w, "type is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if p.Owner == u.Username {
		conflict(w, "only the active player can submit an action")
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	resp, ok, err := dbCreateAction(id, u.Username, &req)
	if err != nil {
		log.Printf("create action: %v", err)
		badRequest(w, "failed to create action")
		return
	}
	if !ok {
		conflict(w, "only the active player can submit an action")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func submitTravelHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if p.Owner == u.Username {
		conflict(w, "only the active player can travel")
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	var req travelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.DestinationID) == "" {
		badRequest(w, "destination_id is required")
		return
	}

	resp, ok, err := dbCreateTravel(id, u.Username, req.DestinationID)
	if err != nil {
		log.Printf("create travel: %v", err)
		badRequest(w, "failed to create travel")
		return
	}
	if !ok {
		conflict(w, "invalid travel destination or not your turn")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func submitRestHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if p.Owner == u.Username {
		conflict(w, "only the active player can rest")
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	var req restRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Type != "short" && req.Type != "long" {
		badRequest(w, "invalid rest type")
		return
	}

	resp, ok, err := dbCreateRest(id, u.Username, req.Type)
	if err != nil {
		log.Printf("create rest: %v", err)
		badRequest(w, "failed to create rest")
		return
	}
	if !ok {
		conflict(w, "not your turn")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func submitResolutionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if p.Owner != u.Username {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
		conflict(w, "only the active GM can resolve")
		return
	}

	var req resolutionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	resp, ok, err := dbCreateResolution(id, u.Username, req.Text)
	if err != nil {
		log.Printf("create resolution: %v", err)
		badRequest(w, "failed to create resolution")
		return
	}
	if !ok {
		conflict(w, "only the active GM can resolve")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func updateCampaignDocumentHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can update the document")
		return
	}

	var req campaignDocumentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if err := dbUpdatePlayCampaignDocument(id, req.Story, req.DMNotes); err != nil {
		log.Printf("update campaign document: %v", err)
		badRequest(w, "failed to update campaign document")
		return
	}

	writeJSON(w, http.StatusOK, campaignDocument{
		Story:   req.Story,
		DMNotes: req.DMNotes,
	})
}

func getCampaignDocumentHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
	}

	story, dmNotes, err := dbGetPlayCampaignDocument(id)
	if err != nil {
		log.Printf("get campaign document: %v", err)
		badRequest(w, "failed to read campaign document")
		return
	}

	if isOwner {
		writeJSON(w, http.StatusOK, campaignDocument{
			Story:   story,
			DMNotes: dmNotes,
		})
		return
	}

	writeJSON(w, http.StatusOK, campaignDocumentPublic{
		Story: story,
	})
}

func updateSessionZeroSettingsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can set session-zero settings")
		return
	}
	if p.Status != campaignStatusLobby {
		conflict(w, "session-zero settings can only be changed while the campaign is in the lobby state")
		return
	}

	var req sessionZeroSettings
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Rules) == "" {
		badRequest(w, "rules is required")
		return
	}
	if strings.TrimSpace(req.Tone) == "" {
		badRequest(w, "tone is required")
		return
	}
	if len(req.Consent) == 0 {
		badRequest(w, "consent must be a non-empty array")
		return
	}
	seen := make(map[string]bool, len(req.Consent))
	for _, c := range req.Consent {
		if strings.TrimSpace(c) == "" {
			badRequest(w, "consent entries must be non-empty strings")
			return
		}
		if seen[c] {
			badRequest(w, "consent entries must be unique")
			return
		}
		seen[c] = true
	}

	if err := dbUpdateSessionZeroSettings(id, &req); err != nil {
		log.Printf("update session zero settings: %v", err)
		badRequest(w, "failed to update session-zero settings")
		return
	}

	writeJSON(w, http.StatusOK, req)
}

func getSessionZeroSettingsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
	}

	settings, found, err := dbGetSessionZeroSettings(id)
	if err != nil {
		log.Printf("get session zero settings: %v", err)
		badRequest(w, "failed to read session-zero settings")
		return
	}
	if !found {
		notFound(w, "session-zero settings not found")
		return
	}

	writeJSON(w, http.StatusOK, settings)
}

func createPlaySceneHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create scenes")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create scenes")
		return
	}

	var req playSceneCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}

	s := &playScene{
		ID:         req.ID,
		CampaignID: id,
		Name:       req.Name,
		Status:     sceneStatusOpen,
	}

	if err := dbCreatePlayScene(s); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "scene id already exists")
			return
		}
		log.Printf("create play scene: %v", err)
		badRequest(w, "failed to create scene")
		return
	}

	writeJSON(w, http.StatusCreated, playScene{
		ID:     s.ID,
		Name:   s.Name,
		Status: s.Status,
	})
}

func enterPlaySceneHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can enter scenes")
		return
	}

	id := r.PathValue("id")
	sceneID := r.PathValue("scene_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can enter scenes")
		return
	}

	s, err := dbGetPlayScene(id, sceneID)
	if err != nil {
		log.Printf("get play scene: %v", err)
		badRequest(w, "failed to read scene")
		return
	}
	if s == nil {
		notFound(w, "scene not found")
		return
	}
	if s.Status == sceneStatusClosed {
		conflict(w, "scene is closed")
		return
	}

	if err := dbSetPlayCampaignCurrentScene(id, sceneID); err != nil {
		log.Printf("set current scene: %v", err)
		badRequest(w, "failed to enter scene")
		return
	}

	writeJSON(w, http.StatusOK, playSceneEnterResponse{
		CurrentSceneID: sceneID,
		Name:           s.Name,
	})
}

func closePlaySceneHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can close scenes")
		return
	}

	id := r.PathValue("id")
	sceneID := r.PathValue("scene_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can close scenes")
		return
	}

	s, err := dbClosePlayScene(id, sceneID)
	if err != nil {
		log.Printf("close play scene: %v", err)
		badRequest(w, "failed to close scene")
		return
	}
	if s == nil {
		notFound(w, "scene not found")
		return
	}

	writeJSON(w, http.StatusOK, playSceneCloseResponse{
		ID:     s.ID,
		Status: s.Status,
	})
}

func getCurrentSceneHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
	}

	sceneID, err := dbGetPlayCampaignCurrentSceneID(id)
	if err != nil {
		log.Printf("get current scene id: %v", err)
		badRequest(w, "failed to read current scene")
		return
	}
	if sceneID == "" {
		notFound(w, "no current scene")
		return
	}

	s, err := dbGetPlayScene(id, sceneID)
	if err != nil {
		log.Printf("get play scene: %v", err)
		badRequest(w, "failed to read scene")
		return
	}
	if s == nil || s.Status != sceneStatusOpen {
		notFound(w, "no current scene")
		return
	}

	writeJSON(w, http.StatusOK, playScene{
		ID:     s.ID,
		Name:   s.Name,
		Status: s.Status,
	})
}

func getPlayCampaignGMStatusHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can read gm status")
		return
	}

	currentActor, _, found, err := dbGetPlayCampaignTurn(id)
	if err != nil {
		log.Printf("get play campaign turn: %v", err)
		badRequest(w, "failed to read campaign turn")
		return
	}
	if !found {
		notFound(w, "campaign not found")
		return
	}

	members, err := dbGetPlayMemberSummariesByCampaign(id)
	if err != nil {
		log.Printf("get play member summaries: %v", err)
		badRequest(w, "failed to read campaign members")
		return
	}

	events, err := dbGetPlayNarrationsByCampaign(id)
	if err != nil {
		log.Printf("get play narrations: %v", err)
		badRequest(w, "failed to read recent events")
		return
	}

	party := make([]gmPartyMember, 0, len(members))
	for _, m := range members {
		party = append(party, gmPartyMember{
			Username:    m.Username,
			CharacterID: m.CharacterID,
			Name:        m.Name,
			Class:       m.Class,
		})
	}

	writeJSON(w, http.StatusOK, gmTurnStatusResponse{
		NeedsAttention: currentActor != "" && currentActor == p.Owner,
		CurrentActor:   currentActor,
		Party:          party,
		RecentEvents:   events,
	})
}

func createPlayLocationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create locations")
		return
	}

	var req locationCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}

	loc := &playLocation{
		ID:         req.ID,
		CampaignID: id,
		Name:       req.Name,
	}
	if err := dbCreatePlayLocation(loc); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "location id already exists")
			return
		}
		log.Printf("create play location: %v", err)
		badRequest(w, "failed to create location")
		return
	}

	writeJSON(w, http.StatusCreated, playLocation{
		ID:   loc.ID,
		Name: loc.Name,
	})
}

func createPlayConnectionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create connections")
		return
	}

	fromID := r.PathValue("from_id")

	var req connectionCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ToID) == "" {
		badRequest(w, "to_id is required")
		return
	}
	if req.TravelTurns <= 0 {
		badRequest(w, "travel_turns must be a positive integer")
		return
	}

	missing, duplicate, err := dbCreatePlayConnection(id, fromID, req.ToID, req.TravelTurns)
	if err != nil {
		log.Printf("create play connection: %v", err)
		badRequest(w, "failed to create connection")
		return
	}
	if missing {
		badRequest(w, "location not found")
		return
	}
	if duplicate {
		badRequest(w, "connection already exists")
		return
	}

	writeJSON(w, http.StatusCreated, playConnection{
		FromID:      fromID,
		ToID:        req.ToID,
		TravelTurns: req.TravelTurns,
	})
}

func addPlayEncounterMonsterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can add monsters")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can add monsters")
		return
	}

	e, err := dbGetPlayEncounter(id, encID)
	if err != nil {
		log.Printf("get play encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return
	}
	if e == nil {
		notFound(w, "encounter not found")
		return
	}

	var req encounterMonsterCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.MonsterID) == "" {
		badRequest(w, "monster_id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if req.HPMax <= 0 {
		badRequest(w, "hp_max must be positive")
		return
	}

	m := &playEncounterMonster{
		MonsterID:  req.MonsterID,
		Name:       req.Name,
		HPMax:      req.HPMax,
		HPCurrent:  req.HPMax,
		Initiative: req.Initiative,
	}
	if err := dbCreatePlayEncounterMonster(id, encID, m); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "monster id already exists")
			return
		}
		log.Printf("create play encounter monster: %v", err)
		badRequest(w, "failed to add monster")
		return
	}

	writeJSON(w, http.StatusCreated, m)
}

func removePlayEncounterMonsterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can remove monsters")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	monsterID := r.PathValue("monster_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can remove monsters")
		return
	}

	e, err := dbGetPlayEncounter(id, encID)
	if err != nil {
		log.Printf("get play encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return
	}
	if e == nil {
		notFound(w, "encounter not found")
		return
	}

	removed, err := dbDeletePlayEncounterMonster(id, encID, monsterID)
	if err != nil {
		log.Printf("delete play encounter monster: %v", err)
		badRequest(w, "failed to remove monster")
		return
	}
	if !removed {
		notFound(w, "monster not found")
		return
	}

	writeJSON(w, http.StatusOK, encounterMonsterRemoveResponse{Removed: monsterID})
}

func bindPlayEncounterMemberHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can bind members")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can bind members")
		return
	}

	e, err := dbGetPlayEncounter(id, encID)
	if err != nil {
		log.Printf("get play encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return
	}
	if e == nil {
		notFound(w, "encounter not found")
		return
	}

	var req bindMemberRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Member) == "" {
		badRequest(w, "member is required")
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(req.Member, id)
	if err != nil {
		log.Printf("get membership: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		badRequest(w, "member not found")
		return
	}

	existing, err := dbGetPlayEncounterMemberCombatant(id, encID, req.Member)
	if err != nil {
		log.Printf("get member combatant: %v", err)
		badRequest(w, "failed to read combatant")
		return
	}
	if existing != nil {
		conflict(w, "member already bound")
		return
	}

	if err := dbCreatePlayEncounterMemberCombatant(id, encID, membership, req.Initiative); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "member already bound")
			return
		}
		log.Printf("create member combatant: %v", err)
		badRequest(w, "failed to bind member")
		return
	}

	writeJSON(w, http.StatusCreated, playEncounterMemberCombatant{
		Member:      membership.Username,
		CharacterID: membership.CharacterID,
		Name:        membership.Name,
		Initiative:  req.Initiative,
	})
}

func unbindPlayEncounterMemberHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can unbind members")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	member := r.PathValue("member")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can unbind members")
		return
	}

	e, err := dbGetPlayEncounter(id, encID)
	if err != nil {
		log.Printf("get play encounter: %v", err)
		badRequest(w, "failed to read encounter")
		return
	}
	if e == nil {
		notFound(w, "encounter not found")
		return
	}

	removed, err := dbDeletePlayEncounterMemberCombatant(id, encID, member)
	if err != nil {
		log.Printf("delete member combatant: %v", err)
		badRequest(w, "failed to unbind member")
		return
	}
	if !removed {
		notFound(w, "member not bound")
		return
	}

	writeJSON(w, http.StatusOK, unbindMemberResponse{Removed: member})
}

// encounterTurnKind normalizes the internal combatant kind for the public wire
// format: player characters are exposed as "player" rather than "member".
func encounterTurnKind(kind string) string {
	if kind == "member" {
		return "player"
	}
	return kind
}

func getPlayEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	active, round, turnIndex, found, err := dbGetPlayEncounterActive(id, encID)
	if err != nil {
		log.Printf("get play encounter turn: %v", err)
		badRequest(w, "failed to read encounter turn")
		return
	}
	if !found {
		notFound(w, "encounter not found")
		return
	}

	resp := encounterTurnResponse{Round: round, TurnIndex: turnIndex}
	if active != nil {
		resp.Active = &encounterTurnActive{
			Name:       active.Name,
			Kind:       encounterTurnKind(active.Kind),
			Initiative: active.Initiative,
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

func advancePlayEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner && !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	active, round, turnIndex, ok, err := dbAdvancePlayEncounterTurn(id, encID, u.Username, isOwner)
	if err != nil {
		log.Printf("advance play encounter turn: %v", err)
		badRequest(w, "failed to advance encounter turn")
		return
	}
	if !ok {
		conflict(w, "acting out of turn")
		return
	}

	resp := encounterTurnResponse{Round: round, TurnIndex: turnIndex}
	if active != nil {
		resp.Active = &encounterTurnActive{
			Name:       active.Name,
			Kind:       encounterTurnKind(active.Kind),
			Initiative: active.Initiative,
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

// validCombatActionTypes lists the action types accepted by the encounter
// combat action endpoint.
var validCombatActionTypes = map[string]bool{
	"attack": true,
	"help":   true,
	"dodge":  true,
	"ready":  true,
}

func submitCombatActionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	var req combatActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if !validCombatActionTypes[req.Type] {
		badRequest(w, "invalid action type")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	resp, ok, err := dbCreateCombatAction(id, encID, u.Username, &req)
	if err != nil {
		log.Printf("create combat action: %v", err)
		badRequest(w, "failed to create combat action")
		return
	}
	if !ok {
		conflict(w, "acting out of turn")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func damageEncounterCombatantHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can damage combatants")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	var req damageHealingRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Target) == "" {
		badRequest(w, "target is required")
		return
	}
	if req.Amount <= 0 {
		badRequest(w, "amount must be positive")
		return
	}

	resp, found, err := dbApplyDamage(id, encID, req.Target, req.Amount)
	if err != nil {
		log.Printf("apply damage: %v", err)
		badRequest(w, "failed to apply damage")
		return
	}
	if !found {
		notFound(w, "target not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func healEncounterCombatantHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can heal combatants")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	var req damageHealingRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Target) == "" {
		badRequest(w, "target is required")
		return
	}
	if req.Amount <= 0 {
		badRequest(w, "amount must be positive")
		return
	}

	resp, found, err := dbApplyHealing(id, encID, req.Target, req.Amount)
	if err != nil {
		log.Printf("apply healing: %v", err)
		badRequest(w, "failed to apply healing")
		return
	}
	if !found {
		notFound(w, "target not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func addPlayEncounterConditionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can apply conditions")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	var req encounterConditionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Target) == "" {
		badRequest(w, "target is required")
		return
	}
	if strings.TrimSpace(req.Condition) == "" {
		badRequest(w, "condition is required")
		return
	}
	if req.Duration <= 0 {
		badRequest(w, "duration_rounds must be a positive integer")
		return
	}

	if _, found, err := dbGetEncounterHealthTarget(id, encID, req.Target); err != nil {
		log.Printf("get encounter target: %v", err)
		badRequest(w, "failed to validate target")
		return
	} else if !found {
		notFound(w, "target not found")
		return
	}

	if err := dbCreatePlayEncounterCondition(id, encID, req.Target, req.Condition, req.Duration); err != nil {
		log.Printf("create encounter condition: %v", err)
		badRequest(w, "failed to apply condition")
		return
	}

	conds, err := dbGetPlayEncounterConditionsByTarget(id, encID, req.Target)
	if err != nil {
		log.Printf("get encounter conditions: %v", err)
		badRequest(w, "failed to read conditions")
		return
	}

	writeJSON(w, http.StatusCreated, encounterConditionResponse{
		Target:     req.Target,
		Conditions: conds,
	})
}

func getPlayEncounterStatusHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	active, round, turnIndex, found, err := dbGetPlayEncounterActive(id, encID)
	if err != nil {
		log.Printf("get play encounter status: %v", err)
		badRequest(w, "failed to read encounter status")
		return
	}
	if !found {
		notFound(w, "encounter not found")
		return
	}

	order, err := dbGetPlayEncounterTurnOrder(id, encID)
	if err != nil {
		log.Printf("get play encounter order: %v", err)
		badRequest(w, "failed to read encounter order")
		return
	}

	conditions, err := dbGetPlayEncounterConditions(id, encID)
	if err != nil {
		log.Printf("get play encounter conditions: %v", err)
		badRequest(w, "failed to read encounter conditions")
		return
	}

	resp := encounterStatusResponse{
		Round:      round,
		TurnIndex:  turnIndex,
		Order:      make([]encounterTurnActive, 0, len(order)),
		Conditions: conditions,
	}
	if active != nil {
		resp.Active = &encounterTurnActive{
			Name:       active.Name,
			Kind:       encounterTurnKind(active.Kind),
			Initiative: active.Initiative,
		}
	}
	for _, e := range order {
		resp.Order = append(resp.Order, encounterTurnActive{
			Name:       e.Name,
			Kind:       encounterTurnKind(e.Kind),
			Initiative: e.Initiative,
		})
	}

	writeJSON(w, http.StatusOK, resp)
}

// delayPlayEncounterTurnHandler moves the current encounter combatant to a
// later position in the initiative order. The caller must be the current
// combatant or the campaign owner. Reordering to an illegal index returns 400.
func delayPlayEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner && !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	active, _, _, found, err := dbGetPlayEncounterActive(id, encID)
	if err != nil {
		log.Printf("get play encounter turn: %v", err)
		badRequest(w, "failed to read encounter turn")
		return
	}
	if !found || active == nil {
		notFound(w, "encounter not found")
		return
	}

	isCurrentCombatant := active.Kind == "member" && active.Member == u.Username
	if !isOwner && !isCurrentCombatant {
		conflict(w, "acting out of turn")
		return
	}

	var req delayRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	var rawIndex *int
	if req.NewIndex != nil {
		rawIndex = req.NewIndex
	} else if req.Index != nil {
		rawIndex = req.Index
	} else if req.ToIndex != nil {
		rawIndex = req.ToIndex
	}
	if rawIndex == nil {
		badRequest(w, "index is required")
		return
	}
	newIndex := *rawIndex

	order, ok, invalid, err := dbDelayPlayEncounterTurn(id, encID, newIndex)
	if err != nil {
		log.Printf("delay play encounter turn: %v", err)
		badRequest(w, "failed to delay turn")
		return
	}
	if invalid {
		badRequest(w, "invalid index")
		return
	}
	if !ok {
		notFound(w, "encounter not found")
		return
	}

	resp := delayResponse{Order: make([]encounterTurnActive, 0, len(order))}
	for _, e := range order {
		resp.Order = append(resp.Order, encounterTurnActive{
			Name:       e.Name,
			Kind:       encounterTurnKind(e.Kind),
			Initiative: e.Initiative,
		})
	}
	writeJSON(w, http.StatusOK, resp)
}

// readyPlayEncounterTurnHandler records a ready action for the current
// encounter combatant. Only the current combatant may call it. The action is
// appended to the narration log but does not change the turn order.
func readyPlayEncounterTurnHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	active, _, _, found, err := dbGetPlayEncounterActive(id, encID)
	if err != nil {
		log.Printf("get play encounter turn: %v", err)
		badRequest(w, "failed to read encounter turn")
		return
	}
	if !found || active == nil {
		notFound(w, "encounter not found")
		return
	}

	isCurrentCombatant := active.Kind == "member" && active.Member == u.Username
	if !isCurrentCombatant {
		conflict(w, "acting out of turn")
		return
	}

	var req readyActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Trigger) == "" {
		badRequest(w, "trigger is required")
		return
	}

	resp, ok, err := dbCreateReadyAction(id, encID, u.Username, req.Trigger)
	if err != nil {
		log.Printf("create ready action: %v", err)
		badRequest(w, "failed to ready action")
		return
	}
	if !ok {
		notFound(w, "encounter not found")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

// awardEncounterRewardsHandler records deterministic XP and loot for an
// encounter. Only the campaign owner may award rewards, and rewards may be
// awarded only once per encounter.
func awardEncounterRewardsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can award rewards")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can award rewards")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	var req encounterRewardsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.XP < 0 {
		badRequest(w, "xp must be non-negative")
		return
	}
	for _, l := range req.Loot {
		if strings.TrimSpace(l.Slug) == "" {
			badRequest(w, "loot slug is required")
			return
		}
		if l.Quantity <= 0 {
			badRequest(w, "loot quantity must be positive")
			return
		}
	}

	if err := dbCreatePlayEncounterReward(id, encID, req.XP, req.Loot); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "rewards already awarded for this encounter")
			return
		}
		log.Printf("create encounter reward: %v", err)
		badRequest(w, "failed to award rewards")
		return
	}

	writeJSON(w, http.StatusOK, encounterRewardResponse{
		ID:   encID,
		XP:   req.XP,
		Loot: req.Loot,
	})
}

// closePlayEncounterHandler marks an encounter as closed. Only the campaign
// owner may close an encounter. The response reports the XP awarded, or zero
// if rewards were not yet awarded.
func closePlayEncounterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can close encounters")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can close this encounter")
		return
	}

	if requirePlayEncounter(w, id, encID) == nil {
		return
	}

	resp, err := dbClosePlayEncounter(id, encID)
	if err != nil {
		log.Printf("close play encounter: %v", err)
		badRequest(w, "failed to close encounter")
		return
	}
	if resp == nil {
		notFound(w, "encounter not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// endPlayEncounterHandler closes an active encounter and restores the campaign
// to its exploration turn queue. Only the campaign owner may call it. If the
// campaign is not currently in combat, it returns 409.
func endPlayEncounterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can end encounters")
		return
	}

	id := r.PathValue("id")
	encID := r.PathValue("enc_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can end this encounter")
		return
	}

	resp, err := dbEndPlayEncounter(id, encID)
	if err != nil {
		log.Printf("end play encounter: %v", err)
		badRequest(w, "failed to end encounter")
		return
	}
	if resp == nil {
		conflict(w, "campaign is not in combat")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func damageCharacterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can damage a character")
		return
	}

	var req struct {
		Amount int `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Amount <= 0 {
		badRequest(w, "amount must be positive")
		return
	}

	resp, found, err := dbApplyCharacterDamage(id, charID, req.Amount)
	if err != nil {
		log.Printf("apply character damage: %v", err)
		badRequest(w, "failed to apply damage")
		return
	}
	if !found {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func deathSavesHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	var req deathSavesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Outcome != "success" && req.Outcome != "failure" {
		badRequest(w, "outcome must be success or failure")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner can record death saves")
		return
	}

	resp, ok, conflicted, err := dbRecordDeathSave(id, charID, req.Outcome)
	if err != nil {
		log.Printf("record death save: %v", err)
		badRequest(w, "failed to record death save")
		return
	}
	if conflicted {
		conflict(w, "character is not unconscious")
		return
	}
	if !ok {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

func getCharacterStatusHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character status: %v", err)
		badRequest(w, "failed to read character status")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, characterStatusResponse{
		CharacterID: charID,
		HPCurrent:   m.HPCurrent,
		HPMax:       m.HPMax,
		Status:      m.Status,
	})
}

func getCharacterOwnerHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character owner: %v", err)
		badRequest(w, "failed to read character owner")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, characterOwnerResponse{
		CharacterID: charID,
		Owner:       m.Username,
	})
}

func claimCharacterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if u.Role != rolePlayer {
		forbidden(w, "only players may claim characters")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("claim character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != "" {
		conflict(w, "character already owned")
		return
	}

	claimed, err := dbClaimCharacter(id, charID, u.Username)
	if err != nil {
		log.Printf("claim character: %v", err)
		badRequest(w, "failed to claim character")
		return
	}
	if !claimed {
		conflict(w, "character already owned")
		return
	}

	writeJSON(w, http.StatusCreated, characterOwnerResponse{
		CharacterID: charID,
		Owner:       u.Username,
	})
}

func transferCharacterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	if u.Role != rolePlayer {
		forbidden(w, "only players may transfer characters")
		return
	}

	var req transferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.NewOwner) == "" {
		badRequest(w, "new_owner is required")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("transfer character: %v", err)
		badRequest(w, "failed to read character owner")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the owner may transfer this character")
		return
	}
	if req.NewOwner == u.Username {
		badRequest(w, "cannot transfer ownership to yourself")
		return
	}

	newOwner, err := dbGetPlayMembershipByUserAndCampaign(req.NewOwner, id)
	if err != nil {
		log.Printf("transfer character: %v", err)
		badRequest(w, "failed to read new owner")
		return
	}
	if newOwner == nil {
		forbidden(w, "new owner is not a campaign member")
		return
	}

	transferred, err := dbTransferCharacter(id, charID, u.Username, req.NewOwner)
	if err != nil {
		log.Printf("transfer character: %v", err)
		badRequest(w, "failed to transfer character")
		return
	}
	if !transferred {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, characterOwnerResponse{
		CharacterID: charID,
		Owner:       req.NewOwner,
	})
}

func buildCharacterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("build character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may build this character")
		return
	}

	var req characterBuildRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	req.Race = strings.ToLower(req.Race)
	req.Class = strings.ToLower(req.Class)
	req.Background = strings.ToLower(req.Background)

	if _, ok := validRaces[req.Race]; !ok {
		badRequest(w, "invalid race")
		return
	}
	if _, ok := validClasses[req.Class]; !ok {
		badRequest(w, "invalid class")
		return
	}
	if _, ok := validBackgrounds[req.Background]; !ok {
		badRequest(w, "invalid background")
		return
	}
	if err := validateAbilityScores(req.Abilities); err != nil {
		badRequest(w, "invalid ability scores")
		return
	}

	hitDie, ok := classHitDice[req.Class]
	if !ok {
		badRequest(w, "invalid class")
		return
	}
	hpMax := hitDie + abilityModifier(req.Abilities.Con)
	if hpMax < 1 {
		hpMax = 1
	}

	resp, ok, err := dbBuildCharacter(id, charID, &req, hpMax)
	if err != nil {
		log.Printf("build character: %v", err)
		badRequest(w, "failed to build character")
		return
	}
	if !ok {
		notFound(w, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func levelUpCharacterHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("level up character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may level up this character")
		return
	}

	var req levelUpRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level out of range")
		return
	}
	if req.Level != m.Level+1 {
		badRequest(w, "level must be exactly one higher than current level")
		return
	}

	resp, ok, err := dbLevelUpCharacter(id, charID, req.Level)
	if err != nil {
		log.Printf("level up character: %v", err)
		badRequest(w, "failed to level up character")
		return
	}
	if !ok {
		badRequest(w, "character has not been built")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func skillCheckHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	var req skillCheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	skill := strings.ToLower(req.Skill)
	if _, ok := validSkills[skill]; !ok {
		badRequest(w, "unsupported skill")
		return
	}
	ability := strings.ToLower(req.Ability)
	if _, ok := validAbilities[ability]; !ok {
		badRequest(w, "unsupported ability")
		return
	}

	csb, err := dbGetCharacterSkillBase(id, charID)
	if err != nil {
		log.Printf("skill check: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if csb == nil {
		notFound(w, "character not found")
		return
	}
	if csb.Username != u.Username {
		forbidden(w, "only the character owner may make a skill check")
		return
	}
	if !csb.Built {
		badRequest(w, "character has not been built")
		return
	}

	score, err := abilityScoreByName(csb.Abilities, ability)
	if err != nil {
		badRequest(w, "unsupported ability")
		return
	}

	modifier := abilityModifier(score)
	if req.Proficient {
		modifier += proficiencyBonus(csb.Level)
	}

	writeJSON(w, http.StatusOK, skillCheckResponse{
		CharacterID: charID,
		Skill:       skill,
		Ability:     ability,
		Modifier:    modifier,
		Total:       req.Roll + modifier,
	})
}

func getPlayLocationTravelHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	isOwner := p.Owner == u.Username
	if !isOwner {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
	}

	locID := r.PathValue("loc_id")
	loc, err := dbGetPlayLocation(id, locID)
	if err != nil {
		log.Printf("get play location: %v", err)
		badRequest(w, "failed to read location")
		return
	}
	if loc == nil {
		notFound(w, "location not found")
		return
	}

	dests, err := dbGetPlayLocationConnections(id, locID)
	if err != nil {
		log.Printf("get play location connections: %v", err)
		badRequest(w, "failed to read travel")
		return
	}

	writeJSON(w, http.StatusOK, travelResponse{Destinations: dests})
}
