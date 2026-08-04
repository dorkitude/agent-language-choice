package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
)

type playMember struct {
	Username    string
	CharacterID string
	Name        string
	Class       string
	HPCurrent   int
	HPMax       int

	// Status tracks the character's life state: "conscious" (default),
	// "unconscious" (at 0 hp, rolling death saves), "stable" (three death
	// save successes), or "dead" (three death save failures).
	Status string

	// DeathSaveSuccesses and DeathSaveFailures count death save rolls made
	// while unconscious. They reset only implicitly via a long rest healing
	// the character back to consciousness elsewhere in the codebase.
	DeathSaveSuccesses int
	DeathSaveFailures  int

	// Owner names the player identity currently holding this character. It is
	// set to the joining player at membership creation, but may later be
	// transferred to another campaign member independently of Username (which
	// keeps its original meaning for all pre-existing permission checks). A
	// zero-value Owner (as in state persisted before this field existed) means
	// the character is unowned and may be claimed by any player.
	Owner string

	// Level tracks the character's current level for level-up purposes. A
	// zero value (as in state persisted before this field existed) means
	// level 1.
	Level int

	// ConModifier is the character's Constitution modifier, captured from
	// the ability scores supplied to the character-build endpoint. It
	// defaults to 0 (as if Constitution were 10-11) until build is called.
	ConModifier int

	// StrModifier, DexModifier, IntModifier, WisModifier, and ChaModifier are
	// the character's remaining ability modifiers, captured alongside
	// ConModifier from the character-build endpoint. They default to 0
	// until build is called.
	StrModifier int
	DexModifier int
	IntModifier int
	WisModifier int
	ChaModifier int

	// Spells lists the spells this character currently knows, in the order
	// they were learned.
	Spells []playSpell

	// PreparedSpells lists the spell IDs this character currently has
	// prepared, in the order supplied to the prepared-spells endpoint.
	PreparedSpells []string

	// SpellSlotsUsed counts, by spell level, how many of the character's
	// spell slots of that level have been expended casting spells.
	SpellSlotsUsed map[int]int

	// Casts records the character's spell cast history in order.
	Casts []playCast

	// Concentration holds the character's currently active concentration
	// spell, or nil if no concentration is active.
	Concentration *playConcentration

	// Items maps held inventory item IDs to their held quantity.
	Items map[string]int

	// Equipment maps equipment slot ("armor" or "accessory") to the item
	// currently equipped there, if any.
	Equipment map[string]*playEquipmentSlot

	// AttunementCount tracks how many items are currently attuned for this
	// character, across all equipment slots.
	AttunementCount int

	// Gold is the character's current gold balance, seeded to 10 when the
	// character joins the campaign.
	Gold int

	// RewardXP is the cumulative XP this character has received from
	// awarded quest rewards.
	RewardXP int

	// RewardItems maps item IDs to the cumulative quantity this character
	// has received from awarded quest rewards.
	RewardItems map[string]int
}

// playEquipmentSlot is a single equipped item and its attunement state.
type playEquipmentSlot struct {
	ItemID  string
	Attuned bool
}

// playConcentration is a character's currently active concentration state.
type playConcentration struct {
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	RemainingTurns int    `json:"remaining_turns"`
}

// playSpell is a single known spell entry in a character's spellbook.
type playSpell struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// playCast is a single recorded spell cast event for a character.
type playCast struct {
	Sequence       int    `json:"sequence"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
}

// playAbilityModifier returns m's modifier for the named ability
// ("str", "dex", "con", "int", "wis", "cha").
func playAbilityModifier(m *playMember, ability string) (int, bool) {
	switch ability {
	case "str":
		return m.StrModifier, true
	case "dex":
		return m.DexModifier, true
	case "con":
		return m.ConModifier, true
	case "int":
		return m.IntModifier, true
	case "wis":
		return m.WisModifier, true
	case "cha":
		return m.ChaModifier, true
	default:
		return 0, false
	}
}

var validPlaySkills = map[string]bool{
	"acrobatics": true, "animal-handling": true, "arcana": true, "athletics": true,
	"deception": true, "history": true, "insight": true, "intimidation": true,
	"investigation": true, "medicine": true, "nature": true, "perception": true,
	"performance": true, "persuasion": true, "religion": true, "sleight-of-hand": true,
	"stealth": true, "survival": true,
}

// playMemberLevel returns m's current level, defaulting to 1 for zero-value
// members (created before leveling existed or before any level-up call).
func playMemberLevel(m *playMember) int {
	if m.Level == 0 {
		return 1
	}
	return m.Level
}

// playMemberOwner returns m's effective character owner, falling back to the
// joining Username when Owner has never been explicitly set.
func playMemberOwner(m *playMember) string {
	if m.Owner != "" {
		return m.Owner
	}
	return m.Username
}

// playMemberStatus returns m's life status, defaulting to "conscious" for
// zero-value members created before death saves existed.
func playMemberStatus(m *playMember) string {
	if m.Status == "" {
		return "conscious"
	}
	return m.Status
}

// findPlayMemberByCharacterID locates the member owning charID within c.
func findPlayMemberByCharacterID(c *playCampaign, charID string) *playMember {
	for _, m := range c.Members {
		if m.CharacterID == charID {
			return m
		}
	}
	return nil
}

type playEvent struct {
	Sequence      int    `json:"sequence"`
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	Type          string `json:"type,omitempty"`
	Target        string `json:"target,omitempty"`
	Text          string `json:"text"`
	DestinationID string `json:"destination_id,omitempty"`
	TravelTurns   int    `json:"travel_turns,omitempty"`
	HPCurrent     int    `json:"hp_current,omitempty"`
	HPMax         int    `json:"hp_max,omitempty"`
}

type playCampaign struct {
	ID           string
	Name         string
	Owner        string
	Status       string
	MaxPlayers   int
	Members      []*playMember
	CurrentActor string
	Phase        string
	TurnNumber   int
	Events       []*playEvent

	// TurnPlayerIndex tracks the index into Members of the player whose turn
	// it is (or most recently was, while the dm is resolving).
	TurnPlayerIndex int

	// TurnDeadline is a logical (non-wall-clock) tick by which the current
	// turn is expected to complete: it advances by a fixed window each time
	// the turn changes.
	TurnDeadline int

	// NudgeCount is a monotonically increasing counter of owner nudges sent
	// for the current turn's occupant.
	NudgeCount int

	// Story is the public campaign document text, visible to the owner and
	// all members.
	Story string

	// DMNotes is the owner-private portion of the campaign document; it must
	// never be disclosed to players.
	DMNotes string

	// Scenes indexes every scene ever created for this campaign by scene id.
	Scenes map[string]*playScene

	// CurrentSceneID names the scene the campaign is currently in, if any.
	CurrentSceneID string

	// Locations indexes every location ever created for this campaign by
	// location id.
	Locations map[string]*playLocation

	// CurrentLocationID names the location the party currently occupies. It
	// defaults to the first location ever created for the campaign.
	CurrentLocationID string

	// Encounters indexes every encounter ever created for this campaign by
	// encounter id.
	Encounters map[string]*playEncounter

	// InCombat reports whether the campaign currently has an active
	// encounter. It is independent from the exploration turn queue.
	InCombat bool

	// TransferSeq counts gold transfers ever recorded for this campaign, used
	// to assign deterministic, campaign-local transfer ids starting at 1.
	TransferSeq int

	// TransactionalTransferSeq counts successful transactional transfers ever
	// recorded for this campaign, used to assign deterministic sequence
	// numbers starting at 1. Simulated failures do not advance it.
	TransactionalTransferSeq int

	// TransactionalTransfers holds every successful transactional transfer
	// ever recorded for this campaign, in sequence order.
	TransactionalTransfers []*playTransactionalTransfer

	// Exports holds every immutable versioned export snapshot ever created
	// for this campaign, in ascending version order (version = index + 1).
	Exports []*playExport

	// Import holds the most recently applied compatible import snapshot for
	// this campaign, or nil if none has ever been applied.
	Import *playImport

	// Migration holds the most recently applied schema migration result for
	// this campaign, or nil if none has ever been applied.
	Migration *playMigration

	// Loot indexes every loot record ever created for this campaign by loot
	// id.
	Loot map[string]*playLoot

	// Relationships holds every directed relationship edge ever created for
	// this campaign, in insertion order.
	Relationships []*playRelationship

	// NPCs indexes every DM-managed NPC record ever created for this
	// campaign by npc id.
	NPCs map[string]*playNPC

	// Factions indexes every DM-managed faction record ever created for
	// this campaign by faction id.
	Factions map[string]*playFaction

	// Clues holds every campaign clue ever created, in insertion order.
	Clues []*playClue

	// SearchRecords holds every campaign search record ever created, in
	// insertion order.
	SearchRecords []*playSearchRecord

	// FeedEvents holds every campaign event feed entry ever appended, in
	// accepted append order.
	FeedEvents []*playFeedEvent

	// Quests holds every campaign quest ever created, in insertion order.
	Quests []*playQuest

	// WorldEvents holds every campaign world event ever scheduled, in
	// creation order.
	WorldEvents []*playWorldEvent

	// Calendar is the campaign's day/season calendar, once initialized by
	// the dm. Nil until initialized.
	Calendar *playCalendar

	// Settlements indexes every DM-managed settlement ever created for this
	// campaign by settlement id. SettlementOrder preserves creation order.
	Settlements     map[string]*playSettlement
	SettlementOrder []string

	// Recipes indexes every DM-managed crafting recipe ever created for this
	// campaign by recipe id. RecipeOrder preserves creation order.
	Recipes     map[string]*playRecipe
	RecipeOrder []string

	// DowntimeActivities indexes every DM-managed recurring downtime activity
	// ever created for this campaign by activity id.
	DowntimeActivities map[string]*playDowntimeActivity

	// DowntimeAllocations indexes every downtime allocation ever created for
	// this campaign by "characterID/activityID".
	DowntimeAllocations map[string]*playDowntimeAllocation

	// SessionZero holds the campaign's pre-start session-zero settings, once
	// set by the dm. Nil until set.
	SessionZero *playSessionZero

	// Content indexes every DM-authored content record ever created for this
	// campaign by content id. ContentOrder preserves creation order.
	Content      map[string]*playContent
	ContentOrder []string

	// Notes indexes every campaign note ever created for this campaign by
	// note id. NoteOrder preserves creation order.
	Notes     map[string]*playNote
	NoteOrder []string

	// Whispers indexes every character-to-character whisper ever sent in
	// this campaign by whisper id. WhisperOrder preserves creation order.
	Whispers     map[string]*playWhisper
	WhisperOrder []string

	// Invitations indexes every campaign invitation ever created for this
	// campaign by invitation id. InvitationOrder preserves creation order.
	Invitations     map[string]*playInvitation
	InvitationOrder []string

	// Delegations indexes the current (possibly inactive) GM delegation
	// record for this campaign by delegate username.
	Delegations map[string]*playDelegation

	// DelegationAudit holds every grant/revoke delegation audit entry ever
	// recorded for this campaign, in grant/revoke order.
	DelegationAudit []*playDelegationAuditEntry

	// AuditEvents holds every actor audit entry ever recorded for this
	// campaign, in timestamp order.
	AuditEvents []*playAuditEvent

	// AuditCorrelationIDs tracks correlation_id values already used for an
	// audit event in this campaign, to reject duplicates.
	AuditCorrelationIDs map[string]bool

	// AuditSeq is the deterministic per-campaign audit timestamp sequence; it
	// increments for every created audit entry.
	AuditSeq int

	// ProjectionEvents holds every projection event ever appended for this
	// campaign, in sequence order.
	ProjectionEvents []*playProjectionEvent

	// ProjectionEventIDs tracks event_id values already used for a projection
	// event in this campaign, to reject duplicates.
	ProjectionEventIDs map[string]bool

	// ProjectionSeq is the deterministic per-campaign projection event
	// sequence; it increments for every appended projection event.
	ProjectionSeq int

	// IdempotentEvents holds every idempotent event ever appended for this
	// campaign, in sequence order.
	IdempotentEvents []*playIdempotentEvent

	// IdempotentEventIDs tracks event_id values already used for an
	// idempotent event in this campaign, to reject duplicates.
	IdempotentEventIDs map[string]bool

	// IdempotencyKeys indexes the stored idempotent event by the
	// Idempotency-Key that created it, to detect replayed requests.
	IdempotencyKeys map[string]*playIdempotentEvent

	// IdempotentEventSeq is the deterministic per-campaign idempotent event
	// sequence; it increments for every appended idempotent event.
	IdempotentEventSeq int

	// RateEvents holds every accepted rate event for this campaign, in
	// acceptance order.
	RateEvents []*playRateEvent

	// RateEventIDs tracks event_id values already used for a rate event in
	// this campaign, to reject duplicates.
	RateEventIDs map[string]bool

	// RateEventCounts tracks the number of accepted rate events per
	// username for this campaign, to enforce the per-identity allowance.
	RateEventCounts map[string]int

	// MetricsAcceptedRateEvents counts accepted ticket 087 rate events.
	MetricsAcceptedRateEvents int

	// MetricsRejectedRateEvents counts ticket 087 rate events rejected with
	// HTTP 429.
	MetricsRejectedRateEvents int

	// MetricsProjectionEvents counts accepted ticket 079 projection event
	// appends.
	MetricsProjectionEvents int

	// SafeTurnCurrent is the campaign's safe-turn current turn number,
	// starting at 1. Zero means uninitialized (treated as 1).
	SafeTurnCurrent int

	// SafeTurns holds every accepted safe-turn submission for this campaign,
	// in acceptance order.
	SafeTurns []*playSafeTurn

	// SafeTurnSubmissionIDs tracks submission_id values already used for a
	// safe-turn submission in this campaign, to reject duplicates.
	SafeTurnSubmissionIDs map[string]bool

	// Backups holds every immutable campaign backup snapshot ever created
	// for this campaign, in creation (sequential backup_id) order.
	Backups []*playBackup

	// BackupSeq is the deterministic per-campaign backup sequence; it
	// increments for every created backup, yielding ids "backup-1",
	// "backup-2", and so on.
	BackupSeq int

	// ReplayEvents holds every successfully appended replay event for this
	// campaign, in append order.
	ReplayEvents []*playReplayEvent

	// ReplayEventIDs tracks event_id values already used for a replay event
	// in this campaign, to reject duplicates.
	ReplayEventIDs map[string]bool

	// ReplayEventSeq is the deterministic per-campaign replay event
	// sequence; it increments for every appended replay event.
	ReplayEventSeq int

	// RngSeed is the campaign's configured deterministic RNG seed. Empty
	// means no seed has been configured yet.
	RngSeed string

	// RngSeedSet reports whether RngSeed has been configured; distinguishes
	// an unset seed from a (disallowed) empty seed value.
	RngSeedSet bool

	// RngRolls holds every accepted RNG roll for this campaign, in append
	// (sequence) order.
	RngRolls []*playRngRoll

	// RngRollIDs tracks roll_id values already used in this campaign's RNG
	// ledger, to reject duplicates.
	RngRollIDs map[string]bool

	// RngRollSeq is the deterministic per-campaign RNG roll sequence; it
	// increments for every accepted roll, starting at 1.
	RngRollSeq int

	// ModerationReports holds every moderation report ever submitted for
	// this campaign, in append (sequence) order.
	ModerationReports []*playModerationReport

	// ModerationReportIDs tracks report_id values already used in this
	// campaign's moderation reports, to reject duplicates.
	ModerationReportIDs map[string]bool

	// ModerationReportSeq is the deterministic per-campaign moderation
	// report sequence; it increments for every accepted report, starting
	// at 1.
	ModerationReportSeq int

	// SafetyBlockedTags holds the campaign's current safety boundary tag
	// set, as last replaced by the DM.
	SafetyBlockedTags []string

	// SafetyEvents holds every accepted safety check event for this
	// campaign, in append (sequence) order.
	SafetyEvents []*playSafetyEvent

	// SafetyEventIDs tracks event_id values already accepted in this
	// campaign's safety checks, to reject duplicates.
	SafetyEventIDs map[string]bool

	// SafetyEventSeq is the deterministic per-campaign safety event
	// sequence; it increments for every accepted event, starting at 1.
	SafetyEventSeq int

	// FixtureSeeded records whether the canonical-v1 fixture has been
	// seeded for this campaign.
	FixtureSeeded bool
}

// playSessionZero is a campaign's session-zero settings: rules version,
// tone, and consent boundaries.
type playSessionZero struct {
	Rules   string   `json:"rules"`
	Tone    string   `json:"tone"`
	Consent []string `json:"consent"`
}

// turnDeadlineWindow is the fixed number of logical turns granted before a
// turn is considered overdue.
const turnDeadlineWindow = 10

var (
	playMu    sync.Mutex
	playStore = map[string]*playCampaign{}
)

func playCampaignResponse(c *playCampaign) map[string]interface{} {
	return map[string]interface{}{
		"id":          c.ID,
		"name":        c.Name,
		"owner":       c.Owner,
		"status":      c.Status,
		"max_players": c.MaxPlayers,
	}
}

func playMemberResponse(username string, m *playMember) map[string]interface{} {
	return map[string]interface{}{
		"username":     username,
		"character_id": m.CharacterID,
		"name":         m.Name,
		"class":        m.Class,
	}
}

// playCampaignSubPath splits a "/v1/play/campaigns/{id}/{rest}" path.
func playCampaignSubPath(path string) (id, rest string, ok bool) {
	const prefix = "/v1/play/campaigns/"
	if !strings.HasPrefix(path, prefix) {
		return "", "", false
	}
	trimmed := strings.TrimPrefix(path, prefix)
	parts := strings.SplitN(trimmed, "/", 2)
	if len(parts) == 0 || parts[0] == "" {
		return "", "", false
	}
	if len(parts) == 1 {
		return parts[0], "", true
	}
	return parts[0], parts[1], true
}

// authenticatePlay parses the Authorization header of the form
// "Bearer session-<username>". A missing header or malformed prefix is not
// authenticated at all (401). A well-formed header names an actor even if
// that username was never registered; callers treat an unresolved account as
// having no privileged role, which yields 403 rather than 401 for
// authorization failures.
func authenticatePlay(r *http.Request) (username string, formatOK bool) {
	const prefix = "Bearer session-"
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, prefix) {
		return "", false
	}
	username = strings.TrimPrefix(auth, prefix)
	if username == "" {
		return "", false
	}
	return username, true
}

func lookupPlayAccount(username string) *userAccount {
	userMu.Lock()
	defer userMu.Unlock()
	return userStore[username]
}

// requirePlayCampaign looks up campaignID in playStore. It must be called
// with playMu already held. On a missing campaign it unlocks playMu, writes
// a 404, and returns ok=false; callers must return immediately in that case
// without unlocking again.
func requirePlayCampaign(w http.ResponseWriter, campaignID string) (c *playCampaign, ok bool) {
	c, exists := playStore[campaignID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return nil, false
	}
	return c, true
}

func handleCreatePlayCampaign(w http.ResponseWriter, r *http.Request) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	account := lookupPlayAccount(username)
	if account == nil || account.Role != "dm" {
		writeError(w, http.StatusForbidden, "only a dm may create a play campaign")
		return
	}

	var req struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		MaxPlayers *int   `json:"max_players"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.MaxPlayers == nil {
		writeError(w, http.StatusBadRequest, "id, name, and max_players are required")
		return
	}

	playMu.Lock()
	if _, exists := playStore[req.ID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "play campaign id already exists")
		return
	}
	c := &playCampaign{
		ID:         req.ID,
		Name:       req.Name,
		Owner:      account.Username,
		Status:     "lobby",
		MaxPlayers: *req.MaxPlayers,
	}
	playStore[req.ID] = c
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playCampaignResponse(c))
}

func handlePlayCampaignsCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleCreatePlayCampaign(w, r)
}

func handlePlayCampaignsSub(w http.ResponseWriter, r *http.Request) {
	id, rest, ok := playCampaignSubPath(r.URL.Path)
	if !ok || id == "" || rest == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}

	if rest == "members" {
		handlePlayCampaignMembers(w, r, id)
		return
	}

	if rest == "start" {
		handleStartPlayCampaign(w, r, id)
		return
	}

	if rest == "narrations" {
		handlePlayCampaignNarrations(w, r, id)
		return
	}

	if rest == "messages" {
		handlePlayCampaignMessages(w, r, id)
		return
	}

	if handlePlayCampaignDelegationsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignSpectatorsSub(w, r, id, rest) {
		return
	}

	if rest == "audit-events" {
		handlePlayCampaignAuditEvents(w, r, id)
		return
	}

	if handlePlayCampaignProjectionSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignIdempotentEventsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignRateEventsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignMetricsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignServiceModeSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignSafeTurnsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignTransactionalTransfersSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignExportsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignImportsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignMigrationsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignBackupsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignReplaySub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignRngLedgerSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignModerationSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignSafetySub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignFixtureSub(w, r, id, rest) {
		return
	}

	if rest == "turn/nudge" {
		handlePlayCampaignTurnNudge(w, r, id)
		return
	}

	if rest == "turn/travel" {
		handlePlayCampaignTurnTravel(w, r, id)
		return
	}

	if rest == "turn/rest" {
		handlePlayCampaignTurnRest(w, r, id)
		return
	}

	if rest == "turn" {
		handlePlayCampaignTurn(w, r, id)
		return
	}

	if rest == "my-turn" {
		handlePlayCampaignMyTurn(w, r, id)
		return
	}

	if rest == "gm/status" {
		handlePlayCampaignGMStatus(w, r, id)
		return
	}

	if rest == "actions" {
		handlePlayCampaignActions(w, r, id)
		return
	}

	if rest == "resolutions" {
		handlePlayCampaignResolutions(w, r, id)
		return
	}

	if rest == "document" {
		handlePlayCampaignDocument(w, r, id)
		return
	}

	if rest == "session-zero" {
		handlePlayCampaignSessionZero(w, r, id)
		return
	}

	if rest == "onboarding" {
		handlePlayCampaignOnboarding(w, r, id)
		return
	}

	if rest == "scenes" {
		handleCreateScene(w, r, id)
		return
	}

	if rest == "scenes/current" {
		handleCurrentScene(w, r, id)
		return
	}

	if strings.HasPrefix(rest, "scenes/") {
		sceneRest := strings.TrimPrefix(rest, "scenes/")
		if sceneID, ok := strings.CutSuffix(sceneRest, "/enter"); ok && sceneID != "" {
			handleEnterScene(w, r, id, sceneID)
			return
		}
		if sceneID, ok := strings.CutSuffix(sceneRest, "/close"); ok && sceneID != "" {
			handleCloseScene(w, r, id, sceneID)
			return
		}
	}

	if rest == "encounters" {
		handleCreatePlayEncounter(w, r, id)
		return
	}

	if strings.HasPrefix(rest, "encounters/") {
		encRest := strings.TrimPrefix(rest, "encounters/")
		parts := strings.SplitN(encRest, "/", 2)
		if len(parts) == 2 && parts[0] != "" {
			encID := parts[0]
			if parts[1] == "monsters" {
				handleCreateEncounterMonster(w, r, id, encID)
				return
			}
			if monsterID, ok := strings.CutPrefix(parts[1], "monsters/"); ok && monsterID != "" {
				handleRemoveEncounterMonster(w, r, id, encID, monsterID)
				return
			}
			if parts[1] == "combatants" {
				handleBindEncounterCombatant(w, r, id, encID)
				return
			}
			if member, ok := strings.CutPrefix(parts[1], "combatants/"); ok && member != "" {
				handleUnbindEncounterCombatant(w, r, id, encID, member)
				return
			}
			if parts[1] == "turn" {
				handleGetEncounterTurn(w, r, id, encID)
				return
			}
			if parts[1] == "turn/advance" {
				handleAdvanceEncounterTurn(w, r, id, encID)
				return
			}
			if parts[1] == "turn/delay" {
				handleDelayEncounterTurn(w, r, id, encID)
				return
			}
			if parts[1] == "turn/ready" {
				handleReadyEncounterTurn(w, r, id, encID)
				return
			}
			if parts[1] == "actions" {
				handleEncounterAction(w, r, id, encID)
				return
			}
			if parts[1] == "damage" {
				handleEncounterDamage(w, r, id, encID)
				return
			}
			if parts[1] == "heal" {
				handleEncounterHeal(w, r, id, encID)
				return
			}
			if parts[1] == "conditions" {
				handleEncounterConditions(w, r, id, encID)
				return
			}
			if parts[1] == "status" {
				handleEncounterStatus(w, r, id, encID)
				return
			}
			if parts[1] == "rewards" {
				handleEncounterRewards(w, r, id, encID)
				return
			}
			if parts[1] == "close" {
				handleEncounterClose(w, r, id, encID)
				return
			}
			if parts[1] == "end" {
				handleEncounterEnd(w, r, id, encID)
				return
			}
		}
	}

	if strings.HasPrefix(rest, "characters/") {
		charRest := strings.TrimPrefix(rest, "characters/")
		parts := strings.SplitN(charRest, "/", 2)
		if len(parts) == 2 && parts[0] != "" {
			charID := parts[0]
			switch parts[1] {
			case "damage":
				handlePlayCharacterDamage(w, r, id, charID)
				return
			case "status":
				handlePlayCharacterStatus(w, r, id, charID)
				return
			case "death-saves":
				handlePlayCharacterDeathSaves(w, r, id, charID)
				return
			case "owner":
				handlePlayCharacterOwner(w, r, id, charID)
				return
			case "claim":
				handlePlayCharacterClaim(w, r, id, charID)
				return
			case "transfer":
				handlePlayCharacterTransfer(w, r, id, charID)
				return
			case "build":
				handlePlayCharacterBuild(w, r, id, charID)
				return
			case "level-up":
				handlePlayLevelUp(w, r, id, charID)
				return
			case "skill-check":
				handlePlaySkillCheck(w, r, id, charID)
				return
			case "spells":
				handlePlayCharacterSpells(w, r, id, charID)
				return
			case "prepared-spells":
				handlePlayCharacterPreparedSpells(w, r, id, charID)
				return
			case "casts":
				handlePlayCharacterCasts(w, r, id, charID)
				return
			case "concentration":
				handlePlayCharacterConcentration(w, r, id, charID)
				return
			case "concentration/advance-turn":
				handlePlayCharacterConcentrationAdvanceTurn(w, r, id, charID)
				return
			case "inventory/items":
				handlePlayCharacterInventoryItems(w, r, id, charID)
				return
			case "currency":
				handlePlayCharacterCurrency(w, r, id, charID)
				return
			case "currency/transfers":
				handlePlayCharacterCurrencyTransfer(w, r, id, charID)
				return
			case "rewards":
				handleGetPlayCharacterRewards(w, r, id, charID)
				return
			case "downtime/allocations":
				handleCreatePlayDowntimeAllocation(w, r, id, charID)
				return
			case "sheet":
				handlePlayCharacterSheet(w, r, id, charID)
				return
			}
			if allocRest, ok := strings.CutPrefix(parts[1], "downtime/allocations/"); ok && allocRest != "" {
				if activityID, ok := strings.CutSuffix(allocRest, "/progress"); ok && activityID != "" {
					handlePlayDowntimeAllocationProgress(w, r, id, charID, activityID)
					return
				}
				handleGetPlayDowntimeAllocation(w, r, id, charID, allocRest)
				return
			}
			if itemID, ok := strings.CutPrefix(parts[1], "inventory/items/"); ok && itemID != "" {
				if consumeItemID, ok := strings.CutSuffix(itemID, "/consume"); ok && consumeItemID != "" {
					handlePlayCharacterInventoryItemConsume(w, r, id, charID, consumeItemID)
					return
				}
				handlePlayCharacterInventoryItemRemove(w, r, id, charID, itemID)
				return
			}
			if slot, ok := strings.CutPrefix(parts[1], "equipment/"); ok && slot != "" {
				if attuneSlot, ok := strings.CutSuffix(slot, "/attune"); ok && attuneSlot != "" {
					handlePlayCharacterAttune(w, r, id, charID, attuneSlot)
					return
				}
				handlePlayCharacterEquipmentSlot(w, r, id, charID, slot)
				return
			}
		}
	}

	if handlePlayCampaignLootSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignNPCSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignRelationshipSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignCluesSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignSearchRecordsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignFeedEventsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignFactionSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignQuestSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignWorldEventSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignCalendarSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignSettlementSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignRecipeSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignContentSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignNotesSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignWhispersSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignInvitationsSub(w, r, id, rest) {
		return
	}

	if handlePlayCampaignDowntimeSub(w, r, id, rest) {
		return
	}

	if rest == "locations" {
		handleCreateLocation(w, r, id)
		return
	}

	if strings.HasPrefix(rest, "locations/") {
		locRest := strings.TrimPrefix(rest, "locations/")
		if locID, ok := strings.CutSuffix(locRest, "/connections"); ok && locID != "" {
			handleCreateLocationConnection(w, r, id, locID)
			return
		}
		if locID, ok := strings.CutSuffix(locRest, "/travel"); ok && locID != "" {
			handleLocationTravel(w, r, id, locID)
			return
		}
	}

	writeError(w, http.StatusNotFound, "not found")
}

// playTurnQueue builds the deterministic turn queue: each member's turn is
// followed by the dm's turn, in join order.
func playTurnQueue(c *playCampaign) []string {
	queue := make([]string, 0, len(c.Members)*2)
	for _, m := range c.Members {
		queue = append(queue, m.Username, "dm")
	}
	return queue
}

// isPlayMember reports whether username is the owner of or a member in c.
func isPlayMember(c *playCampaign, username string) bool {
	if c.Owner == username {
		return true
	}
	for _, m := range c.Members {
		if m.Username == username {
			return true
		}
	}
	return false
}

func handlePlayCampaignTurn(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view the turn state")
		return
	}

	resp := map[string]interface{}{
		"campaign_id":      c.ID,
		"current_actor":    c.CurrentActor,
		"phase":            c.Phase,
		"turn_number":      c.TurnNumber,
		"queue":            playTurnQueue(c),
		"logical_deadline": c.TurnNumber + 1,
		"overdue":          c.NudgeCount > 0,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCampaignTurnNudge lets the owner nudge the current turn's
// occupant with a reminder message. Only the campaign owner may call this;
// nudge_count increases monotonically with each nudge sent during the
// current turn.
func handlePlayCampaignTurnNudge(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Message string `json:"message"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Message == "" {
		writeError(w, http.StatusBadRequest, "message is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may nudge")
		return
	}

	c.NudgeCount++
	c.Events = append(c.Events, &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "nudge",
		Actor:    "dm",
		Text:     req.Message,
	})
	resp := map[string]interface{}{
		"actor":       "dm",
		"target":      c.CurrentActor,
		"message":     req.Message,
		"nudge_count": c.NudgeCount,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handlePlayCampaignTurnTravel lets the active player consume their
// exploration turn to travel along a valid outbound connection from the
// party's current location. Only the current actor may call this, and only
// to a location that is a valid outbound connection; acting out of turn or
// naming an invalid destination returns 409. On success the turn passes to
// the dm, mirroring handlePlayCampaignActions.
func handlePlayCampaignTurnTravel(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		DestinationID string `json:"destination_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.DestinationID == "" {
		writeError(w, http.StatusBadRequest, "destination_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.CurrentActor != username {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "it is not this player's turn")
		return
	}

	var currentLoc *playLocation
	if c.CurrentLocationID != "" {
		currentLoc = c.Locations[c.CurrentLocationID]
	}
	var conn *playLocationConnection
	if currentLoc != nil {
		for _, cn := range currentLoc.Connections {
			if cn.ToID == req.DestinationID {
				conn = cn
				break
			}
		}
	}
	if conn == nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "invalid travel destination")
		return
	}

	ev := &playEvent{
		Sequence:      len(c.Events) + 1,
		Kind:          "travel",
		Actor:         username,
		DestinationID: conn.ToID,
		TravelTurns:   conn.TravelTurns,
	}
	c.Events = append(c.Events, ev)
	c.CurrentLocationID = conn.ToID
	c.CurrentActor = c.Owner
	c.Phase = "dm"
	c.TurnDeadline = c.TurnNumber + turnDeadlineWindow
	c.NudgeCount = 0
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence":       ev.Sequence,
		"kind":           ev.Kind,
		"actor":          ev.Actor,
		"destination_id": ev.DestinationID,
		"travel_turns":   ev.TravelTurns,
		"next_actor":     "dm",
	})
}

// handlePlayCampaignTurnRest lets the active player consume their
// exploration turn to take a short or long rest. Only the current actor may
// call this; a long rest restores the acting character's hp_current to
// hp_max. Acting out of turn or naming an invalid rest type returns 409/400.
// On success the turn passes to the dm, mirroring handlePlayCampaignActions.
func handlePlayCampaignTurnRest(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Type string `json:"type"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Type != "short" && req.Type != "long" {
		writeError(w, http.StatusBadRequest, "type must be \"short\" or \"long\"")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.CurrentActor != username {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "it is not this player's turn")
		return
	}

	var member *playMember
	for _, m := range c.Members {
		if m.Username == username {
			member = m
			break
		}
	}
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "only a party member may rest")
		return
	}

	if req.Type == "long" {
		member.HPCurrent = member.HPMax
	}

	ev := &playEvent{
		Sequence:  len(c.Events) + 1,
		Kind:      "rest",
		Actor:     username,
		Type:      req.Type,
		HPCurrent: member.HPCurrent,
		HPMax:     member.HPMax,
	}
	c.Events = append(c.Events, ev)
	c.CurrentActor = c.Owner
	c.Phase = "dm"
	c.TurnDeadline = c.TurnNumber + turnDeadlineWindow
	c.NudgeCount = 0
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence":   ev.Sequence,
		"kind":       ev.Kind,
		"actor":      ev.Actor,
		"type":       ev.Type,
		"hp_current": ev.HPCurrent,
		"hp_max":     ev.HPMax,
		"next_actor": "dm",
	})
}

// handlePlayCampaignMyTurn returns the caller's own turn context: whether it
// is currently their turn, who the current actor is, their own character
// (never another member's), and the recent event log. Only a campaign member
// with the "player" role may call this; it never exposes DM-private fields.
func handlePlayCampaignMyTurn(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	account := lookupPlayAccount(username)
	if account == nil || account.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may view their turn context")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	var member *playMember
	for _, m := range c.Members {
		if m.Username == username {
			member = m
			break
		}
	}
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a member of this campaign may view their turn context")
		return
	}

	events := make([]*playEvent, len(c.Events))
	copy(events, c.Events)

	resp := map[string]interface{}{
		"is_my_turn":    c.CurrentActor == username,
		"current_actor": c.CurrentActor,
		"character": map[string]interface{}{
			"id":   member.CharacterID,
			"name": member.Name,
		},
		"recent_events": events,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCampaignGMStatus returns the owner's turn-management view: whether
// the campaign is waiting on the owner to act, the current actor, a summary
// of each party member, and the recent event log. Only the campaign owner may
// call this; any other authenticated user receives 403.
func handlePlayCampaignGMStatus(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may view gm status")
		return
	}

	party := make([]map[string]interface{}, 0, len(c.Members))
	for _, m := range c.Members {
		party = append(party, map[string]interface{}{
			"username":     m.Username,
			"character_id": m.CharacterID,
			"name":         m.Name,
			"class":        m.Class,
			"is_current":   c.CurrentActor == m.Username,
		})
	}

	events := make([]*playEvent, len(c.Events))
	copy(events, c.Events)

	resp := map[string]interface{}{
		"needs_attention": c.CurrentActor == c.Owner,
		"current_actor":   c.CurrentActor,
		"party":           party,
		"recent_events":   events,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handlePlayCampaignNarrations(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playDelegateHasPower(c, username, "narrate") {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm owner or a narrate delegate may narrate")
		return
	}

	actor := "dm"
	if c.Owner != username {
		actor = username
	}

	ev := &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "narration",
		Actor:    actor,
		Text:     req.Text,
	}
	c.Events = append(c.Events, ev)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, ev)
}

func handleStartPlayCampaign(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm owner may start this campaign")
		return
	}
	if c.Status != "lobby" || len(c.Members) < 2 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "play campaign cannot be started")
		return
	}

	c.Status = "active"
	c.CurrentActor = c.Members[0].Username
	c.Phase = "player"
	c.TurnNumber = 1
	c.TurnPlayerIndex = 0
	c.TurnDeadline = c.TurnNumber + turnDeadlineWindow
	c.NudgeCount = 0
	resp := map[string]interface{}{
		"id":            c.ID,
		"status":        c.Status,
		"current_actor": c.CurrentActor,
		"turn_number":   c.TurnNumber,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCampaignActions lets the active player submit a game action. Only
// the member whose turn it currently is may call this; a waiting player or
// the dm owner receives 409. On success the turn passes to the dm.
func handlePlayCampaignActions(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Type == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "type and text are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if username == c.Owner {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "the dm may not submit a player action")
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a member of this campaign may submit an action")
		return
	}
	if c.CurrentActor != username {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "it is not this player's turn")
		return
	}

	ev := &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "action",
		Actor:    username,
		Type:     req.Type,
		Text:     req.Text,
	}
	c.Events = append(c.Events, ev)
	c.CurrentActor = c.Owner
	c.Phase = "dm"
	c.TurnDeadline = c.TurnNumber + turnDeadlineWindow
	c.NudgeCount = 0
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence":   ev.Sequence,
		"kind":       ev.Kind,
		"actor":      ev.Actor,
		"type":       ev.Type,
		"text":       ev.Text,
		"next_actor": "dm",
	})
}

// handlePlayCampaignMessages lets any campaign member (including the dm)
// post an in-party chat message. Chat is unrestricted by turn order.
func handlePlayCampaignMessages(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a member of this campaign may chat")
		return
	}

	ev := &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "chat",
		Actor:    username,
		Text:     req.Text,
	}
	c.Events = append(c.Events, ev)
	currentActor := c.CurrentActor
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence":      ev.Sequence,
		"kind":          ev.Kind,
		"actor":         ev.Actor,
		"text":          ev.Text,
		"current_actor": currentActor,
	})
}

// handlePlayCampaignResolutions lets the dm owner resolve the current
// player's action. Only the owner may call this; a player receives 409. On
// success the turn advances to the next member in join order and the turn
// number increments.
func handlePlayCampaignResolutions(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if username != c.Owner {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "only the owner may resolve")
		return
	}
	if len(c.Members) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "play campaign has no members")
		return
	}

	ev := &playEvent{
		Sequence: len(c.Events) + 1,
		Kind:     "resolution",
		Actor:    "dm",
		Text:     req.Text,
	}
	c.Events = append(c.Events, ev)

	nextIdx := 0
	if len(c.Members) > 1 {
		nextIdx = 1
	}
	if c.TurnNumber >= 2 {
		nextIdx = 0
	}
	c.TurnPlayerIndex = nextIdx
	c.CurrentActor = c.Members[c.TurnPlayerIndex].Username
	c.Phase = "player"
	c.TurnNumber++
	c.TurnDeadline = c.TurnNumber + turnDeadlineWindow
	c.NudgeCount = 0
	nextActor := c.CurrentActor
	turnNumber := c.TurnNumber
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"sequence":    ev.Sequence,
		"kind":        ev.Kind,
		"actor":       ev.Actor,
		"text":        ev.Text,
		"next_actor":  nextActor,
		"turn_number": turnNumber,
	})
}

func handlePlayCampaignMembers(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	account := lookupPlayAccount(username)
	if account == nil || account.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may join a play campaign")
		return
	}

	var req struct {
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Class       string `json:"class"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" || req.Name == "" || req.Class == "" {
		writeError(w, http.StatusBadRequest, "character_id, name, and class are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	for _, m := range c.Members {
		if m.Username == username {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "player already has a membership in this campaign")
			return
		}
		if m.CharacterID == req.CharacterID {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "character id already in use in this campaign")
			return
		}
	}
	if len(c.Members) >= c.MaxPlayers {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "play campaign party is full")
		return
	}

	m := &playMember{
		Username:    username,
		CharacterID: req.CharacterID,
		Name:        req.Name,
		Class:       req.Class,
		HPCurrent:   20,
		HPMax:       20,
		Owner:       username,
		Gold:        10,
	}
	c.Members = append(c.Members, m)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playMemberResponse(username, m))
}

// handlePlayCampaignDocument gets or updates the durable role-filtered
// campaign document. Only the owner may update it (PUT); the owner receives
// both fields on GET, while a member receives only the public story and
// never the dm_notes field.
func handlePlayCampaignDocument(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	switch r.Method {
	case http.MethodPut:
		var req struct {
			Story   string `json:"story"`
			DMNotes string `json:"dm_notes"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}

		playMu.Lock()
		c, ok := requirePlayCampaign(w, campaignID)
		if !ok {
			return
		}
		if c.Owner != username {
			playMu.Unlock()
			writeError(w, http.StatusForbidden, "only the owner may update the campaign document")
			return
		}

		c.Story = req.Story
		c.DMNotes = req.DMNotes
		resp := map[string]interface{}{
			"story":    c.Story,
			"dm_notes": c.DMNotes,
		}
		playMu.Unlock()
		persistState()

		writeJSON(w, http.StatusOK, resp)

	case http.MethodGet:
		playMu.Lock()
		c, ok := requirePlayCampaign(w, campaignID)
		if !ok {
			return
		}
		if !isPlayMember(c, username) {
			playMu.Unlock()
			writeError(w, http.StatusForbidden, "only the owner or a member may view the campaign document")
			return
		}

		var resp map[string]interface{}
		if c.Owner == username {
			resp = map[string]interface{}{
				"story":    c.Story,
				"dm_notes": c.DMNotes,
			}
		} else {
			resp = map[string]interface{}{
				"story": c.Story,
			}
		}
		playMu.Unlock()

		writeJSON(w, http.StatusOK, resp)

	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

// handlePlayCampaignOnboarding returns a role-specific list of onboarding next
// steps for an authenticated member of the campaign. The owner/DM and player
// members receive fixed, role-specific responses; the response never depends
// on map iteration order and never mutates campaign state.
func handlePlayCampaignOnboarding(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view onboarding")
		return
	}
	isOwner := c.Owner == username
	playMu.Unlock()

	var resp map[string]interface{}
	if isOwner {
		resp = map[string]interface{}{
			"role":       "dm",
			"next_steps": []string{"configure-safety", "invite-players", "start-campaign"},
			"can_mutate": true,
		}
	} else {
		resp = map[string]interface{}{
			"role":       "player",
			"next_steps": []string{"review-party", "take-turn", "submit-action"},
			"can_mutate": true,
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func playSessionZeroResponse(s *playSessionZero) map[string]interface{} {
	return map[string]interface{}{
		"rules":   s.Rules,
		"tone":    s.Tone,
		"consent": s.Consent,
	}
}

func handlePlayCampaignSessionZero(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	switch r.Method {
	case http.MethodPut:
		var req struct {
			Rules   string   `json:"rules"`
			Tone    string   `json:"tone"`
			Consent []string `json:"consent"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		if req.Rules == "" || req.Tone == "" || len(req.Consent) == 0 {
			writeError(w, http.StatusBadRequest, "rules, tone, and a nonempty consent list are required")
			return
		}
		seen := map[string]bool{}
		for _, item := range req.Consent {
			if item == "" || seen[item] {
				writeError(w, http.StatusBadRequest, "consent must contain unique nonempty strings")
				return
			}
			seen[item] = true
		}

		playMu.Lock()
		c, ok := requirePlayCampaign(w, campaignID)
		if !ok {
			return
		}
		if c.Owner != username {
			playMu.Unlock()
			writeError(w, http.StatusForbidden, "only the dm owner may set session-zero settings")
			return
		}
		if c.Status != "lobby" {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "session-zero settings can only be changed in the lobby")
			return
		}

		c.SessionZero = &playSessionZero{
			Rules:   req.Rules,
			Tone:    req.Tone,
			Consent: append([]string{}, req.Consent...),
		}
		resp := playSessionZeroResponse(c.SessionZero)
		playMu.Unlock()
		persistState()

		writeJSON(w, http.StatusOK, resp)

	case http.MethodGet:
		playMu.Lock()
		c, ok := requirePlayCampaign(w, campaignID)
		if !ok {
			return
		}
		if !isPlayMember(c, username) {
			playMu.Unlock()
			writeError(w, http.StatusForbidden, "only the owner or a member may view session-zero settings")
			return
		}
		if c.SessionZero == nil {
			playMu.Unlock()
			writeError(w, http.StatusNotFound, "session-zero settings not set")
			return
		}
		resp := playSessionZeroResponse(c.SessionZero)
		playMu.Unlock()

		writeJSON(w, http.StatusOK, resp)

	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}
