package main

import "sync"

// Well-known user roles.
const (
	roleDM     = "dm"
	rolePlayer = "player"
)

// Well-known play-campaign statuses.
const (
	campaignStatusLobby  = "lobby"
	campaignStatusActive = "active"
)

// Well-known invitation statuses.
const (
	invitationStatusPending  = "pending"
	invitationStatusAccepted = "accepted"
)

// Well-known quest statuses.
const (
	questStatusActive    = "active"
	questStatusCompleted = "completed"
	questStatusBlocked   = "blocked"
)

// Well-known crafting project statuses.
const (
	craftingStatusActive   = "active"
	craftingStatusComplete = "complete"
)

// Well-known scene statuses.
const (
	sceneStatusOpen   = "open"
	sceneStatusClosed = "closed"
)

// Well-known encounter statuses.
const (
	encounterStatusActive = "active"
	encounterStatusClosed = "closed"
)

// Well-known play quest states.
const (
	playQuestStateLocked    = "locked"
	playQuestStateActive    = "active"
	playQuestStateCompleted = "completed"
)

// Well-known character life states.
const (
	characterStatusConscious   = "conscious"
	characterStatusUnconscious = "unconscious"
	characterStatusStable      = "stable"
	characterStatusDead        = "dead"
)

// --- Auth and runtime state ---

// user represents an authenticated account loaded from SQLite at startup
// and mirrored in memory so login checks do not require a DB round-trip.
type user struct {
	Username     string
	PasswordHash string
	Role         string
}

// userStore is the in-memory mirror of the users table. It is protected by
// its own mutex because login checks are frequent and read-heavy.
type userStore struct {
	users map[string]*user
	mu    sync.RWMutex
}

// session is the in-memory runtime state for a single combat encounter. The
// durable source of truth is the SQLite tables combat_sessions, combat_order
// and combat_conditions; the cache is rebuilt from those tables on startup.
type session struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []orderEntry
	Conditions map[string][]condition // keyed by combatant name
}

// combatState holds the in-memory cache of all combat sessions.
type combatState struct {
	sessions map[string]*session
	mu       sync.RWMutex
}

// combatantInput is the request shape for initiative computation.
type combatantInput struct {
	Name string `json:"name"`
	Dex  int    `json:"dex"`
	Roll int    `json:"roll"`
}

// orderEntry is the public initiative result for a single combatant.
type orderEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

// condition tracks a temporary status effect on a combatant.
type condition struct {
	Condition string `json:"condition"`
	Remaining int    `json:"remaining_rounds"`
}

// --- Compendium ---

// monster is a compendium entry for a monster stat block.
type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags,omitempty"`
}

// item is a compendium entry for a piece of equipment or treasure.
type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

// --- Campaign state ---

// campaign is the top-level campaign container.
type campaign struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

// character is a campaign participant.
type character struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

// campaignEvent is a campaign log entry (e.g. a session recap hook).
type campaignEvent struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary,omitempty"`
}

// encounterMonsterGroup is an internal grouping used by encounter difficulty
// math. It differs from the wire format in that it is already collapsed to a
// count per CR.
type encounterMonsterGroup struct {
	CR    string
	Count int
}

// --- Campaign subsystems ---

// quest represents a campaign quest and its milestone aggregate counts.
type quest struct {
	ID         string `json:"id"`
	CampaignID string `json:"-"`
	Title      string `json:"title"`
	Status     string `json:"status"`
	Total      int    `json:"milestones_total"`
	Done       int    `json:"milestones_done"`
}

// questCreateRequest is the wire shape for creating a quest.
type questCreateRequest struct {
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Status     string   `json:"status"`
	Milestones []string `json:"milestones"`
}

// lootItem is a single entry from a treasure parcel.
type lootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// faction is a campaign power group or organization with a stance toward the party.
type faction struct {
	ID         string `json:"id"`
	CampaignID string `json:"-"`
	Name       string `json:"name"`
	Stance     string `json:"stance"`
}

// npc is a non-player character tied to a campaign and a faction.
type npc struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

// inventoryItem is a quantity of an item held by a party or owner within a campaign.
type inventoryItem struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

// equipmentAssignment is a quantity of an item given to a specific character.
type equipmentAssignment struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

// craftingProject represents a downtime crafting effort in a campaign.
type craftingProject struct {
	ID            string `json:"id"`
	CampaignID    string `json:"-"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	CostGP        int    `json:"cost_gp,omitempty"`
	Status        string `json:"status"`
}

// craftingProjectResponse is the public wire shape for a crafting project.
// It omits the campaign id and cost_gp from the default response.
type craftingProjectResponse struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

// campaignSession is a scheduled play session for a campaign.
type campaignSession struct {
	ID              string   `json:"id"`
	CampaignID      string   `json:"-"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes int      `json:"duration_minutes"`
	Agenda          []string `json:"agenda,omitempty"`
}

// sessionResponse is the public wire shape for a scheduled session.
type sessionResponse struct {
	ID              string `json:"id"`
	StartsAt        string `json:"starts_at"`
	DurationMinutes int    `json:"duration_minutes"`
	AgendaCount     int    `json:"agenda_count"`
}

// nextSessionResponse is the public wire shape for the next upcoming session.
// It omits duration_minutes to match the spec for the next-session endpoint.
type nextSessionResponse struct {
	ID          string `json:"id"`
	StartsAt    string `json:"starts_at"`
	AgendaCount int    `json:"agenda_count"`
}

// attendanceRequest records which characters are present or absent for a session.
type attendanceRequest struct {
	Present []string `json:"present"`
	Absent  []string `json:"absent"`
}

// attendanceResponse is the public wire shape for recorded attendance.
type attendanceResponse struct {
	SessionID    string `json:"session_id"`
	PresentCount int    `json:"present_count"`
	AbsentCount  int    `json:"absent_count"`
}

// --- Campaign analytics ---

// auditResponse is the public wire shape for the campaign audit endpoint.
type auditResponse struct {
	CampaignID string `json:"campaign_id"`
	Events     int    `json:"events"`
	Quests     int    `json:"quests"`
	NPCs       int    `json:"npcs"`
	Sessions   int    `json:"sessions"`
}

// exportResponse is the public wire shape for the deterministic campaign export.
type exportResponse struct {
	CampaignID     string `json:"campaign_id"`
	Name           string `json:"name"`
	Characters     int    `json:"characters"`
	Quests         int    `json:"quests"`
	NPCs           int    `json:"npcs"`
	InventoryItems int    `json:"inventory_items"`
	Sessions       int    `json:"sessions"`
	SchemaVersion  int    `json:"schema_version"`
}

// analyticsSummaryResponse is the public wire shape for the campaign analytics
// summary endpoint. It aggregates counts accumulated across the campaign state.
type analyticsSummaryResponse struct {
	CampaignID        string `json:"campaign_id"`
	ReadinessScore    int    `json:"readiness_score"`
	OpenQuests        int    `json:"open_quests"`
	FriendlyNPCs      int    `json:"friendly_npcs"`
	ScheduledSessions int    `json:"scheduled_sessions"`
	InventoryItems    int    `json:"inventory_items"`
}

// riskSignals groups the boolean maintenance signals for a campaign.
type riskSignals struct {
	HasDM          bool `json:"has_dm"`
	HasCharacters  bool `json:"has_characters"`
	HasNextSession bool `json:"has_next_session"`
	HasActiveQuest bool `json:"has_active_quest"`
}

// riskReportResponse is the public wire shape for the campaign risk report.
type riskReportResponse struct {
	CampaignID string      `json:"campaign_id"`
	RiskLevel  string      `json:"risk_level"`
	Missing    []string    `json:"missing"`
	Signals    riskSignals `json:"signals"`
}

// riskReportRequest is the accepted request shape for the risk report endpoint.
type riskReportRequest struct {
	IncludeZeroes bool `json:"include_zeroes"`
}

// thresholds bundles the daily encounter difficulty thresholds for one or more
// party members. Easy/medium/hard/deadly are the canonical D&D 5e budget names.
type thresholds struct {
	easy, medium, hard, deadly int
}

// --- Play-surface campaigns ---

// playCampaign is an owned, play-surface campaign used by the /v1/play APIs.
type playCampaign struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Owner      string `json:"owner"`
	Status     string `json:"status"`
	MaxPlayers int    `json:"max_players"`
}

// playCampaignCreateRequest is the wire shape for creating a play campaign.
type playCampaignCreateRequest struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	MaxPlayers int    `json:"max_players"`
}

// playMembership is a player's character in a play-surface campaign.
type playMembership struct {
	CampaignID  string `json:"-"`
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
	Level       int    `json:"-"`
	HPCurrent   int    `json:"-"`
	HPMax       int    `json:"-"`
	Status      string `json:"-"`
	Successes   int    `json:"-"`
	Failures    int    `json:"-"`
}

// playMembershipRequest is the accepted request shape for joining a campaign.
type playMembershipRequest struct {
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// playMembershipResponse is the public wire shape returned when a player joins.
type playMembershipResponse struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// playCampaignStartResponse is the public wire shape returned when a DM-owner
// starts a lobby campaign.
type playCampaignStartResponse struct {
	ID           string `json:"id"`
	Status       string `json:"status"`
	CurrentActor string `json:"current_actor"`
	TurnNumber   int    `json:"turn_number"`
}

// playCampaignTurnResponse is the public wire shape for the turn reader.
// It exposes the campaign's current play phase and turn pointer to the owner
// or any member of the campaign, plus deterministic timeout metadata.
type playCampaignTurnResponse struct {
	CampaignID      string   `json:"campaign_id"`
	CurrentActor    string   `json:"current_actor"`
	Phase           string   `json:"phase"`
	TurnNumber      int      `json:"turn_number"`
	Queue           []string `json:"queue"`
	Overdue         bool     `json:"overdue"`
	LogicalDeadline int      `json:"logical_deadline"`
}

// playerTurnResponse is the public wire shape for the player-only turn
// context endpoint. It exposes whether it is the caller's turn, the current
// actor, the caller's own character, and recent public narrations.
type playerTurnResponse struct {
	IsMyTurn     bool           `json:"is_my_turn"`
	CurrentActor string         `json:"current_actor"`
	Character    playerTurnChar `json:"character"`
	RecentEvents []narration    `json:"recent_events"`
}

// playerTurnChar is the subset of a membership exposed to a player through
// the my-turn context endpoint. It contains only the caller's own character
// id and name; class and other fields are intentionally omitted.
type playerTurnChar struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// narration is a DM narration event appended to a play campaign.
type narration struct {
	Sequence int    `json:"sequence"`
	Kind     string `json:"kind"`
	Actor    string `json:"actor"`
	Text     string `json:"text"`
	Type     string `json:"type,omitempty"`
}

// narrationRequest is the accepted request shape for appending a narration.
type narrationRequest struct {
	Text string `json:"text"`
}

// actionRequest is the accepted request shape for submitting a player action.
type actionRequest struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// actionResponse is the public wire shape returned when an active player
// submits an action.
type actionResponse struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Type      string `json:"type"`
	Text      string `json:"text"`
	NextActor string `json:"next_actor"`
}

// resolutionRequest is the accepted request shape for submitting a GM resolution.
type resolutionRequest struct {
	Text string `json:"text"`
}

// resolutionResponse is the public wire shape returned when the active GM
// resolves the current turn.
type resolutionResponse struct {
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Actor      string `json:"actor"`
	Text       string `json:"text"`
	NextActor  string `json:"next_actor"`
	TurnNumber int    `json:"turn_number"`
}

// gmTurnStatusResponse is the public wire shape for the owner-only GM
// dashboard. It shows whether the GM needs to act, whose turn it is, a
// summary of every party member, and recent public narrations.
type gmTurnStatusResponse struct {
	NeedsAttention bool            `json:"needs_attention"`
	CurrentActor   string          `json:"current_actor"`
	Party          []gmPartyMember `json:"party"`
	RecentEvents   []narration     `json:"recent_events"`
}

// gmPartyMember is the summary of a single party member shown to the GM.
type gmPartyMember struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
}

// nudgeRequest is the accepted request shape for the owner nudge endpoint.
type nudgeRequest struct {
	Message string `json:"message"`
}

// nudgeResponse is the public wire shape returned when the owner nudges the
// current actor. It records the actor, the nudged target, the message, and the
// monotonically increasing nudge count for the campaign.
type nudgeResponse struct {
	Actor      string `json:"actor"`
	Target     string `json:"target"`
	Message    string `json:"message"`
	NudgeCount int    `json:"nudge_count"`
}

// campaignDocument is the owner-visible wire shape for a campaign document.
// It includes both the public story and the private DM notes.
type campaignDocument struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// campaignDocumentRequest is the accepted request shape for updating a
// campaign document.
type campaignDocumentRequest struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// campaignDocumentPublic is the player-visible wire shape for a campaign
// document. It deliberately omits DM notes.
type campaignDocumentPublic struct {
	Story string `json:"story"`
}

// sessionZeroSettings is the pre-start campaign session-zero configuration
// for rules version, tone, and consent boundaries. It is both the request
// and response shape for the session-zero endpoints.
type sessionZeroSettings struct {
	Rules   string   `json:"rules"`
	Tone    string   `json:"tone"`
	Consent []string `json:"consent"`
}

// content is a campaign content record with deterministic tags.
type content struct {
	ContentID string   `json:"content_id"`
	Kind      string   `json:"kind"`
	Text      string   `json:"text"`
	Tags      []string `json:"tags"`
}

// contentUpdateTagsRequest is the accepted request shape for replacing a
// content record's tags.
type contentUpdateTagsRequest struct {
	Tags []string `json:"tags"`
}

// playScene is a scene belonging to a play campaign.
type playScene struct {
	ID         string `json:"id"`
	CampaignID string `json:"-"`
	Name       string `json:"name"`
	Status     string `json:"status"`
}

// playSceneCreateRequest is the wire shape for creating a scene.
type playSceneCreateRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// playSceneEnterResponse is the wire shape returned when an owner enters a
// scene for a campaign.
type playSceneEnterResponse struct {
	CurrentSceneID string `json:"current_scene_id"`
	Name           string `json:"name"`
}

// playSceneCloseResponse is the wire shape returned when an owner closes a
// scene. It deliberately omits the scene name to match the stage contract.
type playSceneCloseResponse struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

// playLocation is a named place in a campaign's location graph.
type playLocation struct {
	ID         string `json:"id"`
	CampaignID string `json:"-"`
	Name       string `json:"name"`
}

// locationCreateRequest is the accepted shape for creating a location.
type locationCreateRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// playConnection is a one-way travel link between two campaign locations.
type playConnection struct {
	FromID      string `json:"from_id"`
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// connectionCreateRequest is the accepted shape for creating a connection.
type connectionCreateRequest struct {
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

// travelDestination is a single outbound destination in the travel response.
type travelDestination struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	TravelTurns int    `json:"travel_turns"`
}

// travelResponse is the public wire shape for reading valid outbound travel.
type travelResponse struct {
	Destinations []travelDestination `json:"destinations"`
}

// travelRequest is the accepted shape for consuming a turn to travel.
type travelRequest struct {
	DestinationID string `json:"destination_id"`
}

// travelEventResponse is the public wire shape returned when the active player
// consumes a turn to travel to a valid connected destination.
type travelEventResponse struct {
	Sequence      int    `json:"sequence"`
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	DestinationID string `json:"destination_id"`
	TravelTurns   int    `json:"travel_turns"`
	NextActor     string `json:"next_actor"`
}

// restRequest is the accepted request shape for submitting a rest turn.
type restRequest struct {
	Type string `json:"type"`
}

// restEventResponse is the public wire shape returned when the active player
// consumes a turn to take a short or long rest.
type restEventResponse struct {
	Sequence  int    `json:"sequence"`
	Kind      string `json:"kind"`
	Actor     string `json:"actor"`
	Type      string `json:"type"`
	HPCurrent int    `json:"hp_current"`
	HPMax     int    `json:"hp_max"`
	NextActor string `json:"next_actor"`
}

// --- Play encounters ---

// playEncounter is a campaign-bound combat encounter.
type playEncounter struct {
	ID             string `json:"id"`
	CampaignID     string `json:"-"`
	Name           string `json:"name"`
	Status         string `json:"status"`
	PreCombatActor string `json:"-"`
}

// playCampaignEndResponse is the public wire shape returned when an active
// encounter ends and the campaign returns to exploration.
type playCampaignEndResponse struct {
	CampaignID   string `json:"campaign_id"`
	Status       string `json:"status"`
	Phase        string `json:"phase"`
	CurrentActor string `json:"current_actor"`
}

// encounterCreateRequest is the accepted shape for creating an encounter.
type encounterCreateRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// encounterResponse is the public wire shape returned when an encounter is
// created. It omits the campaign id and exposes the (initially empty) list of
// combatants.
type encounterResponse struct {
	ID         string          `json:"id"`
	Name       string          `json:"name"`
	Status     string          `json:"status"`
	Combatants []playCombatant `json:"combatants"`
}

// playCombatant is a single participant in a play encounter.
type playCombatant struct {
	Name string `json:"name"`
}

// playEncounterMonster is a deterministic monster combatant added to an encounter.
type playEncounterMonster struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	HPCurrent  int    `json:"hp_current"`
	Initiative int    `json:"initiative"`
}

// encounterMonsterCreateRequest is the accepted shape for adding a monster to an encounter.
type encounterMonsterCreateRequest struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
}

// encounterMonsterRemoveResponse is the public shape returned when a monster is removed.
type encounterMonsterRemoveResponse struct {
	Removed string `json:"removed"`
}

// playEncounterMemberCombatant is a campaign party member bound to an active
// encounter as a combatant.
type playEncounterMemberCombatant struct {
	Member      string `json:"member"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Initiative  int    `json:"initiative"`
}

// bindMemberRequest is the accepted shape for binding a party member to an encounter.
type bindMemberRequest struct {
	Member     string `json:"member"`
	Initiative int    `json:"initiative"`
}

// unbindMemberResponse is the public shape returned when a member combatant is removed.
type unbindMemberResponse struct {
	Removed string `json:"removed"`
}

// encounterTurnActive is the active combatant exposed by the encounter turn
// endpoints. It carries the public name, kind (monster or player), and the
// initiative value that determined the turn order.
type encounterTurnActive struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`
	Initiative int    `json:"initiative"`
}

// encounterTurnResponse is the public wire shape for the current encounter turn.
type encounterTurnResponse struct {
	Round     int                  `json:"round"`
	TurnIndex int                  `json:"turn_index"`
	Active    *encounterTurnActive `json:"active"`
}

// encounterTurnEntry is the internal, ordered representation of a single
// encounter combatant used to resolve turn authority and advancement.
type encounterTurnEntry struct {
	Name       string
	Kind       string // "monster" or "member"
	Initiative int
	Member     string // username for members; empty for monsters
	TargetID   string // monster_id for monsters; member username for members
}

// combatActionRequest is the accepted shape for submitting a combat action.
type combatActionRequest struct {
	Type   string `json:"type"`
	Target string `json:"target"`
	Text   string `json:"text"`
}

// combatActionResponse is the public wire shape returned when the current
// encounter combatant records a combat action.
type combatActionResponse struct {
	Sequence int    `json:"sequence"`
	Kind     string `json:"kind"`
	Actor    string `json:"actor"`
	Type     string `json:"type"`
	Target   string `json:"target"`
	Text     string `json:"text"`
}

// damageHealingRequest is the accepted shape for applying damage or healing
// to an encounter combatant.
type damageHealingRequest struct {
	Target string `json:"target"`
	Amount int    `json:"amount"`
}

// encounterConditionRequest is the accepted shape for applying a named
// condition to an encounter combatant.
type encounterConditionRequest struct {
	Target    string `json:"target"`
	Condition string `json:"condition"`
	Duration  int    `json:"duration_rounds"`
}

// encounterConditionResponse is the public wire shape returned when a
// condition is applied to an encounter combatant.
type encounterConditionResponse struct {
	Target     string      `json:"target"`
	Conditions []condition `json:"conditions"`
}

// encounterStatusResponse is the public wire shape for the full encounter
// state reader, including the initiative order and active conditions.
type encounterStatusResponse struct {
	Round      int                    `json:"round"`
	TurnIndex  int                    `json:"turn_index"`
	Active     *encounterTurnActive   `json:"active"`
	Order      []encounterTurnActive  `json:"order"`
	Conditions map[string][]condition `json:"conditions"`
}

// damageResponse is the public wire shape returned when the owner applies
// damage to an encounter combatant or a campaign character.
type damageResponse struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Damage   int    `json:"damage"`
}

// healingResponse is the public wire shape returned when the owner applies
// healing to an encounter combatant.
type healingResponse struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Healing  int    `json:"healing"`
}

// characterStatusResponse is the public wire shape for a character's current
// life state. It is used by the character status reader.
type characterStatusResponse struct {
	CharacterID string `json:"character_id"`
	HPCurrent   int    `json:"hp_current"`
	HPMax       int    `json:"hp_max"`
	Status      string `json:"status"`
}

// characterOwnerResponse is the public wire shape for a character's owner.
type characterOwnerResponse struct {
	CharacterID string `json:"character_id"`
	Owner       string `json:"owner"`
}

// transferRequest is the accepted request shape for transferring character
// ownership.
type transferRequest struct {
	NewOwner string `json:"new_owner"`
}

// deathSavesResponse is the public wire shape returned when a character's
// owner records a death saving throw.
type deathSavesResponse struct {
	CharacterID string `json:"character_id"`
	Successes   int    `json:"successes"`
	Failures    int    `json:"failures"`
	Status      string `json:"status"`
}

// deathSavesRequest is the accepted request shape for recording a death save.
type deathSavesRequest struct {
	Outcome string `json:"outcome"`
}

// readyActionRequest is the accepted request shape for readying an action.
type readyActionRequest struct {
	Trigger string `json:"trigger"`
}

// readyActionResponse is the public wire shape returned when the current
// combatant readies an action.
type readyActionResponse struct {
	Actor   string `json:"actor"`
	Trigger string `json:"trigger"`
}

// delayRequest is the accepted request shape for delaying a turn. The index
// may be supplied as new_index, index, or to_index; they are checked in that
// order.
type delayRequest struct {
	NewIndex *int `json:"new_index"`
	Index    *int `json:"index"`
	ToIndex  *int `json:"to_index"`
}

// delayResponse is the public wire shape returned when a combatant delays.
type delayResponse struct {
	Order []encounterTurnActive `json:"order"`
}

// encounterRewardsRequest is the accepted shape for awarding encounter rewards.
type encounterRewardsRequest struct {
	XP   int        `json:"xp"`
	Loot []lootItem `json:"loot"`
}

// encounterRewardResponse is the public wire shape returned when the owner
// awards deterministic XP and loot for an encounter.
type encounterRewardResponse struct {
	ID   string     `json:"id"`
	XP   int        `json:"xp"`
	Loot []lootItem `json:"loot"`
}

// encounterCloseResponse is the public wire shape returned when the owner
// closes an encounter. It reports the encounter id, its new status, and the
// XP that was awarded (zero if rewards were not yet awarded).
type encounterCloseResponse struct {
	ID        string `json:"id"`
	Status    string `json:"status"`
	XPAwarded int    `json:"xp_awarded"`
}

// --- Character build ---

// abilities is the canonical six ability-score block for a character.
type abilities struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

// characterBuildRequest is the accepted shape for the character build endpoint.
type characterBuildRequest struct {
	Race       string    `json:"race"`
	Class      string    `json:"class"`
	Background string    `json:"background"`
	Abilities  abilities `json:"abilities"`
}

// characterBuildResponse is the public wire shape returned when a character's
// owner submits validated race/class/background choices and ability scores.
type characterBuildResponse struct {
	CharacterID      string `json:"character_id"`
	Race             string `json:"race"`
	Class            string `json:"class"`
	Background       string `json:"background"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// levelUpRequest is the accepted shape for the character level-up endpoint.
type levelUpRequest struct {
	Level int `json:"level"`
}

// levelUpResponse is the public wire shape returned when a character's owner
// advances the character by exactly one level.
type levelUpResponse struct {
	CharacterID      string `json:"character_id"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	HitDice          string `json:"hit_dice"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// skillCheckRequest is the accepted shape for a character skill check.
type skillCheckRequest struct {
	Skill      string `json:"skill"`
	Ability    string `json:"ability"`
	Proficient bool   `json:"proficient"`
	Roll       int    `json:"roll"`
}

// skillCheckResponse is the public wire shape returned when a skill check is
// resolved using the character's stored ability score and level.
type skillCheckResponse struct {
	CharacterID string `json:"character_id"`
	Skill       string `json:"skill"`
	Ability     string `json:"ability"`
	Modifier    int    `json:"modifier"`
	Total       int    `json:"total"`
}

// spell is a single spell known by a character.
type spell struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// spellbook is the public wire shape for a character's known spells.
type spellbook struct {
	Spells []spell `json:"spells"`
}

// spellCreateRequest is the accepted request shape for adding a spell to a
// character's spellbook.
type spellCreateRequest struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// preparedSpellsRequest is the accepted request shape for setting a
// character's prepared spells.
type preparedSpellsRequest struct {
	SpellIDs []string `json:"spell_ids"`
}

// preparedSpellsResponse is the public wire shape for a character's prepared
// spells. An empty list is rendered as [], never omitted or null.
type preparedSpellsResponse struct {
	CharacterID    string   `json:"character_id"`
	PreparedSpells []string `json:"prepared_spells"`
	MaxPrepared    int      `json:"max_prepared"`
}

// castSpellRequest is the accepted request shape for casting a spell.
type castSpellRequest struct {
	SpellID string `json:"spell_id"`
	Target  string `json:"target"`
}

// castEvent is the public wire shape for a recorded spell cast.
type castEvent struct {
	CharacterID    string `json:"character_id"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
	Sequence       int    `json:"sequence"`
}

// castHistoryResponse is the public wire shape for a character's cast history.
// An empty list is rendered as [], never omitted or null.
type castHistoryResponse struct {
	Casts []castEvent `json:"casts"`
}

// concentration tracks a spell a character is currently concentrating on.
type concentration struct {
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	RemainingTurns int    `json:"remaining_turns"`
}

// concentrationResponse is the public wire shape for a character's
// concentration state. A nil pointer renders as JSON null.
type concentrationResponse struct {
	CharacterID   string         `json:"character_id"`
	Concentration *concentration `json:"concentration"`
}

// concentrationRequest is the accepted request shape for starting or replacing
// concentration on a spell.
type concentrationRequest struct {
	SpellID       string `json:"spell_id"`
	Target        string `json:"target"`
	DurationTurns int    `json:"duration_turns"`
}

// characterInventoryStack is a single held item stack on a play-surface
// character.
type characterInventoryStack struct {
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// characterInventoryStackRequest is the accepted shape for adding or removing
// an item stack.
type characterInventoryStackRequest struct {
	ItemID   string `json:"item_id,omitempty"`
	Quantity int    `json:"quantity"`
}

// characterInventoryStackResponse is the public wire shape returned when an
// item stack is modified. Quantity reports the amount requested; total_quantity
// reports the resulting stack size.
type characterInventoryStackResponse struct {
	CharacterID   string `json:"character_id"`
	ItemID        string `json:"item_id"`
	Quantity      int    `json:"quantity"`
	TotalQuantity int    `json:"total_quantity"`
}

// characterInventoryResponse is the public wire shape for reading all held
// items on a character. Items are always rendered as a list, never omitted.
type characterInventoryResponse struct {
	CharacterID string                    `json:"character_id"`
	Items       []characterInventoryStack `json:"items"`
}

// characterEquipmentSlot is the public wire shape for a single equipped item
// slot on a play-surface character. An empty slot renders item_id as the empty
// string and attuned as false.
type characterEquipmentSlot struct {
	CharacterID string `json:"character_id"`
	Slot        string `json:"slot"`
	ItemID      string `json:"item_id"`
	Attuned     bool   `json:"attuned"`
}

// characterAttunementResponse is the public wire shape returned when a
// character owner successfully attunes an equipped accessory.
type characterAttunementResponse struct {
	CharacterID     string `json:"character_id"`
	Slot            string `json:"slot"`
	ItemID          string `json:"item_id"`
	Attuned         bool   `json:"attuned"`
	AttunementCount int    `json:"attunement_count"`
	MaxAttunements  int    `json:"max_attunements"`
}

// consumableEffect describes the deterministic outcome of consuming an item.
type consumableEffect struct {
	Type       string `json:"type"`
	HPRestored int    `json:"hp_restored"`
}

// consumeItemResponse is the public wire shape returned when a character owner
// consumes a held consumable item.
type consumeItemResponse struct {
	CharacterID      string           `json:"character_id"`
	ItemID           string           `json:"item_id"`
	QuantityConsumed int              `json:"quantity_consumed"`
	TotalQuantity    int              `json:"total_quantity"`
	Effect           consumableEffect `json:"effect"`
}

// currencyResponse is the public wire shape for a character's gold balance.
type currencyResponse struct {
	CharacterID string `json:"character_id"`
	Gold        int    `json:"gold"`
}

// goldTransferRequest is the accepted request shape for a character-to-
// character gold transfer.
type goldTransferRequest struct {
	ToCharacterID string `json:"to_character_id"`
	Gold          int    `json:"gold"`
}

// goldTransferResponse is the public wire shape returned when a gold transfer
// succeeds. It includes the post-transfer balances and the campaign-local
// transfer id.
type goldTransferResponse struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Gold            int    `json:"gold"`
	FromGold        int    `json:"from_gold"`
	ToGold          int    `json:"to_gold"`
	TransferID      int    `json:"transfer_id"`
}

// --- Loot distribution ---

const (
	lootStatusOpen     = "open"
	lootStatusAssigned = "assigned"
)

// lootRecord is the durable, immutable loot record for a play campaign.
type lootRecord struct {
	LootID               string         `json:"loot_id"`
	ItemID               string         `json:"item_id"`
	Quantity             int            `json:"quantity"`
	Status               string         `json:"status"`
	RecipientCharacterID string         `json:"recipient_character_id"`
	Votes                map[string]int `json:"votes"`
}

// lootCreateRequest is the accepted shape for creating a loot record.
type lootCreateRequest struct {
	LootID   string `json:"loot_id"`
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// lootCreateResponse is the public wire shape returned when a DM creates a
// loot record. It deliberately omits the unset recipient and vote count.
type lootCreateResponse struct {
	LootID   string `json:"loot_id"`
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
	Status   string `json:"status"`
}

// lootVoteRequest is the accepted shape for casting a loot vote.
type lootVoteRequest struct {
	RecipientCharacterID string `json:"recipient_character_id"`
}

// lootVoteResponse is the public wire shape returned when a player casts a
// vote for a loot recipient. votes_for_recipient reports the total votes for
// that recipient after the vote is recorded.
type lootVoteResponse struct {
	LootID               string `json:"loot_id"`
	Voter                string `json:"voter"`
	RecipientCharacterID string `json:"recipient_character_id"`
	VotesForRecipient    int    `json:"votes_for_recipient"`
}

// lootAssignResponse is the public wire shape returned when a DM assigns loot
// to the unambiguous highest-voted recipient.
type lootAssignResponse struct {
	LootID               string `json:"loot_id"`
	RecipientCharacterID string `json:"recipient_character_id"`
	ItemID               string `json:"item_id"`
	Quantity             int    `json:"quantity"`
	Votes                int    `json:"votes"`
	Status               string `json:"status"`
}

// --- Play NPC agendas ---

// playNPC is a DM-managed campaign NPC with a private agenda and a
// player-visible public status.
type playNPC struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// npcCreateRequest is the accepted shape for creating a play NPC.
type npcCreateRequest struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// npcAgendaUpdateRequest is the accepted shape for updating a play NPC's
// private agenda and public status.
type npcAgendaUpdateRequest struct {
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// npcPublicResponse is the player-visible shape for a play NPC. It deliberately
// omits the private agenda field.
type npcPublicResponse struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	PublicStatus string `json:"public_status"`
}

// --- Play Factions and Reputation ---

// playFaction is a DM-managed faction within a play-surface campaign.
type playFaction struct {
	FactionID string `json:"faction_id"`
	Name      string `json:"name"`
}

// playFactionCreateRequest is the accepted shape for creating a play faction.
type playFactionCreateRequest struct {
	FactionID string `json:"faction_id"`
	Name      string `json:"name"`
}

// reputationRequest is the accepted shape for changing a character's faction
// reputation.
type reputationRequest struct {
	CharacterID string `json:"character_id"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// reputationEntry is a single immutable reputation change record.
type reputationEntry struct {
	FactionID   string `json:"faction_id"`
	CharacterID string `json:"character_id"`
	Reputation  int    `json:"reputation"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// reputationResponse is the public wire shape for reading a faction's
// reputation history.
type reputationResponse struct {
	FactionID string            `json:"faction_id"`
	Entries   []reputationEntry `json:"entries"`
}

// --- NPC dialogue ---

// dialogueEntry is a single attributed dialogue line for a campaign NPC.
type dialogueEntry struct {
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// dialogueRequest is the accepted shape for appending NPC dialogue.
type dialogueRequest struct {
	DialogueID string `json:"dialogue_id"`
	Speaker    string `json:"speaker"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// dialogueResponse is the public wire shape for reading an NPC's dialogue
// history. The DM receives all entries; players receive only public entries.
type dialogueResponse struct {
	NPCID   string          `json:"npc_id"`
	Entries []dialogueEntry `json:"entries"`
}

// --- Relationship graph ---

// playRelationship is a directed edge between two campaign entities. Both
// source_id and target_id may refer to either a campaign member character id
// or an NPC id.
type playRelationship struct {
	SourceID string `json:"source_id"`
	TargetID string `json:"target_id"`
	Kind     string `json:"kind"`
	Score    int    `json:"score"`
}

// relationshipCreateRequest is the accepted shape for creating a relationship.
type relationshipCreateRequest struct {
	SourceID string `json:"source_id"`
	TargetID string `json:"target_id"`
	Kind     string `json:"kind"`
	Score    *int   `json:"score"`
}

// relationshipUpdateRequest is the accepted shape for updating a relationship.
type relationshipUpdateRequest struct {
	Score *int `json:"score"`
}

// relationshipsResponse is the public wire shape for listing all edges in a
// campaign. Edges are returned in insertion order.
type relationshipsResponse struct {
	Edges []playRelationship `json:"edges"`
}

// --- Clues ---

const (
	clueAudienceCharacter = "character"
	clueAudienceParty     = "party"
	clueAudienceHidden    = "hidden"
)

// clueResponse is the public wire shape for a campaign clue. It omits
// character_id for party and hidden clues.
type clueResponse struct {
	ClueID      string `json:"clue_id"`
	Text        string `json:"text"`
	Audience    string `json:"audience"`
	CharacterID string `json:"character_id,omitempty"`
}

// clueCreateRequest is the accepted shape for creating a clue.
type clueCreateRequest struct {
	ClueID      string  `json:"clue_id"`
	Text        string  `json:"text"`
	Audience    string  `json:"audience"`
	CharacterID *string `json:"character_id,omitempty"`
}

// cluesResponse is the public wire shape for listing clues.
type cluesResponse struct {
	Clues []clueResponse `json:"clues"`
}

// --- Play quest dependencies ---

// playQuest is a deterministic campaign quest with prerequisite dependencies.
type playQuest struct {
	QuestID   string        `json:"quest_id"`
	Title     string        `json:"title"`
	DependsOn []string      `json:"depends_on"`
	State     string        `json:"state"`
	Rewards   *questRewards `json:"rewards,omitempty"`
}

// questRewards is the configured reward payload for a play quest.
type questRewards struct {
	XP    int            `json:"xp"`
	Items map[string]int `json:"items"`
}

// questRewardAwardResponse is the public wire shape returned when a DM awards
// quest rewards.
type questRewardAwardResponse struct {
	QuestID string         `json:"quest_id"`
	Awarded bool           `json:"awarded"`
	XP      int            `json:"xp"`
	Items   map[string]int `json:"items"`
}

// characterRewardsResponse is the public wire shape for cumulative quest
// rewards granted to a character.
type characterRewardsResponse struct {
	CharacterID string         `json:"character_id"`
	XP          int            `json:"xp"`
	Items       map[string]int `json:"items"`
}

// playQuestCreateRequest is the accepted shape for creating a play quest.
type playQuestCreateRequest struct {
	QuestID   string   `json:"quest_id"`
	Title     string   `json:"title"`
	DependsOn []string `json:"depends_on"`
}

// playQuestStateRequest is the accepted shape for updating a quest state.
type playQuestStateRequest struct {
	State string `json:"state"`
}

// playQuestsResponse is the public wire shape for listing play quests.
type playQuestsResponse struct {
	Quests []playQuest `json:"quests"`
}

// --- World events ---

const (
	worldEventStatusScheduled = "scheduled"
	worldEventStatusResolved  = "resolved"
)

// worldEventResolution is the immutable resolution recorded for a world event.
type worldEventResolution struct {
	TurnNumber int    `json:"turn_number"`
	Text       string `json:"text"`
}

// worldEvent is a deterministic campaign-level event scheduled by the DM and
// resolved exactly once when the campaign reaches the scheduled turn.
type worldEvent struct {
	EventID    string                `json:"event_id"`
	TurnNumber int                   `json:"turn_number"`
	Title      string                `json:"title"`
	Text       string                `json:"text"`
	Status     string                `json:"status"`
	Resolution *worldEventResolution `json:"resolution,omitempty"`
}

// worldEventCreateRequest is the accepted shape for scheduling a world event.
type worldEventCreateRequest struct {
	EventID    string `json:"event_id"`
	TurnNumber int    `json:"turn_number"`
	Title      string `json:"title"`
	Text       string `json:"text"`
}

// worldEventResolveRequest is the accepted shape for resolving a world event.
type worldEventResolveRequest struct {
	Text string `json:"text"`
}

// worldEventsResponse is the public wire shape for listing world events.
type worldEventsResponse struct {
	Events []worldEvent `json:"events"`
}

// --- Campaign calendar ---

// calendarResponse is the public wire shape for a campaign calendar.
// Weather is derived deterministically from the current day and season.
type calendarResponse struct {
	Day     int    `json:"day"`
	Season  string `json:"season"`
	Weather string `json:"weather"`
}

// calendarCreateRequest is the accepted shape for initializing a calendar.
type calendarCreateRequest struct {
	Day    int    `json:"day"`
	Season string `json:"season"`
}

// calendarAdvanceRequest is the accepted shape for advancing the calendar.
type calendarAdvanceRequest struct {
	Days int `json:"days"`
}

// --- Settlements ---

const (
	settlementAvailabilityOpen    = "open"
	settlementAvailabilityLimited = "limited"
	settlementAvailabilityClosed  = "closed"
)

// settlement is a DM-managed campaign settlement with services and
// availability. Player views filter discovered_by to the caller's own
// character id.
type settlement struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
	DiscoveredBy []string `json:"discovered_by"`
}

// settlementCreateRequest is the accepted shape for creating or replacing a
// settlement. settlement_id is required for create and taken from the URL for
// replace.
type settlementCreateRequest struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
}

// settlementsResponse is the public wire shape for listing settlements.
type settlementsResponse struct {
	Settlements []settlement `json:"settlements"`
}

// --- Shops ---

// shop is a DM-managed settlement shop with deterministic stock and prices.
type shop struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  int            `json:"buy_price"`
	SellPrice int            `json:"sell_price"`
}

// shopCreateRequest is the accepted shape for creating a shop.
type shopCreateRequest struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  int            `json:"buy_price"`
	SellPrice int            `json:"sell_price"`
}

// shopTransactionRequest is the accepted shape for buying or selling items.
type shopTransactionRequest struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
}

// shopTransactionResponse is the public wire shape returned by a successful
// buy or sell operation.
type shopTransactionResponse struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
	Gold        int    `json:"gold"`
	Stock       int    `json:"stock"`
}

// --- Recipe catalog ---

// recipe is a deterministic campaign crafting recipe backed by the public
// campaign inventory item catalog.
type recipe struct {
	RecipeID       string         `json:"recipe_id"`
	Name           string         `json:"name"`
	Ingredients    map[string]int `json:"ingredients"`
	OutputItem     string         `json:"output_item"`
	OutputQuantity int            `json:"output_quantity"`
}

// craftRequest is the accepted shape for crafting a recipe.
type craftRequest struct {
	CharacterID string `json:"character_id"`
}

// craftResponse is the public wire shape returned by a successful craft.
type craftResponse struct {
	CharacterID    string `json:"character_id"`
	RecipeID       string `json:"recipe_id"`
	OutputItem     string `json:"output_item"`
	OutputQuantity int    `json:"output_quantity"`
}

// recipesResponse is the public wire shape for listing campaign recipes.
type recipesResponse struct {
	Recipes []recipe `json:"recipes"`
}

// --- Recurring downtime ---

// downtimeActivity is a recurring downtime activity defined by the campaign DM.
type downtimeActivity struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired int    `json:"cycles_required"`
}

// downtimeActivityRequest is the accepted shape for creating a downtime activity.
type downtimeActivityRequest struct {
	ActivityID     string `json:"activity_id"`
	Name           string `json:"name"`
	CyclesRequired int    `json:"cycles_required"`
}

// downtimeAllocation is a character's recurring progress on a downtime activity.
type downtimeAllocation struct {
	CharacterID     string `json:"character_id"`
	ActivityID      string `json:"activity_id"`
	CyclesCompleted int    `json:"cycles_completed"`
	Completions     int    `json:"completions"`
}

// downtimeAllocationRequest is the accepted shape for allocating an activity.
type downtimeAllocationRequest struct {
	ActivityID string `json:"activity_id"`
}

// --- Privacy controls ---

// playNote is a role-filtered campaign note owned by a player.
type playNote struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
	Owner      string `json:"owner"`
}

// playNoteCreateRequest is the accepted shape for creating a note.
type playNoteCreateRequest struct {
	NoteID     string `json:"note_id"`
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// playNoteUpdateRequest is the accepted shape for updating a note.
type playNoteUpdateRequest struct {
	Text       string `json:"text"`
	Visibility string `json:"visibility"`
}

// playNotesResponse is the public wire shape for listing notes.
type playNotesResponse struct {
	Notes []playNote `json:"notes"`
}

// playWhisper is a character-to-character private message.
type playWhisper struct {
	WhisperID       string `json:"whisper_id"`
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Text            string `json:"text"`
}

// playWhisperCreateRequest is the accepted shape for creating a whisper.
type playWhisperCreateRequest struct {
	WhisperID     string `json:"whisper_id"`
	ToCharacterID string `json:"to_character_id"`
	Text          string `json:"text"`
}

// playWhispersResponse is the public wire shape for listing whispers.
type playWhispersResponse struct {
	Whispers []playWhisper `json:"whispers"`
}

// playInvitation is a campaign invitation from the DM to a registered player.
type playInvitation struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
	Status       string `json:"status"`
}

// playInvitationCreateRequest is the accepted shape for creating an invitation.
type playInvitationCreateRequest struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
}

// playInvitationsResponse is the public wire shape for listing invitations.
type playInvitationsResponse struct {
	Invitations []playInvitation `json:"invitations"`
}

// delegation is a campaign member's delegated co-GM power record.
type delegation struct {
	Username string   `json:"username"`
	Powers   []string `json:"powers"`
	Active   bool     `json:"active"`
}

// delegationCreateRequest is the accepted shape for granting a delegation.
type delegationCreateRequest struct {
	Username string   `json:"username"`
	Powers   []string `json:"powers"`
}

// delegationAuditEntry is a single immutable grant/revoke event.
type delegationAuditEntry struct {
	Username string   `json:"username"`
	Action   string   `json:"action"`
	Powers   []string `json:"powers"`
}

// delegationsAuditResponse is the public wire shape for the audit endpoint.
type delegationsAuditResponse struct {
	Entries []delegationAuditEntry `json:"entries"`
}

// --- Actor audit trail ---

// auditEvent is an immutable campaign-scoped record of a mutating play event.
type auditEvent struct {
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	Role          string `json:"role"`
	Timestamp     int    `json:"timestamp"`
	CorrelationID string `json:"correlation_id"`
}

// auditEventCreateRequest is the accepted shape for creating an audit event.
type auditEventCreateRequest struct {
	Kind          string `json:"kind"`
	CorrelationID string `json:"correlation_id"`
}

// auditEventsResponse is the public wire shape for listing audit events.
type auditEventsResponse struct {
	Entries []auditEvent `json:"entries"`
}

// characterSheetResponse is the public wire shape for a basic character sheet.
// It exposes only the fields needed for the privacy-controls stage.
type characterSheetResponse struct {
	CharacterID      string `json:"character_id"`
	Owner            string `json:"owner"`
	Name             string `json:"name"`
	Class            string `json:"class"`
	Level            int    `json:"level"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
	HPMax            int    `json:"hp_max"`
	ArmorClass       int    `json:"armor_class"`
}

// --- Event projections ---

const (
	projectionKindSetStory        = "set-story"
	projectionKindIncrementDanger = "increment-danger"
)

// projectionEvent is a campaign-scoped immutable projection event.
type projectionEvent struct {
	Sequence int    `json:"sequence"`
	EventID  string `json:"event_id"`
	Kind     string `json:"kind"`
	Value    string `json:"value,omitempty"`
}

// projectionEventCreateRequest is the accepted shape for appending a projection event.
type projectionEventCreateRequest struct {
	EventID string  `json:"event_id"`
	Kind    string  `json:"kind"`
	Value   *string `json:"value,omitempty"`
}

// projectionResponse is the public wire shape for a deterministic projection
// rebuilt from ordered projection events.
type projectionResponse struct {
	Story           string   `json:"story"`
	Danger          int      `json:"danger"`
	AppliedEventIDs []string `json:"applied_event_ids"`
}

// --- Idempotent events ---

// idempotentEvent is a campaign-scoped immutable event created with an
// idempotency key. Repeating the same key returns the identical stored event.
type idempotentEvent struct {
	EventID        string `json:"event_id"`
	Value          string `json:"value"`
	Sequence       int    `json:"sequence"`
	IdempotencyKey string `json:"idempotency_key"`
}

// idempotentEventCreateRequest is the accepted shape for creating an idempotent
// event.
type idempotentEventCreateRequest struct {
	EventID string `json:"event_id"`
	Value   string `json:"value"`
}

// idempotentEventsResponse is the public wire shape for listing idempotent
// events.
type idempotentEventsResponse struct {
	Events []idempotentEvent `json:"events"`
}

// --- Safe turns ---

// safeTurnSubmitRequest is the accepted shape for submitting a safe turn.
type safeTurnSubmitRequest struct {
	SubmissionID string `json:"submission_id"`
	ExpectedTurn int    `json:"expected_turn"`
	Action       string `json:"action"`
}

// safeTurnSubmitResponse is the public wire shape returned when a safe turn
// is accepted and the campaign advances exactly once.
type safeTurnSubmitResponse struct {
	SubmissionID string `json:"submission_id"`
	Action       string `json:"action"`
	AcceptedTurn int    `json:"accepted_turn"`
	NextTurn     int    `json:"next_turn"`
}

// safeTurnStaleResponse is the public wire shape returned when a safe turn
// is rejected because its expected turn does not match the current turn.
type safeTurnStaleResponse struct {
	CurrentTurn int `json:"current_turn"`
}

// safeTurnAcceptedEntry is a single accepted safe turn in the read history.
type safeTurnAcceptedEntry struct {
	SubmissionID string `json:"submission_id"`
	Action       string `json:"action"`
	AcceptedTurn int    `json:"accepted_turn"`
	NextTurn     int    `json:"next_turn"`
}

// safeTurnsResponse is the public wire shape for reading a campaign's safe
// turn state. Accepted turns are ordered by acceptance turn.
type safeTurnsResponse struct {
	CurrentTurn int                     `json:"current_turn"`
	Accepted    []safeTurnAcceptedEntry `json:"accepted"`
}
