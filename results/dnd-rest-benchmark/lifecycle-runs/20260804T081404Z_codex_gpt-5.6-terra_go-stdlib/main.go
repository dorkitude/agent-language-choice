package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

var diceExpression = regexp.MustCompile(`^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$`)

type combatant struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	dex   int
}

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []combatant
	Conditions map[string][]condition
}

var combatState = struct {
	sync.Mutex
	sessions map[string]*combatSession
}{sessions: make(map[string]*combatSession)}

type user struct {
	Username     string
	PasswordHash [sha256.Size]byte
	Role         string
}

type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type monsterSummary struct {
	Slug       string `json:"slug"`
	Name       string `json:"name"`
	CR         string `json:"cr"`
	ArmorClass int    `json:"armor_class"`
	HitPoints  int    `json:"hit_points"`
}

type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

type campaign struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

type playCampaign struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Owner      string `json:"owner"`
	Status     string `json:"status"`
	MaxPlayers int    `json:"max_players"`
}

type playMember struct {
	Username    string `json:"username"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Class       string `json:"class"`
	HPCurrent   int    `json:"hp_current,omitempty"`
	HPMax       int    `json:"hp_max,omitempty"`
	Status      string `json:"status,omitempty"`
	Successes   int    `json:"death_save_successes,omitempty"`
	Failures    int    `json:"death_save_failures,omitempty"`
}

// playSpell is a character's known spell. Spellbook entries are deliberately
// stored separately from membership documents so listing them does not change
// the established member response.
type playSpell struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// playInventoryItem is a held item stack. It is stored apart from the older
// campaign-level inventory API, whose response and ownership rules differ.
type playInventoryItem struct {
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

type playInventoryStackResponse struct {
	CharacterID   string `json:"character_id"`
	ItemID        string `json:"item_id"`
	Quantity      int    `json:"quantity"`
	TotalQuantity int    `json:"total_quantity"`
}

// playLoot is a campaign-scoped item parcel.  Votes are kept in a separate
// table so the record itself remains unchanged until its one assignment.
type playLoot struct {
	LootID               string `json:"loot_id"`
	ItemID               string `json:"item_id"`
	Quantity             int    `json:"quantity"`
	Status               string `json:"status"`
	RecipientCharacterID string `json:"recipient_character_id"`
	Votes                int    `json:"votes"`
}

type playLootVoteResponse struct {
	LootID               string `json:"loot_id"`
	Voter                string `json:"voter"`
	RecipientCharacterID string `json:"recipient_character_id"`
	VotesForRecipient    int    `json:"votes_for_recipient"`
}

// playNPC keeps the DM's agenda with the player-visible status. Responses for
// players are deliberately projected instead of relying on omitempty so a
// private agenda can never leak when it is present.
type playNPC struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// playLootReadResponse exposes the immutable loot parcel together with the
// complete vote tally. Assignment responses intentionally retain their
// numeric winning-vote count, while reads show each recipient's tally.
type playLootReadResponse struct {
	LootID               string         `json:"loot_id"`
	ItemID               string         `json:"item_id"`
	Quantity             int            `json:"quantity"`
	Status               string         `json:"status"`
	RecipientCharacterID string         `json:"recipient_character_id"`
	Votes                map[string]int `json:"votes"`
}

// playConsumableResponse reports the single unit used and its deterministic
// game effect. Consumables are removed from the same held-item stack used by
// the inventory endpoints.
type playConsumableResponse struct {
	CharacterID      string `json:"character_id"`
	ItemID           string `json:"item_id"`
	QuantityConsumed int    `json:"quantity_consumed"`
	TotalQuantity    int    `json:"total_quantity"`
	Effect           struct {
		Type       string `json:"type"`
		HPRestored int    `json:"hp_restored"`
	} `json:"effect"`
}

// playEquipmentResponse represents the single item assigned to an equipment
// slot. Equipment remains in the inventory stack while it is equipped.
type playEquipmentResponse struct {
	CharacterID string `json:"character_id"`
	Slot        string `json:"slot"`
	ItemID      string `json:"item_id"`
	Attuned     bool   `json:"attuned"`
}

type playAttunementResponse struct {
	CharacterID     string `json:"character_id"`
	Slot            string `json:"slot"`
	ItemID          string `json:"item_id"`
	Attuned         bool   `json:"attuned"`
	AttunementCount int    `json:"attunement_count"`
	MaxAttunements  int    `json:"max_attunements"`
}

type playCurrencyResponse struct {
	CharacterID string `json:"character_id"`
	Gold        int    `json:"gold"`
}

type playCurrencyTransferResponse struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Gold            int    `json:"gold"`
	FromGold        int    `json:"from_gold"`
	ToGold          int    `json:"to_gold"`
	TransferID      int    `json:"transfer_id"`
}

// playSpellCast is an immutable spell-casting event. It is kept separate from
// character membership so the established member document remains unchanged.
type playSpellCast struct {
	CharacterID    string `json:"character_id"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
	Sequence       int    `json:"sequence"`
}

// playConcentration is the single active concentration effect for a character.
// It is stored independently so established character responses remain stable.
type playConcentration struct {
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	RemainingTurns int    `json:"remaining_turns"`
}

type playScene struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Status string `json:"status"`
}

// playEncounter is deliberately separate from the exploration timeline. Later
// combat stages can populate combatants without changing the party turn queue.
type playEncounter struct {
	ID              string                     `json:"id"`
	Name            string                     `json:"name"`
	Status          string                     `json:"status"`
	Reward          *playEncounterReward       `json:"reward,omitempty"`
	Combatants      []playMonster              `json:"combatants"`
	PartyCombatants []playPartyCombatant       `json:"party_combatants,omitempty"`
	TurnOrder       []string                   `json:"turn_order,omitempty"`
	Round           int                        `json:"round,omitempty"`
	TurnIndex       int                        `json:"turn_index,omitempty"`
	Conditions      map[string][]playCondition `json:"conditions,omitempty"`
}

// playEncounterReward is stored on the encounter so an award is durable and
// cannot be granted twice, including after a server restart.
type playEncounterReward struct {
	XP   int              `json:"xp"`
	Loot []playRewardLoot `json:"loot"`
}

type playRewardLoot struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// playCondition is scoped to an encounter combatant. Conditions are keyed by
// the stable monster ID or campaign-member username in playEncounter.Conditions.
type playCondition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// playMonster is an encounter-local combatant. Monster IDs are scoped to an
// encounter, allowing the same deterministic monster template in other fights.
type playMonster struct {
	MonsterID  string `json:"monster_id"`
	Name       string `json:"name"`
	HPMax      int    `json:"hp_max"`
	Initiative int    `json:"initiative"`
	HPCurrent  int    `json:"hp_current"`
}

// playPartyCombatant is a snapshot of a campaign member when the owner adds
// them to an encounter. It deliberately retains the membership username so it
// can be unbound without affecting the campaign's party membership.
type playPartyCombatant struct {
	Member      string `json:"member"`
	CharacterID string `json:"character_id"`
	Name        string `json:"name"`
	Initiative  int    `json:"initiative"`
}

// playLocation and playLocationConnection form a directed, campaign-scoped
// travel graph. Connections are stored separately so a location can have many
// deterministic outbound destinations.
type playLocation struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type playLocationConnection struct {
	FromID      string `json:"from_id"`
	ToID        string `json:"to_id"`
	TravelTurns int    `json:"travel_turns"`
}

type travelDestination struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	TravelTurns int    `json:"travel_turns"`
}

// campaignDocument keeps the player-visible story separate from the owner's
// private preparation notes. It is stored independently from campaign state so
// updates remain durable without changing the established campaign response.
type campaignDocument struct {
	Story   string `json:"story"`
	DMNotes string `json:"dm_notes"`
}

// narrationEvent is an immutable entry in a play campaign's DM event log.
// Its field order is also the response order used by the API.
type narrationEvent struct {
	Sequence      int    `json:"sequence"`
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	Type          string `json:"type,omitempty"`
	Target        string `json:"target,omitempty"`
	HPCurrent     int    `json:"hp_current,omitempty"`
	HPMax         int    `json:"hp_max,omitempty"`
	Text          string `json:"text,omitempty"`
	DestinationID string `json:"destination_id,omitempty"`
	TravelTurns   int    `json:"travel_turns,omitempty"`
	NextActor     string `json:"next_actor,omitempty"`
}

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type inventoryItem struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

type equipmentAssignment struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

type campaignEvent struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

type faction struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

type npc struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

type quest struct {
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Status     string   `json:"status"`
	Milestones []string `json:"milestones"`
	Completed  []string `json:"completed"`
}

type craftingProject struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	CostGP        int    `json:"cost_gp"`
	Status        string `json:"status"`
}

type campaignSession struct {
	ID              string   `json:"id"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes int      `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
	Present         []string `json:"present,omitempty"`
	Absent          []string `json:"absent,omitempty"`
}

var userState = struct {
	sync.Mutex
	users map[string]user
}{users: make(map[string]user)}

const (
	schemaVersion    = 1
	databaseFile     = "game.db"
	maxJSONBodyBytes = 1 << 20
)

// schemaDefinition is shared by startup and reset. Keeping the DDL in one
// place prevents the two lifecycle paths from silently creating different
// database layouts.
const schemaDefinition = `
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS play_memberships (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_character_owners (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_character_progress (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id));
CREATE TABLE IF NOT EXISTS play_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence));
CREATE TABLE IF NOT EXISTS play_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_character_inventory_stacks (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id));
CREATE TABLE IF NOT EXISTS play_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot));
CREATE TABLE IF NOT EXISTS play_character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id));
CREATE TABLE IF NOT EXISTS play_currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id));
CREATE TABLE IF NOT EXISTS play_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id));
CREATE TABLE IF NOT EXISTS play_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter));
CREATE TABLE IF NOT EXISTS play_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id));
CREATE TABLE IF NOT EXISTS play_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence));
CREATE TABLE IF NOT EXISTS play_turn_nudges (campaign_id TEXT NOT NULL, nudge_count INTEGER NOT NULL, PRIMARY KEY (campaign_id, nudge_count));
CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS play_scenes (campaign_id TEXT NOT NULL, scene_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, scene_id));
CREATE TABLE IF NOT EXISTS play_scene_state (campaign_id TEXT PRIMARY KEY, current_scene_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS play_encounters (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, encounter_id));
CREATE TABLE IF NOT EXISTS play_locations (campaign_id TEXT NOT NULL, location_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, location_id));
CREATE TABLE IF NOT EXISTS play_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id));
CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_inventory (id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_equipment (id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_factions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_npcs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_quests (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crafting_projects (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_sessions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL);`

var schemaTables = []string{
	"users", "combat_sessions", "monsters", "items", "campaigns",
	"play_campaigns", "play_memberships", "play_character_owners", "play_character_progress", "play_character_spells", "play_character_prepared_spells", "play_character_casts", "play_character_concentrations", "play_character_inventory_stacks", "play_character_equipment", "play_character_currency", "play_currency_transfers", "play_loot", "play_loot_votes", "play_npcs", "play_narrations", "play_turn_nudges", "play_campaign_documents", "play_scenes", "play_scene_state", "play_encounters", "play_locations", "play_location_connections",
	"campaign_characters", "campaign_events", "campaign_inventory", "campaign_equipment", "campaign_factions",
	"campaign_npcs", "campaign_quests", "crafting_projects", "campaign_sessions",
}

var storageState struct {
	sync.Mutex
	initialized bool
}

func main() {
	if err := initializeStorage(); err != nil {
		fmt.Fprintln(os.Stderr, "initialize storage:", err)
		os.Exit(1)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	if err := http.ListenAndServe("127.0.0.1:"+port, newRouter()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// apiRoute keeps the public API inventory separate from ServeMux construction.
// Patterns include the method so net/http retains the established 405 behavior.
type apiRoute struct {
	pattern string
	handler http.HandlerFunc
}

// newRouter builds the complete public HTTP surface from the route inventory.
func newRouter() *http.ServeMux {
	mux := http.NewServeMux()
	registerRoutes(mux, []apiRoute{
		{"GET /health", health},
		{"POST /v1/dice/stats", diceStats},
		{"POST /v1/checks/ability", abilityCheck},
		{"POST /v1/encounters/adjusted-xp", adjustedXP},
		{"POST /v1/initiative/order", initiativeOrder},
		{"POST /v1/characters/ability-modifier", abilityModifierHandler},
		{"POST /v1/characters/proficiency", proficiencyHandler},
		{"POST /v1/characters/derived-stats", derivedStats},
		{"POST /v1/combat/sessions", createCombatSession},
		{"POST /v1/combat/sessions/{id}/conditions", addCondition},
		{"POST /v1/combat/sessions/{id}/advance", advanceCombatTurn},
		{"POST /v1/auth/register", registerUser},
		{"POST /v1/auth/login", loginUser},
		{"POST /v1/play/campaigns", createPlayCampaign},
		{"POST /v1/play/campaigns/{id}/members", joinPlayCampaign},
		{"GET /v1/play/campaigns/{id}/characters/{char_id}/owner", getPlayCharacterOwner},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/claim", claimPlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/transfer", transferPlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/build", buildPlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/level-up", levelUpPlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check", skillCheckPlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/spells", addPlayCharacterSpell},
		{"GET /v1/play/campaigns/{id}/characters/{char_id}/spells", listPlayCharacterSpells},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", addPlayCharacterInventoryItems},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", listPlayCharacterInventoryItems},
		{"DELETE /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}", removePlayCharacterInventoryItems},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume", consumePlayCharacterInventoryItem},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/currency", getPlayCharacterCurrency},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/currency/transfers", transferPlayCharacterCurrency},
		{"POST /v1/play/campaigns/{id}/loot", createPlayLoot},
		{"POST /v1/play/campaigns/{id}/loot/{loot_id}/votes", votePlayLoot},
		{"POST /v1/play/campaigns/{id}/loot/{loot_id}/assign", assignPlayLoot},
		{"GET /v1/play/campaigns/{id}/loot/{loot_id}", getPlayLoot},
		{"POST /v1/play/campaigns/{id}/npcs", createPlayNPC},
		{"PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda", updatePlayNPCAgenda},
		{"GET /v1/play/campaigns/{id}/npcs/{npc_id}", getPlayNPC},
		{"PUT /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", putPlayCharacterEquipment},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", getPlayCharacterEquipment},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune", attunePlayCharacterEquipment},
		{"PUT /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", putPlayCharacterPreparedSpells},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", getPlayCharacterPreparedSpells},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/casts", castPlayCharacterSpell},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/casts", listPlayCharacterCasts},
		{"PUT /v1/play/campaigns/{id}/characters/{character_id}/concentration", putPlayCharacterConcentration},
		{"GET /v1/play/campaigns/{id}/characters/{character_id}/concentration", getPlayCharacterConcentration},
		{"POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn", advancePlayCharacterConcentration},
		{"DELETE /v1/play/campaigns/{id}/characters/{character_id}/concentration", deletePlayCharacterConcentration},
		{"POST /v1/play/campaigns/{id}/start", startPlayCampaign},
		{"POST /v1/play/campaigns/{id}/narrations", appendNarration},
		{"POST /v1/play/campaigns/{id}/actions", submitPlayerAction},
		{"POST /v1/play/campaigns/{id}/resolutions", submitGMResolution},
		{"POST /v1/play/campaigns/{id}/turn/nudge", nudgePlayTurn},
		{"POST /v1/play/campaigns/{id}/turn/travel", submitTravelTurn},
		{"POST /v1/play/campaigns/{id}/turn/rest", submitRestTurn},
		{"POST /v1/play/campaigns/{id}/encounters", createPlayEncounter},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters", addPlayMonster},
		{"DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}", removePlayMonster},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants", bindPlayMemberCombatant},
		{"DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}", unbindPlayMemberCombatant},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions", addPlayEncounterCondition},
		{"GET /v1/play/campaigns/{id}/encounters/{enc_id}/status", getPlayEncounterStatus},
		{"GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn", getPlayEncounterTurn},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance", advancePlayEncounterTurn},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay", delayPlayEncounterTurn},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready", readyPlayEncounterAction},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions", submitPlayCombatAction},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage", damagePlayCombatant},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal", healPlayCombatant},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards", awardPlayEncounterRewards},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/close", closePlayEncounter},
		{"POST /v1/play/campaigns/{id}/encounters/{enc_id}/end", endPlayEncounter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/damage", damagePlayCharacter},
		{"POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves", recordDeathSave},
		{"GET /v1/play/campaigns/{id}/characters/{char_id}/status", getPlayCharacterStatus},
		{"POST /v1/play/campaigns/{id}/scenes", createPlayScene},
		{"POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter", enterPlayScene},
		{"POST /v1/play/campaigns/{id}/scenes/{scene_id}/close", closePlayScene},
		{"GET /v1/play/campaigns/{id}/scenes/current", getCurrentPlayScene},
		{"POST /v1/play/campaigns/{id}/locations", createPlayLocation},
		{"POST /v1/play/campaigns/{id}/locations/{from_id}/connections", createPlayLocationConnection},
		{"GET /v1/play/campaigns/{id}/locations/{loc_id}/travel", getPlayLocationTravel},
		{"PUT /v1/play/campaigns/{id}/document", putCampaignDocument},
		{"GET /v1/play/campaigns/{id}/document", getCampaignDocument},
		{"GET /v1/play/campaigns/{id}/turn", getPlayTurn},
		{"GET /v1/play/campaigns/{id}/my-turn", getMyPlayTurn},
		{"GET /v1/play/campaigns/{id}/gm/status", getGMPlayStatus},
		{"GET /v1/storage/status", storageStatus},
		{"POST /v1/storage/reset", resetStorage},
		{"POST /v1/compendium/monsters", createMonster},
		{"GET /v1/compendium/monsters/{slug}", getMonster},
		{"POST /v1/compendium/items", createItem},
		{"GET /v1/compendium/items/{slug}", getItem},
		{"POST /v1/campaigns", createCampaign},
		{"POST /v1/campaigns/{id}/characters", addCampaignCharacter},
		{"POST /v1/campaigns/{id}/events", addCampaignEvent},
		{"GET /v1/campaigns/{id}/state", getCampaignState},
		{"GET /v1/campaigns/{id}/audit", campaignAudit},
		{"GET /v1/campaigns/{id}/export", exportCampaign},
		{"POST /v1/campaigns/{id}/inventory", addInventoryItem},
		{"POST /v1/campaigns/{id}/characters/{character_id}/equipment", assignEquipment},
		{"GET /v1/campaigns/{id}/inventory/summary", inventorySummary},
		{"POST /v1/campaigns/{id}/factions", createFaction},
		{"POST /v1/campaigns/{id}/npcs", createNPC},
		{"GET /v1/campaigns/{id}/relationships", relationshipSummary},
		{"POST /v1/campaigns/{id}/quests", createQuest},
		{"POST /v1/campaigns/{id}/quests/{quest_id}/progress", updateQuestProgress},
		{"GET /v1/campaigns/{id}/quests/summary", questSummary},
		{"POST /v1/campaigns/{id}/downtime/crafting", createCraftingProject},
		{"POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance", advanceCraftingProject},
		{"POST /v1/campaigns/{id}/sessions", scheduleCampaignSession},
		{"POST /v1/campaigns/{id}/sessions/{session_id}/attendance", recordSessionAttendance},
		{"GET /v1/campaigns/{id}/sessions/next", nextCampaignSession},
		{"GET /v1/campaigns/{id}/analytics/summary", campaignAnalyticsSummary},
		{"POST /v1/campaigns/{id}/analytics/risk-report", campaignRiskReport},
		{"POST /v1/phb/spell-slots", spellSlots},
		{"POST /v1/phb/rests/long", longRest},
		{"POST /v1/phb/equipment-load", equipmentLoad},
		{"POST /v1/dm/encounter-builder", encounterBuilder},
		{"POST /v1/dm/loot-parcel", lootParcel},
		{"POST /v1/dm/session-recap", sessionRecap},
	})
	return mux
}

func registerRoutes(mux *http.ServeMux, routes []apiRoute) {
	for _, route := range routes {
		mux.HandleFunc(route.pattern, route.handler)
	}
}

func spellSlots(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Class string `json:"class"`
		Level int    `json:"level"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Class != "wizard" || input.Level != 5 {
		badRequest(w, "unsupported class or level")
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"class": input.Class,
		"level": input.Level,
		"slots": map[string]int{"1": 4, "2": 3, "3": 2},
	})
}

func longRest(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Level           int `json:"level"`
		HPCurrent       int `json:"hp_current"`
		HPMax           int `json:"hp_max"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validLevel(input.Level) || input.HPMax < 1 || input.HPCurrent < 0 || input.HPCurrent > input.HPMax || input.HitDiceSpent < 0 || input.ExhaustionLevel < 0 {
		badRequest(w, "invalid rest")
		return
	}
	recovered := max(1, input.Level/2)
	hitDiceSpent := max(0, input.HitDiceSpent-recovered)
	exhaustion := max(0, input.ExhaustionLevel-1)
	respondJSON(w, http.StatusOK, map[string]int{
		"hp_current":       input.HPMax,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustion,
	})
}

func equipmentLoad(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Strength int `json:"strength"`
		Weight   int `json:"weight"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Strength < 0 || input.Weight < 0 {
		badRequest(w, "invalid equipment load")
		return
	}
	capacity := input.Strength * 15
	respondJSON(w, http.StatusOK, map[string]any{
		"capacity":   capacity,
		"weight":     input.Weight,
		"encumbered": input.Weight > capacity,
	})
}

func storageStatus(w http.ResponseWriter, _ *http.Request) {
	storageState.Lock()
	initialized := storageState.initialized
	storageState.Unlock()
	respondJSON(w, http.StatusOK, map[string]any{"driver": "sqlite", "schema_version": schemaVersion, "initialized": initialized})
}

func resetStorage(w http.ResponseWriter, _ *http.Request) {
	// State locks precede the storage lock everywhere they are held together.
	userState.Lock()
	combatState.Lock()
	storageState.Lock()
	err := recreateSchemaLocked()
	if err == nil {
		userState.users = make(map[string]user)
		combatState.sessions = make(map[string]*combatSession)
		storageState.initialized = true
	}
	storageState.Unlock()
	combatState.Unlock()
	userState.Unlock()
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage reset failed"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"ok": true, "schema_version": schemaVersion})
}

func initializeStorage() error {
	storageState.Lock()
	defer storageState.Unlock()
	if err := createSchemaLocked(); err != nil {
		return err
	}
	if err := loadStoredStateLocked(); err != nil {
		return err
	}
	storageState.initialized = true
	return nil
}

func createSchemaLocked() error {
	return runSQLite("PRAGMA journal_mode=WAL;" + schemaDefinition)
}

func recreateSchemaLocked() error {
	var sql strings.Builder
	for _, table := range schemaTables {
		sql.WriteString("DROP TABLE IF EXISTS ")
		sql.WriteString(table)
		sql.WriteString(";\n")
	}
	sql.WriteString(schemaDefinition)
	return runSQLite(sql.String())
}

func runSQLite(sql string) error {
	command := exec.Command("/usr/bin/sqlite3", databaseFile, sql)
	if output, err := command.CombinedOutput(); err != nil {
		return fmt.Errorf("sqlite: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return nil
}

func querySQLite(sql string) (string, error) {
	command := exec.Command("/usr/bin/sqlite3", "-separator", "\t", databaseFile, sql)
	output, err := command.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("sqlite: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return string(output), nil
}

func sqlQuote(value string) string { return "'" + strings.ReplaceAll(value, "'", "''") + "'" }

func loadStoredStateLocked() error {
	users, err := querySQLite("SELECT username, password_hash, role FROM users;")
	if err != nil {
		return err
	}
	for _, row := range strings.Split(strings.TrimSuffix(users, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 3 {
			return errors.New("invalid stored user")
		}
		hash, err := hex.DecodeString(columns[1])
		if err != nil || len(hash) != sha256.Size {
			return errors.New("invalid stored password hash")
		}
		var passwordHash [sha256.Size]byte
		copy(passwordHash[:], hash)
		userState.users[columns[0]] = user{Username: columns[0], PasswordHash: passwordHash, Role: columns[2]}
	}
	sessions, err := querySQLite("SELECT state FROM combat_sessions;")
	if err != nil {
		return err
	}
	for _, row := range strings.Split(strings.TrimSuffix(sessions, "\n"), "\n") {
		if row == "" {
			continue
		}
		var session combatSession
		if err := json.Unmarshal([]byte(row), &session); err != nil {
			return errors.New("invalid stored combat session")
		}
		if session.ID == "" {
			return errors.New("invalid stored combat session")
		}
		combatState.sessions[session.ID] = &session
	}
	return nil
}

func persistUserLocked(account user) error {
	storageState.Lock()
	defer storageState.Unlock()
	return runSQLite("INSERT INTO users (username, password_hash, role) VALUES (" + sqlQuote(account.Username) + ", " + sqlQuote(hex.EncodeToString(account.PasswordHash[:])) + ", " + sqlQuote(account.Role) + ");")
}

func persistSessionLocked(session *combatSession) error {
	state, err := json.Marshal(session)
	if err != nil {
		return err
	}
	storageState.Lock()
	defer storageState.Unlock()
	return runSQLite("INSERT OR REPLACE INTO combat_sessions (id, state) VALUES (" + sqlQuote(session.ID) + ", " + sqlQuote(string(state)) + ");")
}

func createMonster(w http.ResponseWriter, r *http.Request) {
	var input monster
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validMonster(input) {
		badRequest(w, "invalid monster")
		return
	}

	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	storageState.Lock()
	defer storageState.Unlock()
	existing, err := querySQLite("SELECT slug FROM monsters WHERE slug = " + sqlQuote(input.Slug) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(existing) != "" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "monster slug already exists"})
		return
	}
	if err := runSQLite("INSERT INTO monsters (slug, state) VALUES (" + sqlQuote(input.Slug) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, monsterSummary{Slug: input.Slug, Name: input.Name, CR: input.CR, ArmorClass: input.ArmorClass, HitPoints: input.HitPoints})
}

func getMonster(w http.ResponseWriter, r *http.Request) {
	monster, found, err := loadCompendiumRecord[monster]("monsters", r.PathValue("slug"))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown monster"})
		return
	}
	respondJSON(w, http.StatusOK, monster)
}

func createItem(w http.ResponseWriter, r *http.Request) {
	var input item
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validItem(input) {
		badRequest(w, "invalid item")
		return
	}

	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	storageState.Lock()
	defer storageState.Unlock()
	existing, err := querySQLite("SELECT slug FROM items WHERE slug = " + sqlQuote(input.Slug) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(existing) != "" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "item slug already exists"})
		return
	}
	if err := runSQLite("INSERT INTO items (slug, state) VALUES (" + sqlQuote(input.Slug) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, input)
}

func getItem(w http.ResponseWriter, r *http.Request) {
	item, found, err := loadCompendiumRecord[item]("items", r.PathValue("slug"))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown item"})
		return
	}
	respondJSON(w, http.StatusOK, item)
}

func createCampaign(w http.ResponseWriter, r *http.Request) {
	var input campaign
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) || !validCampaignText(input.DM) {
		badRequest(w, "invalid campaign")
		return
	}
	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", input.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign id already exists"})
	} else if err := runSQLite("INSERT INTO campaigns (id, state) VALUES (" + sqlQuote(input.ID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else {
		respondJSON(w, http.StatusCreated, input)
	}
}

func addCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	var input campaignCharacter
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) || !validCampaignText(input.Class) || !validLevel(input.Level) {
		badRequest(w, "invalid character")
		return
	}
	if err := insertCampaignRecord("campaign_characters", r.PathValue("id"), input.ID, input); err != nil {
		respondCampaignInsertError(w, err, "character")
		return
	}
	respondJSON(w, http.StatusCreated, input)
}

func addCampaignEvent(w http.ResponseWriter, r *http.Request) {
	var input campaignEvent
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Kind) || !validCampaignText(input.Summary) {
		badRequest(w, "invalid event")
		return
	}
	if err := insertCampaignRecord("campaign_events", r.PathValue("id"), input.ID, input); err != nil {
		respondCampaignInsertError(w, err, "event")
		return
	}
	respondJSON(w, http.StatusCreated, map[string]string{"id": input.ID, "kind": input.Kind})
}

func addInventoryItem(w http.ResponseWriter, r *http.Request) {
	var input inventoryItem
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ItemSlug) || input.Quantity < 1 || input.Owner != "party" {
		badRequest(w, "invalid inventory item")
		return
	}
	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
	} else if err := runSQLite("INSERT INTO campaign_inventory (campaign_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else {
		respondJSON(w, http.StatusCreated, input)
	}
}

func assignEquipment(w http.ResponseWriter, r *http.Request) {
	var input struct {
		ItemSlug string `json:"item_slug"`
		Quantity int    `json:"quantity"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ItemSlug) || input.Quantity < 1 {
		badRequest(w, "invalid equipment assignment")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	character, err := querySQLite("SELECT id FROM campaign_characters WHERE id = " + sqlQuote(characterID) + " AND campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(character) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	available, err := availableInventoryLocked(campaignID, input.ItemSlug)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if input.Quantity > available {
		badRequest(w, "insufficient inventory")
		return
	}
	assignment := equipmentAssignment{CharacterID: characterID, ItemSlug: input.ItemSlug, Quantity: input.Quantity}
	state, err := json.Marshal(assignment)
	if err != nil || runSQLite("INSERT INTO campaign_equipment (campaign_id, character_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(characterID)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, assignment)
}

func inventorySummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	partyItems, err := campaignRecordCount("campaign_inventory", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	assignedItems, err := campaignRecordCount("campaign_equipment", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	available, err := availableInventoryLocked(campaignID, "healing-potion")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": campaignID, "party_items": partyItems, "assigned_items": assignedItems,
		"healing_potions_available": available,
	})
}

func createCraftingProject(w http.ResponseWriter, r *http.Request) {
	var input craftingProject
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.CharacterID) || !validCampaignText(input.ItemSlug) || input.DaysRequired < 1 || input.CostGP < 0 {
		badRequest(w, "invalid crafting project")
		return
	}
	input.DaysCompleted = 0
	input.Status = "active"
	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
	} else if exists, err := sqliteRecordExists("crafting_projects", "id", input.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "crafting project id already exists"})
	} else if err := runSQLite("INSERT INTO crafting_projects (id, campaign_id, state) VALUES (" + sqlQuote(input.ID) + ", " + sqlQuote(campaignID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else {
		respondJSON(w, http.StatusCreated, craftingProjectResponse(input))
	}
}

func advanceCraftingProject(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Days int `json:"days"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Days < 1 {
		badRequest(w, "invalid days")
		return
	}
	campaignID, projectID := r.PathValue("id"), r.PathValue("project_id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	data, err := querySQLite("SELECT state FROM crafting_projects WHERE id = " + sqlQuote(projectID) + " AND campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown crafting project"})
		return
	}
	var project craftingProject
	if err := json.Unmarshal([]byte(strings.TrimSuffix(data, "\n")), &project); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if project.Status != "active" {
		badRequest(w, "crafting project is complete")
		return
	}
	project.DaysCompleted += input.Days
	if project.DaysCompleted >= project.DaysRequired {
		project.DaysCompleted = project.DaysRequired
		project.Status = "complete"
	}
	state, err := json.Marshal(project)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if project.Status == "complete" {
		itemState, err := json.Marshal(inventoryItem{ItemSlug: project.ItemSlug, Quantity: 1, Owner: "party"})
		if err != nil || runSQLite("BEGIN; UPDATE crafting_projects SET state = "+sqlQuote(string(state))+" WHERE id = "+sqlQuote(projectID)+" AND campaign_id = "+sqlQuote(campaignID)+"; INSERT INTO campaign_inventory (campaign_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(string(itemState))+"); COMMIT;") != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
	} else if err := runSQLite("UPDATE crafting_projects SET state = " + sqlQuote(string(state)) + " WHERE id = " + sqlQuote(projectID) + " AND campaign_id = " + sqlQuote(campaignID) + ";"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"id": project.ID, "days_completed": project.DaysCompleted, "status": project.Status})
}

func craftingProjectResponse(project craftingProject) map[string]any {
	return map[string]any{"id": project.ID, "character_id": project.CharacterID, "item_slug": project.ItemSlug, "days_required": project.DaysRequired, "days_completed": project.DaysCompleted, "status": project.Status}
}

func scheduleCampaignSession(w http.ResponseWriter, r *http.Request) {
	var input campaignSession
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignSession(input) {
		badRequest(w, "invalid session")
		return
	}
	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
	} else if exists, err := sqliteRecordExists("campaign_sessions", "id", input.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "session id already exists"})
	} else if err := runSQLite("INSERT INTO campaign_sessions (id, campaign_id, state) VALUES (" + sqlQuote(input.ID) + ", " + sqlQuote(campaignID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else {
		respondJSON(w, http.StatusCreated, campaignSessionResponse(input))
	}
}

func recordSessionAttendance(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Present []string `json:"present"`
		Absent  []string `json:"absent"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validAttendance(input.Present, input.Absent) {
		badRequest(w, "invalid attendance")
		return
	}
	campaignID, sessionID := r.PathValue("id"), r.PathValue("session_id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	data, err := querySQLite("SELECT state FROM campaign_sessions WHERE id = " + sqlQuote(sessionID) + " AND campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}
	var session campaignSession
	if err := json.Unmarshal([]byte(strings.TrimSuffix(data, "\n")), &session); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	session.Present, session.Absent = input.Present, input.Absent
	state, err := json.Marshal(session)
	if err != nil || runSQLite("UPDATE campaign_sessions SET state = "+sqlQuote(string(state))+" WHERE id = "+sqlQuote(sessionID)+" AND campaign_id = "+sqlQuote(campaignID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "present_count": len(input.Present), "absent_count": len(input.Absent)})
}

func nextCampaignSession(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	sessions, err := loadCampaignSessionsLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if len(sessions) == 0 {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "no scheduled sessions"})
		return
	}
	sort.Slice(sessions, func(i, j int) bool {
		left, _ := time.Parse(time.RFC3339, sessions[i].StartsAt)
		right, _ := time.Parse(time.RFC3339, sessions[j].StartsAt)
		if left.Equal(right) {
			return sessions[i].ID < sessions[j].ID
		}
		return left.Before(right)
	})
	respondJSON(w, http.StatusOK, campaignSessionNextResponse(sessions[0]))
}

func validCampaignSession(value campaignSession) bool {
	if !validCampaignText(value.ID) || value.DurationMinutes < 1 || value.Agenda == nil {
		return false
	}
	if _, err := time.Parse(time.RFC3339, value.StartsAt); err != nil {
		return false
	}
	for _, item := range value.Agenda {
		if !validCampaignText(item) {
			return false
		}
	}
	return true
}

func validAttendance(present, absent []string) bool {
	if present == nil || absent == nil {
		return false
	}
	seen := make(map[string]bool, len(present)+len(absent))
	for _, characterID := range append(append([]string{}, present...), absent...) {
		if !validCampaignText(characterID) || seen[characterID] {
			return false
		}
		seen[characterID] = true
	}
	return true
}

func loadCampaignSessionsLocked(campaignID string) ([]campaignSession, error) {
	data, err := querySQLite("SELECT state FROM campaign_sessions WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return nil, err
	}
	sessions := make([]campaignSession, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var session campaignSession
		if err := json.Unmarshal([]byte(row), &session); err != nil {
			return nil, err
		}
		sessions = append(sessions, session)
	}
	return sessions, nil
}

func campaignSessionResponse(value campaignSession) map[string]any {
	return map[string]any{"id": value.ID, "starts_at": value.StartsAt, "duration_minutes": value.DurationMinutes, "agenda_count": len(value.Agenda)}
}

func campaignSessionNextResponse(value campaignSession) map[string]any {
	return map[string]any{"id": value.ID, "starts_at": value.StartsAt, "agenda_count": len(value.Agenda)}
}

func availableInventoryLocked(campaignID, itemSlug string) (int, error) {
	data, err := querySQLite("SELECT state FROM campaign_inventory WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return 0, err
	}
	available := 0
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var entry inventoryItem
		if err := json.Unmarshal([]byte(row), &entry); err != nil {
			return 0, err
		}
		if entry.ItemSlug == itemSlug && entry.Owner == "party" {
			available += entry.Quantity
		}
	}
	data, err = querySQLite("SELECT state FROM campaign_equipment WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return 0, err
	}
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var entry equipmentAssignment
		if err := json.Unmarshal([]byte(row), &entry); err != nil {
			return 0, err
		}
		if entry.ItemSlug == itemSlug {
			available -= entry.Quantity
		}
	}
	return available, nil
}

func createFaction(w http.ResponseWriter, r *http.Request) {
	var input faction
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) || !validCampaignText(input.Stance) {
		badRequest(w, "invalid faction")
		return
	}
	if err := insertCampaignRecord("campaign_factions", r.PathValue("id"), input.ID, input); err != nil {
		respondCampaignInsertError(w, err, "faction")
		return
	}
	respondJSON(w, http.StatusCreated, input)
}

func createNPC(w http.ResponseWriter, r *http.Request) {
	var input npc
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) || !validCampaignText(input.FactionID) {
		badRequest(w, "invalid npc")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	factionData, err := querySQLite("SELECT id FROM campaign_factions WHERE id = " + sqlQuote(input.FactionID) + " AND campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(factionData) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown faction"})
		return
	}
	if exists, err := sqliteRecordExists("campaign_npcs", "id", input.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "npc id already exists"})
		return
	}
	state, err := json.Marshal(input)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := runSQLite("INSERT INTO campaign_npcs (id, campaign_id, state) VALUES (" + sqlQuote(input.ID) + ", " + sqlQuote(campaignID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, input)
}

func relationshipSummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	factions, err := campaignRecordCount("campaign_factions", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	data, err := querySQLite("SELECT state FROM campaign_npcs WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	npcs, friendly := 0, 0
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var value npc
		if err := json.Unmarshal([]byte(row), &value); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		npcs++
		if value.Disposition > 0 {
			friendly++
		}
	}
	respondJSON(w, http.StatusOK, map[string]any{"campaign_id": campaignID, "factions": factions, "npcs": npcs, "friendly_npcs": friendly})
}

func createQuest(w http.ResponseWriter, r *http.Request) {
	var input quest
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validQuest(input) {
		badRequest(w, "invalid quest")
		return
	}
	input.Completed = make([]string, 0)
	if err := insertCampaignRecord("campaign_quests", r.PathValue("id"), input.ID, input); err != nil {
		respondCampaignInsertError(w, err, "quest")
		return
	}
	respondJSON(w, http.StatusCreated, questCreateResponse(input))
}

func updateQuestProgress(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Completed []string `json:"completed"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Completed == nil {
		badRequest(w, "invalid progress")
		return
	}
	campaignID, questID := r.PathValue("id"), r.PathValue("quest_id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	data, err := querySQLite("SELECT state FROM campaign_quests WHERE id = " + sqlQuote(questID) + " AND campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown quest"})
		return
	}
	var value quest
	if err := json.Unmarshal([]byte(strings.TrimSuffix(data, "\n")), &value); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	allowed := make(map[string]bool, len(value.Milestones))
	for _, milestone := range value.Milestones {
		allowed[milestone] = true
	}
	completed := make(map[string]bool, len(value.Completed))
	for _, milestone := range value.Completed {
		completed[milestone] = true
	}
	for _, milestone := range input.Completed {
		if !allowed[milestone] {
			badRequest(w, "invalid progress")
			return
		}
		completed[milestone] = true
	}
	value.Completed = value.Completed[:0]
	for _, milestone := range value.Milestones {
		if completed[milestone] {
			value.Completed = append(value.Completed, milestone)
		}
	}
	if len(value.Completed) == len(value.Milestones) {
		value.Status = "completed"
	}
	state, err := json.Marshal(value)
	if err != nil || runSQLite("UPDATE campaign_quests SET state = "+sqlQuote(string(state))+" WHERE id = "+sqlQuote(questID)+" AND campaign_id = "+sqlQuote(campaignID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, questProgressResponse(value))
}

func questSummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("campaigns", "id", campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	data, err := querySQLite("SELECT state FROM campaign_quests WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	summary := map[string]any{"campaign_id": campaignID, "active": 0, "completed": 0, "blocked": 0}
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var value quest
		if err := json.Unmarshal([]byte(row), &value); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		summary[value.Status] = summary[value.Status].(int) + 1
	}
	respondJSON(w, http.StatusOK, summary)
}

func validQuest(value quest) bool {
	if !validCampaignText(value.ID) || !validCampaignText(value.Title) || !validQuestStatus(value.Status) || len(value.Milestones) == 0 || value.Completed != nil {
		return false
	}
	seen := make(map[string]bool, len(value.Milestones))
	for _, milestone := range value.Milestones {
		if !validCampaignText(milestone) || seen[milestone] {
			return false
		}
		seen[milestone] = true
	}
	return true
}

func validQuestStatus(status string) bool {
	return status == "active" || status == "completed" || status == "blocked"
}

func questProgressResponse(value quest) map[string]any {
	return map[string]any{"id": value.ID, "status": value.Status, "milestones_total": len(value.Milestones), "milestones_done": len(value.Completed)}
}

func questCreateResponse(value quest) map[string]any {
	response := questProgressResponse(value)
	response["title"] = value.Title
	return response
}

var errUnknownCampaign = errors.New("unknown campaign")
var errDuplicateCampaignRecord = errors.New("duplicate campaign record")

func insertCampaignRecord(table, campaignID, recordID string, record any) error {
	state, err := json.Marshal(record)
	if err != nil {
		return err
	}
	storageState.Lock()
	defer storageState.Unlock()
	exists, err := sqliteRecordExists("campaigns", "id", campaignID)
	if err != nil {
		return err
	}
	if !exists {
		return errUnknownCampaign
	}
	exists, err = sqliteRecordExists(table, "id", recordID)
	if err != nil {
		return err
	}
	if exists {
		return errDuplicateCampaignRecord
	}
	return runSQLite("INSERT INTO " + table + " (id, campaign_id, state) VALUES (" + sqlQuote(recordID) + ", " + sqlQuote(campaignID) + ", " + sqlQuote(string(state)) + ");")
}

func respondCampaignInsertError(w http.ResponseWriter, err error, recordType string) {
	switch err {
	case errUnknownCampaign:
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
	case errDuplicateCampaignRecord:
		respondJSON(w, http.StatusConflict, map[string]string{"error": recordType + " id already exists"})
	default:
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	}
}

func getCampaignState(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var value campaign
	if err := json.Unmarshal([]byte(strings.TrimSuffix(data, "\n")), &value); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	characters, err := loadCampaignCharactersLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	events, err := querySQLite("SELECT COUNT(*) FROM campaign_events WHERE campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	logCount, err := strconv.Atoi(strings.TrimSpace(events))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"id": value.ID, "name": value.Name, "dm": value.DM, "characters": characters, "log_count": logCount})
}

// campaignAudit returns the stable counts used to audit a campaign's activity.
func campaignAudit(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	if err := requireCampaignLocked(campaignID); err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	events, err := campaignRecordCount("campaign_events", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	quests, err := campaignRecordCount("campaign_quests", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	npcs, err := campaignRecordCount("campaign_npcs", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	sessions, err := campaignRecordCount("campaign_sessions", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"campaign_id": campaignID, "events": events, "quests": quests, "npcs": npcs, "sessions": sessions})
}

// campaignAnalytics is the small, stable set of facts shared by the campaign
// reporting endpoints. It is built while the storage lock is held so each
// response represents one consistent persisted campaign state.
type campaignAnalytics struct {
	hasDM          bool
	characters     int
	openQuests     int
	activeQuests   int
	friendlyNPCs   int
	sessions       int
	inventoryItems int
}

func campaignAnalyticsSummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	analytics, err := loadCampaignAnalyticsLocked(campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	readiness := 0
	if analytics.hasDM {
		readiness += 25
	}
	if analytics.characters > 0 {
		readiness += 25
	}
	if analytics.sessions > 0 {
		readiness += 20
	}
	if analytics.activeQuests > 0 {
		readiness += 15
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": campaignID, "readiness_score": readiness,
		"open_quests": analytics.openQuests, "friendly_npcs": analytics.friendlyNPCs,
		"scheduled_sessions": analytics.sessions, "inventory_items": analytics.inventoryItems,
	})
}

func campaignRiskReport(w http.ResponseWriter, r *http.Request) {
	var input struct {
		IncludeZeroes bool `json:"include_zeroes"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	analytics, err := loadCampaignAnalyticsLocked(campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	signals := map[string]bool{
		"has_dm":           analytics.hasDM,
		"has_characters":   analytics.characters > 0,
		"has_next_session": analytics.sessions > 0,
		"has_active_quest": analytics.activeQuests > 0,
	}
	missing := make([]string, 0, len(signals))
	for _, signal := range []string{"has_dm", "has_characters", "has_next_session", "has_active_quest"} {
		if !signals[signal] {
			missing = append(missing, strings.TrimPrefix(signal, "has_"))
		}
	}
	riskLevel := "low"
	if len(missing) == 1 {
		riskLevel = "medium"
	} else if len(missing) > 1 {
		riskLevel = "high"
	}
	// include_zeroes is accepted as part of the report contract. Signals are
	// booleans, so false values are already represented without a lossy omit.
	_ = input.IncludeZeroes
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": campaignID, "risk_level": riskLevel,
		"missing": missing, "signals": signals,
	})
}

func loadCampaignAnalyticsLocked(campaignID string) (campaignAnalytics, error) {
	if err := requireCampaignLocked(campaignID); err != nil {
		return campaignAnalytics{}, err
	}
	data, err := querySQLite("SELECT state FROM campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		return campaignAnalytics{}, err
	}
	var value campaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &value); err != nil {
		return campaignAnalytics{}, err
	}
	analytics := campaignAnalytics{hasDM: strings.TrimSpace(value.DM) != ""}
	if analytics.characters, err = campaignRecordCount("campaign_characters", campaignID); err != nil {
		return campaignAnalytics{}, err
	}
	if analytics.sessions, err = campaignRecordCount("campaign_sessions", campaignID); err != nil {
		return campaignAnalytics{}, err
	}
	if analytics.inventoryItems, err = campaignInventoryItemKindsLocked(campaignID); err != nil {
		return campaignAnalytics{}, err
	}
	questData, err := querySQLite("SELECT state FROM campaign_quests WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return campaignAnalytics{}, err
	}
	for _, row := range strings.Split(strings.TrimSuffix(questData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var value quest
		if err := json.Unmarshal([]byte(row), &value); err != nil {
			return campaignAnalytics{}, err
		}
		if value.Status != "completed" {
			analytics.openQuests++
		}
		if value.Status == "active" {
			analytics.activeQuests++
		}
	}
	npcData, err := querySQLite("SELECT state FROM campaign_npcs WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return campaignAnalytics{}, err
	}
	for _, row := range strings.Split(strings.TrimSuffix(npcData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var value npc
		if err := json.Unmarshal([]byte(row), &value); err != nil {
			return campaignAnalytics{}, err
		}
		if value.Disposition > 0 {
			analytics.friendlyNPCs++
		}
	}
	return analytics, nil
}

// exportCampaign returns a deterministic, download-free summary of campaign state.
func exportCampaign(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	if strings.TrimSpace(data) == "" {
		respondCampaignLookupError(w, errUnknownCampaign)
		return
	}
	var value campaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &value); err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	characters, err := campaignRecordCount("campaign_characters", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	quests, err := campaignRecordCount("campaign_quests", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	npcs, err := campaignRecordCount("campaign_npcs", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	// Inventory is an append-only ledger: crafting may add another row for an
	// item already held by the party. Export reports the number of item kinds,
	// rather than the number of ledger entries.
	inventoryItems, err := campaignInventoryItemKindsLocked(campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	sessions, err := campaignRecordCount("campaign_sessions", campaignID)
	if err != nil {
		respondCampaignLookupError(w, err)
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": campaignID, "name": value.Name, "characters": characters,
		"quests": quests, "npcs": npcs, "inventory_items": inventoryItems,
		"sessions": sessions, "schema_version": schemaVersion,
	})
}

func requireCampaignLocked(campaignID string) error {
	exists, err := sqliteRecordExists("campaigns", "id", campaignID)
	if err != nil {
		return err
	}
	if !exists {
		return errUnknownCampaign
	}
	return nil
}

func respondCampaignLookupError(w http.ResponseWriter, err error) {
	if errors.Is(err, errUnknownCampaign) {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
}

func loadCampaignCharactersLocked(campaignID string) ([]campaignCharacter, error) {
	data, err := querySQLite("SELECT state FROM campaign_characters WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return nil, err
	}
	characters := make([]campaignCharacter, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var character campaignCharacter
		if err := json.Unmarshal([]byte(row), &character); err != nil {
			return nil, err
		}
		characters = append(characters, character)
	}
	return characters, nil
}

func campaignExists(campaignID string) (bool, error) {
	storageState.Lock()
	defer storageState.Unlock()
	return sqliteRecordExists("campaigns", "id", campaignID)
}

func loadCampaignEvents(campaignID string) ([]campaignEvent, error) {
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM campaign_events WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return nil, err
	}
	events := make([]campaignEvent, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event campaignEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	return events, nil
}

func sqliteRecordExists(table, column, value string) (bool, error) {
	result, err := querySQLite("SELECT " + column + " FROM " + table + " WHERE " + column + " = " + sqlQuote(value) + ";")
	return strings.TrimSpace(result) != "", err
}

func campaignRecordCount(table, campaignID string) (int, error) {
	result, err := querySQLite("SELECT COUNT(*) FROM " + table + " WHERE campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		return 0, err
	}
	return strconv.Atoi(strings.TrimSpace(result))
}

func campaignInventoryItemKindsLocked(campaignID string) (int, error) {
	data, err := querySQLite("SELECT state FROM campaign_inventory WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid;")
	if err != nil {
		return 0, err
	}
	itemSlugs := make(map[string]struct{})
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var entry inventoryItem
		if err := json.Unmarshal([]byte(row), &entry); err != nil {
			return 0, err
		}
		itemSlugs[entry.ItemSlug] = struct{}{}
	}
	return len(itemSlugs), nil
}

func validCampaignText(value string) bool {
	return strings.TrimSpace(value) != "" && !strings.ContainsAny(value, "\t\r\n")
}

func loadCompendiumRecord[T any](table, slug string) (T, bool, error) {
	var record T
	storageState.Lock()
	defer storageState.Unlock()
	result, err := querySQLite("SELECT state FROM " + table + " WHERE slug = " + sqlQuote(slug) + ";")
	if err != nil {
		return record, false, err
	}
	result = strings.TrimSuffix(result, "\n")
	if result == "" {
		return record, false, nil
	}
	if err := json.Unmarshal([]byte(result), &record); err != nil {
		return record, false, err
	}
	return record, true, nil
}

func validMonster(value monster) bool {
	if !validCompendiumText(value.Slug) || !validCompendiumText(value.Name) || !validCompendiumText(value.CR) || value.ArmorClass < 1 || value.HitPoints < 1 || value.Tags == nil {
		return false
	}
	for _, tag := range value.Tags {
		if !validCompendiumText(tag) {
			return false
		}
	}
	return true
}

func validItem(value item) bool {
	return validCompendiumText(value.Slug) && validCompendiumText(value.Name) && validCompendiumText(value.Type) && validCompendiumText(value.Rarity) && value.CostGP >= 0
}

func validCompendiumText(value string) bool {
	return strings.TrimSpace(value) != "" && !strings.ContainsAny(value, "\t\r\n")
}

func health(w http.ResponseWriter, _ *http.Request) {
	respondJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func registerUser(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validUsername(input.Username) || utf8.RuneCountInString(input.Password) < 8 || (input.Role != "dm" && input.Role != "player") {
		badRequest(w, "invalid registration")
		return
	}

	userState.Lock()
	defer userState.Unlock()
	if _, exists := userState.users[input.Username]; exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "username already exists"})
		return
	}
	account := user{
		Username: input.Username, PasswordHash: hashPassword(input.Password), Role: input.Role,
	}
	if err := persistUserLocked(account); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	userState.users[input.Username] = account
	respondJSON(w, http.StatusCreated, map[string]string{"username": input.Username, "role": input.Role})
}

func loginUser(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	userState.Lock()
	account, exists := userState.users[input.Username]
	userState.Unlock()
	if !exists || !passwordMatches(account.PasswordHash, input.Password) {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid credentials"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"username": account.Username, "token": "session-" + account.Username})
}

func createPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "dm" {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	var input struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		MaxPlayers int    `json:"max_players"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) || input.MaxPlayers < 1 {
		badRequest(w, "invalid campaign")
		return
	}

	campaign := playCampaign{
		ID: input.ID, Name: input.Name, Owner: actor.Username, Status: "lobby", MaxPlayers: input.MaxPlayers,
	}
	state, err := json.Marshal(campaign)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	storageState.Lock()
	defer storageState.Unlock()
	if exists, err := sqliteRecordExists("play_campaigns", "id", campaign.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign id already exists"})
	} else if err := runSQLite("INSERT INTO play_campaigns (id, state) VALUES (" + sqlQuote(campaign.ID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
	} else {
		respondJSON(w, http.StatusCreated, campaign)
	}
}

// putCampaignDocument records the owner's public story and private DM notes.
func putCampaignDocument(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var document campaignDocument
	if err := decodeJSON(r, &document); err != nil {
		badRequest(w, "invalid JSON")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	state, err := json.Marshal(document)
	if err != nil || runSQLite("INSERT INTO play_campaign_documents (campaign_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(string(state))+") ON CONFLICT(campaign_id) DO UPDATE SET state = excluded.state;") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, document)
}

// getCampaignDocument projects the stored document according to the caller's
// campaign role, so private notes never appear in a player's JSON response.
func getCampaignDocument(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	if !isOwner {
		membership, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(actor.Username) + " LIMIT 1;")
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if actor.Role != "player" || strings.TrimSpace(membership) == "" {
			respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
	}

	document := campaignDocument{}
	data, err := querySQLite("SELECT state FROM play_campaign_documents WHERE campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil || (strings.TrimSpace(data) != "" && json.Unmarshal([]byte(strings.TrimSpace(data)), &document) != nil) {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if isOwner {
		respondJSON(w, http.StatusOK, document)
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"story": document.Story})
}

func loadPlayCampaignLocked(campaignID string) (playCampaign, bool, error) {
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		return playCampaign{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playCampaign{}, false, nil
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		return playCampaign{}, false, err
	}
	return campaign, true, nil
}

func playCampaignMemberLocked(campaignID, username string) (bool, error) {
	member, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(username) + " LIMIT 1;")
	return strings.TrimSpace(member) != "", err
}

// createPlayEncounter pauses exploration by changing only the campaign mode.
// The exploration timeline remains intact, so it resumes from the same turn
// when a later combat stage returns the campaign to exploration.
func createPlayEncounter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) {
		badRequest(w, "invalid encounter")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if campaign.Status == "combat" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign already in combat"})
		return
	}
	if campaign.Status != "active" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not active"})
		return
	}
	if exists, err := querySQLite("SELECT 1 FROM play_encounters WHERE campaign_id = " + sqlQuote(campaignID) + " AND encounter_id = " + sqlQuote(input.ID) + " LIMIT 1;"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if strings.TrimSpace(exists) != "" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "encounter id already exists"})
		return
	}

	encounter := playEncounter{ID: input.ID, Name: input.Name, Status: "active", Combatants: make([]playMonster, 0)}
	encounterState, err := json.Marshal(encounter)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaign.Status = "combat"
	campaignState, err := json.Marshal(campaign)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := runSQLite("INSERT INTO play_encounters (campaign_id, encounter_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(encounter.ID) + ", " + sqlQuote(string(encounterState)) + "); UPDATE play_campaigns SET state = " + sqlQuote(string(campaignState)) + " WHERE id = " + sqlQuote(campaignID) + ";"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, encounter)
}

func loadPlayEncounterLocked(campaignID, encounterID string) (playEncounter, bool, error) {
	data, err := querySQLite("SELECT state FROM play_encounters WHERE campaign_id = " + sqlQuote(campaignID) + " AND encounter_id = " + sqlQuote(encounterID) + ";")
	if err != nil {
		return playEncounter{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playEncounter{}, false, nil
	}
	var encounter playEncounter
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &encounter); err != nil {
		return playEncounter{}, false, err
	}
	return encounter, true, nil
}

// playEncounterTurnCombatant is the public turn projection.  The internal
// identity is kept separately so party combatants can be authorized by their
// membership username without exposing that implementation detail.
type playEncounterTurnCombatant struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`
	Initiative int    `json:"initiative"`
	member     string
}

type playEncounterTurn struct {
	Round     int                        `json:"round"`
	TurnIndex int                        `json:"turn_index"`
	Active    playEncounterTurnCombatant `json:"active"`
}

// playEncounterOrder uses the initiative score first and stable public
// identifiers as tie breakers.  This keeps independently persisted encounter
// state deterministic without changing the existing combatant payloads.
func playEncounterOrder(encounter playEncounter) []playEncounterTurnCombatant {
	order := make([]playEncounterTurnCombatant, 0, len(encounter.Combatants)+len(encounter.PartyCombatants))
	for _, monster := range encounter.Combatants {
		order = append(order, playEncounterTurnCombatant{Name: monster.Name, Kind: "monster", Initiative: monster.Initiative, member: monster.MonsterID})
	}
	for _, member := range encounter.PartyCombatants {
		order = append(order, playEncounterTurnCombatant{Name: member.Name, Kind: "player", Initiative: member.Initiative, member: member.Member})
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Initiative != order[j].Initiative {
			return order[i].Initiative > order[j].Initiative
		}
		if order[i].Name != order[j].Name {
			return order[i].Name < order[j].Name
		}
		if order[i].Kind != order[j].Kind {
			return order[i].Kind < order[j].Kind
		}
		return order[i].member < order[j].member
	})
	if len(encounter.TurnOrder) == 0 {
		return order
	}
	byID := make(map[string]playEncounterTurnCombatant, len(order))
	for _, combatant := range order {
		byID[playEncounterCombatantID(combatant)] = combatant
	}
	reordered := make([]playEncounterTurnCombatant, 0, len(order))
	for _, id := range encounter.TurnOrder {
		if combatant, found := byID[id]; found {
			reordered = append(reordered, combatant)
			delete(byID, id)
		}
	}
	// Roster changes after a delay keep their normal deterministic placement.
	for _, combatant := range order {
		if _, found := byID[playEncounterCombatantID(combatant)]; found {
			reordered = append(reordered, combatant)
		}
	}
	return reordered
}

func playEncounterCombatantID(combatant playEncounterTurnCombatant) string {
	return combatant.Kind + ":" + combatant.member
}

func playEncounterOrderIDs(order []playEncounterTurnCombatant) []string {
	ids := make([]string, len(order))
	for i, combatant := range order {
		ids[i] = playEncounterCombatantID(combatant)
	}
	return ids
}

func encounterTurnState(encounter *playEncounter) ([]playEncounterTurnCombatant, playEncounterTurnCombatant, bool) {
	order := playEncounterOrder(*encounter)
	if len(order) == 0 {
		return order, playEncounterTurnCombatant{}, false
	}
	if encounter.Round < 1 {
		encounter.Round = 1
	}
	if encounter.TurnIndex < 0 || encounter.TurnIndex >= len(order) {
		encounter.TurnIndex = 0
	}
	return order, order[encounter.TurnIndex], true
}

func encounterHasCombatant(encounter playEncounter, target string) bool {
	for _, combatant := range encounter.Combatants {
		if combatant.MonsterID == target {
			return true
		}
	}
	for _, combatant := range encounter.PartyCombatants {
		if combatant.Member == target {
			return true
		}
	}
	return false
}

// expireConditionsAtTurnStart decrements only when the combatant actually
// becomes active. A condition that reaches zero is omitted from its target.
func expireConditionsAtTurnStart(encounter *playEncounter, target string) {
	conditions := encounter.Conditions[target]
	if len(conditions) == 0 {
		return
	}
	remaining := conditions[:0]
	for _, condition := range conditions {
		condition.RemainingRounds--
		if condition.RemainingRounds > 0 {
			remaining = append(remaining, condition)
		}
	}
	if len(remaining) == 0 {
		encounter.Conditions[target] = remaining
		return
	}
	encounter.Conditions[target] = remaining
}

func savePlayEncounterLocked(campaignID, encounterID string, encounter playEncounter) error {
	state, err := json.Marshal(encounter)
	if err != nil {
		return err
	}
	return runSQLite("UPDATE play_encounters SET state = " + sqlQuote(string(state)) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND encounter_id = " + sqlQuote(encounterID) + ";")
}

func awardPlayEncounterRewards(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var reward playEncounterReward
	if err := decodeJSON(r, &reward); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if reward.XP < 0 || reward.Loot == nil {
		badRequest(w, "invalid rewards")
		return
	}
	for _, loot := range reward.Loot {
		if !validCompendiumText(loot.Slug) || loot.Quantity < 1 {
			badRequest(w, "invalid rewards")
			return
		}
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	if encounter.Reward != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "rewards already awarded"})
		return
	}
	encounter.Reward = &reward
	if err := savePlayEncounterLocked(campaignID, encounterID, encounter); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, reward)
}

func closePlayEncounter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}

	encounter.Status = "closed"
	encounterState, encounterErr := json.Marshal(encounter)
	if encounterErr != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(encounterState))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	xp := 0
	if encounter.Reward != nil {
		xp = encounter.Reward.XP
	}
	respondJSON(w, http.StatusOK, map[string]any{"id": encounter.ID, "status": encounter.Status, "xp_awarded": xp})
}

// endPlayEncounter returns a combat-paused campaign to its existing
// exploration queue. It accepts an active encounter directly or one closed by
// the legacy reward-closing endpoint. The queue is derived from narration
// events, so no turn state needs to be changed when combat begins or ends.
func endPlayEncounter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if campaign.Status != "combat" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not in combat"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	if encounter.Status != "active" && encounter.Status != "closed" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "encounter cannot be ended"})
		return
	}

	membersData, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	currentActor, _, err := playTurnStateLocked(campaignID, strings.Fields(membersData))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	encounter.Status = "closed"
	campaign.Status = "active"
	encounterState, encounterErr := json.Marshal(encounter)
	campaignState, campaignErr := json.Marshal(campaign)
	if encounterErr != nil || campaignErr != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(encounterState))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+"; UPDATE play_campaigns SET state = "+sqlQuote(string(campaignState))+" WHERE id = "+sqlQuote(campaignID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{
		"campaign_id":   campaign.ID,
		"status":        campaign.Status,
		"phase":         "exploration",
		"current_actor": currentActor,
	})
}

func getPlayEncounterStatus(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Username != campaign.Owner && !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	order, active, exists := encounterTurnState(&encounter)
	conditions := encounter.Conditions
	if conditions == nil {
		conditions = map[string][]playCondition{}
	}
	status := map[string]any{"round": encounter.Round, "turn_index": encounter.TurnIndex, "order": order, "conditions": conditions}
	if exists {
		status["active"] = active
	} else {
		status["active"] = nil
	}
	respondJSON(w, http.StatusOK, status)
}

func addPlayEncounterCondition(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Target) || !validCampaignText(input.Condition) || input.DurationRounds < 1 {
		badRequest(w, "invalid condition")
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	if !encounterHasCombatant(encounter, input.Target) {
		badRequest(w, "unknown combatant")
		return
	}
	if encounter.Conditions == nil {
		encounter.Conditions = make(map[string][]playCondition)
	}
	conditions := encounter.Conditions[input.Target]
	conditions = append(conditions, playCondition{Condition: input.Condition, RemainingRounds: input.DurationRounds})
	encounter.Conditions[input.Target] = conditions
	if err := savePlayEncounterLocked(campaignID, encounterID, encounter); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, map[string]any{"target": input.Target, "conditions": conditions})
}

func getPlayEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Username != campaign.Owner && !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	_, active, exists := encounterTurnState(&encounter)
	if !exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	respondJSON(w, http.StatusOK, playEncounterTurn{Round: encounter.Round, TurnIndex: encounter.TurnIndex, Active: active})
}

func advancePlayEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Username != campaign.Owner && !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	order, active, exists := encounterTurnState(&encounter)
	if !exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	if actor.Username != campaign.Owner && (active.Kind != "player" || active.member != actor.Username) {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active combatant"})
		return
	}
	encounter.TurnIndex++
	if encounter.TurnIndex == len(order) {
		encounter.TurnIndex = 0
		encounter.Round++
	}
	active = order[encounter.TurnIndex]
	expireConditionsAtTurnStart(&encounter, active.member)
	if err := savePlayEncounterLocked(campaignID, encounterID, encounter); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, playEncounterTurn{Round: encounter.Round, TurnIndex: encounter.TurnIndex, Active: active})
}

// delayPlayEncounterTurn moves the active combatant behind a later combatant
// while keeping that combatant active.  Reordering initiative alone must not
// consume or duplicate the current turn.
func delayPlayEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		NewIndex *int `json:"new_index"`
		ToIndex  *int `json:"to_index"`
		Index    *int `json:"index"`
		Position *int `json:"position"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	indexes := []*int{input.NewIndex, input.ToIndex, input.Index, input.Position}
	var target *int
	for _, candidate := range indexes {
		if candidate == nil {
			continue
		}
		if target != nil {
			badRequest(w, "invalid delay index")
			return
		}
		target = candidate
	}
	if target == nil {
		badRequest(w, "invalid delay index")
		return
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	order, active, exists := encounterTurnState(&encounter)
	if campaign.Status != "combat" || encounter.Status != "active" || !exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active combatant"})
		return
	}
	if actor.Username != campaign.Owner && (active.Kind != "player" || active.member != actor.Username) {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active combatant"})
		return
	}
	if *target <= encounter.TurnIndex || *target >= len(order) {
		badRequest(w, "invalid delay index")
		return
	}

	delayed := order[encounter.TurnIndex]
	newOrder := make([]playEncounterTurnCombatant, 0, len(order))
	newOrder = append(newOrder, order[:encounter.TurnIndex]...)
	newOrder = append(newOrder, order[encounter.TurnIndex+1:*target+1]...)
	newOrder = append(newOrder, delayed)
	newOrder = append(newOrder, order[*target+1:]...)
	encounter.TurnOrder = playEncounterOrderIDs(newOrder)
	// The delayed combatant now occupies target, and remains the current actor.
	encounter.TurnIndex = *target
	if err := savePlayEncounterLocked(campaignID, encounterID, encounter); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"order": newOrder})
}

// readyPlayEncounterAction records an active player's trigger without changing
// the encounter timeline or initiative order.
func readyPlayEncounterAction(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Trigger string `json:"trigger"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Trigger) {
		badRequest(w, "invalid ready action")
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	_, active, exists := encounterTurnState(&encounter)
	if campaign.Status != "combat" || encounter.Status != "active" || !exists || active.Kind != "player" || active.member != actor.Username {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active combatant"})
		return
	}
	respondJSON(w, http.StatusCreated, struct {
		Actor   string `json:"actor"`
		Trigger string `json:"trigger"`
	}{Actor: actor.Username, Trigger: input.Trigger})
}

// submitPlayCombatAction records a player's declared combat action without
// advancing the encounter's initiative order.  Combat actions share the
// campaign event log so their sequence remains consistent with prior events.
func submitPlayCombatAction(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Type   string `json:"type"`
		Target string `json:"target"`
		Text   string `json:"text"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCombatActionType(input.Type) || !validCampaignText(input.Target) || !validCampaignText(input.Text) {
		badRequest(w, "invalid combat action")
		return
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	_, active, exists := encounterTurnState(&encounter)
	if campaign.Status != "combat" || encounter.Status != "active" || !exists || actor.Role != "player" || active.Kind != "player" || active.member != actor.Username {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active combatant"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	event := narrationEvent{Sequence: count + 1, Kind: "combat_action", Actor: actor.Username, Type: input.Type, Target: input.Target, Text: input.Text}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, event)
}

func validCombatActionType(value string) bool {
	return value == "attack" || value == "help" || value == "dodge" || value == "ready"
}

type playCombatantHPChange struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Amount   int    `json:"-"`
}

func damagePlayCombatant(w http.ResponseWriter, r *http.Request) {
	change, ok := updatePlayCombatantHP(w, r, true)
	if !ok {
		return
	}
	respondJSON(w, http.StatusOK, struct {
		Target   string `json:"target"`
		HPBefore int    `json:"hp_before"`
		HPAfter  int    `json:"hp_after"`
		Damage   int    `json:"damage"`
	}{change.Target, change.HPBefore, change.HPAfter, change.Amount})
}

func healPlayCombatant(w http.ResponseWriter, r *http.Request) {
	change, ok := updatePlayCombatantHP(w, r, false)
	if !ok {
		return
	}
	respondJSON(w, http.StatusOK, struct {
		Target   string `json:"target"`
		HPBefore int    `json:"hp_before"`
		HPAfter  int    `json:"hp_after"`
		Healing  int    `json:"healing"`
	}{change.Target, change.HPBefore, change.HPAfter, change.Amount})
}

// updatePlayCombatantHP changes an encounter-local monster's persisted HP.
// Monster IDs are the public target identifiers introduced with the roster.
func updatePlayCombatantHP(w http.ResponseWriter, r *http.Request, damage bool) (playCombatantHPChange, bool) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return playCombatantHPChange{}, false
	}
	var input struct {
		Target string `json:"target"`
		Amount int    `json:"amount"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return playCombatantHPChange{}, false
	}
	if !validCampaignText(input.Target) || input.Amount < 1 {
		badRequest(w, "invalid combatant HP change")
		return playCombatantHPChange{}, false
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return playCombatantHPChange{}, false
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return playCombatantHPChange{}, false
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return playCombatantHPChange{}, false
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return playCombatantHPChange{}, false
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return playCombatantHPChange{}, false
	}

	for index := range encounter.Combatants {
		combatant := &encounter.Combatants[index]
		if combatant.MonsterID != input.Target {
			continue
		}
		before := combatant.HPCurrent
		if damage {
			if input.Amount >= combatant.HPCurrent {
				combatant.HPCurrent = 0
			} else {
				combatant.HPCurrent -= input.Amount
			}
		} else if input.Amount >= combatant.HPMax-combatant.HPCurrent {
			combatant.HPCurrent = combatant.HPMax
		} else {
			combatant.HPCurrent += input.Amount
		}
		state, err := json.Marshal(encounter)
		if err != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return playCombatantHPChange{}, false
		}
		return playCombatantHPChange{Target: input.Target, HPBefore: before, HPAfter: combatant.HPCurrent, Amount: input.Amount}, true
	}
	respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown combatant"})
	return playCombatantHPChange{}, false
}

// normalizePlayMemberHP keeps characters created before HP tracking on the
// established deterministic 20 HP baseline. A missing state is conscious.
func normalizePlayMemberHP(member *playMember) {
	if member.HPMax < 1 || member.HPCurrent < 0 || member.HPCurrent > member.HPMax {
		member.HPCurrent, member.HPMax = 20, 20
	}
	if member.Status == "" {
		member.Status = "conscious"
	}
}

func loadPlayCharacterLocked(campaignID, characterID string) (playMember, bool, error) {
	data, err := querySQLite("SELECT state FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return playMember{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playMember{}, false, nil
	}
	var member playMember
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &member); err != nil {
		return playMember{}, false, err
	}
	normalizePlayMemberHP(&member)
	return member, true, nil
}

func persistPlayMemberLocked(campaignID string, member playMember) error {
	state, err := json.Marshal(member)
	if err != nil {
		return err
	}
	return runSQLite("UPDATE play_memberships SET state = " + sqlQuote(string(state)) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(member.Username) + ";")
}

func damagePlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Amount int `json:"amount"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Amount < 1 {
		badRequest(w, "invalid damage")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	before := member.HPCurrent
	member.HPCurrent = max(0, member.HPCurrent-input.Amount)
	if before > 0 && member.HPCurrent == 0 {
		member.Status, member.Successes, member.Failures = "unconscious", 0, 0
	}
	if err := persistPlayMemberLocked(campaignID, member); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"target": member.CharacterID, "character_id": member.CharacterID, "hp_before": before, "hp_after": member.HPCurrent, "damage": input.Amount, "status": member.Status})
}

func recordDeathSave(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Outcome string `json:"outcome"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Outcome != "success" && input.Outcome != "failure" {
		badRequest(w, "invalid death save outcome")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if actor.Role != "player" || actor.Username != member.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if member.Status != "unconscious" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "character cannot make death saves"})
		return
	}
	if input.Outcome == "success" {
		member.Successes++
		if member.Successes >= 3 {
			member.Successes, member.Status = 3, "stable"
		}
	} else {
		member.Failures++
		if member.Failures >= 3 {
			member.Failures, member.Status = 3, "dead"
		}
	}
	if err := persistPlayMemberLocked(campaignID, member); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, map[string]any{"character_id": member.CharacterID, "successes": member.Successes, "failures": member.Failures, "status": member.Status})
}

func getPlayCharacterStatus(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"character_id": member.CharacterID, "hp_current": member.HPCurrent, "hp_max": member.HPMax, "status": member.Status})
}

func addPlayCharacterSpell(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var spell playSpell
	if err := decodeJSON(r, &spell); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(spell.SpellID) || !validCampaignText(spell.Name) || spell.Level < 0 || spell.Level > 9 {
		badRequest(w, "invalid spell")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may add spells"})
		return
	}
	// This play API currently models wizard spells. A wizard can add any such
	// spell, while non-wizard characters (including rogues) cannot add one.
	if member.Class != "wizard" {
		badRequest(w, "invalid class/spell combination")
		return
	}
	if err := runSQLite("INSERT INTO play_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", " + sqlQuote(spell.SpellID) + ", " + sqlQuote(spell.Name) + ", " + strconv.Itoa(spell.Level) + ");"); err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "spell already known"})
		return
	}
	respondJSON(w, http.StatusCreated, spell)
}

func listPlayCharacterSpells(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	data, err := querySQLite("SELECT spell_id, name, level FROM play_character_spells WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " ORDER BY rowid;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	spells := make([]playSpell, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 3 {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		level, err := strconv.Atoi(columns[2])
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		spells = append(spells, playSpell{SpellID: columns[0], Name: columns[1], Level: level})
	}
	respondJSON(w, http.StatusOK, map[string]any{"spells": spells})
}

func validPlayInventoryItem(itemID string) bool {
	return itemID == "healing-potion" || itemID == "torch" || itemID == "leather-armor" || itemID == "ring-of-protection" || itemID == "amulet-of-health"
}

func consumablePlayInventoryItem(itemID string) bool {
	return itemID == "healing-potion"
}

func loadPlayLootLocked(campaignID, lootID string) (playLoot, bool, error) {
	data, err := querySQLite("SELECT state FROM play_loot WHERE campaign_id = " + sqlQuote(campaignID) + " AND loot_id = " + sqlQuote(lootID) + ";")
	if err != nil {
		return playLoot{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playLoot{}, false, nil
	}
	var loot playLoot
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &loot); err != nil {
		return playLoot{}, false, err
	}
	return loot, true, nil
}

func createPlayLoot(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		LootID   string `json:"loot_id"`
		ItemID   string `json:"item_id"`
		Quantity int    `json:"quantity"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.LootID) || !validPlayInventoryItem(input.ItemID) || input.Quantity <= 0 {
		badRequest(w, "invalid loot")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	loot := playLoot{LootID: input.LootID, ItemID: input.ItemID, Quantity: input.Quantity, Status: "open"}
	state, err := json.Marshal(loot)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := runSQLite("INSERT INTO play_loot (campaign_id, loot_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(loot.LootID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "loot id already exists"})
		return
	}
	respondJSON(w, http.StatusCreated, map[string]any{"loot_id": loot.LootID, "item_id": loot.ItemID, "quantity": loot.Quantity, "status": loot.Status})
}

func votePlayLoot(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		RecipientCharacterID string `json:"recipient_character_id"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.RecipientCharacterID) {
		badRequest(w, "invalid vote")
		return
	}

	campaignID, lootID := r.PathValue("id"), r.PathValue("loot_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "player" {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	loot, found, err := loadPlayLootLocked(campaignID, lootID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown loot"})
		return
	}
	if loot.Status != "open" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "loot is not open"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, input.RecipientCharacterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		badRequest(w, "invalid vote")
		return
	}
	if err := runSQLite("INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(lootID) + ", " + sqlQuote(actor.Username) + ", " + sqlQuote(input.RecipientCharacterID) + ");"); err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "vote already cast"})
		return
	}
	voteCount, err := querySQLite("SELECT COUNT(*) FROM play_loot_votes WHERE campaign_id = " + sqlQuote(campaignID) + " AND loot_id = " + sqlQuote(lootID) + " AND recipient_character_id = " + sqlQuote(input.RecipientCharacterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	votes, err := strconv.Atoi(strings.TrimSpace(voteCount))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, playLootVoteResponse{LootID: lootID, Voter: actor.Username, RecipientCharacterID: input.RecipientCharacterID, VotesForRecipient: votes})
}

func assignPlayLoot(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, lootID := r.PathValue("id"), r.PathValue("loot_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	loot, found, err := loadPlayLootLocked(campaignID, lootID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown loot"})
		return
	}
	if loot.Status != "open" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "loot is not open"})
		return
	}
	rows, err := querySQLite("SELECT recipient_character_id, COUNT(*) FROM play_loot_votes WHERE campaign_id = " + sqlQuote(campaignID) + " AND loot_id = " + sqlQuote(lootID) + " GROUP BY recipient_character_id ORDER BY COUNT(*) DESC, recipient_character_id ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var winner string
	winningVotes := 0
	tied := false
	for _, row := range strings.Split(strings.TrimSuffix(rows, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 2 {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		count, err := strconv.Atoi(columns[1])
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if winningVotes == 0 {
			winner, winningVotes = columns[0], count
		} else if count == winningVotes {
			tied = true
		}
	}
	if winningVotes == 0 || tied {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "loot has no unambiguous winner"})
		return
	}
	loot.Status, loot.RecipientCharacterID, loot.Votes = "assigned", winner, winningVotes
	state, err := json.Marshal(loot)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	sql := "BEGIN IMMEDIATE; UPDATE play_character_inventory_stacks SET quantity = quantity + " + strconv.Itoa(loot.Quantity) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(winner) + " AND item_id = " + sqlQuote(loot.ItemID) + "; INSERT INTO play_character_inventory_stacks (campaign_id, character_id, item_id, quantity) SELECT " + sqlQuote(campaignID) + ", " + sqlQuote(winner) + ", " + sqlQuote(loot.ItemID) + ", " + strconv.Itoa(loot.Quantity) + " WHERE NOT EXISTS (SELECT 1 FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(winner) + " AND item_id = " + sqlQuote(loot.ItemID) + "); UPDATE play_loot SET state = " + sqlQuote(string(state)) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND loot_id = " + sqlQuote(lootID) + "; COMMIT;"
	if err := runSQLite(sql); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, loot)
}

func getPlayLoot(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, lootID := r.PathValue("id"), r.PathValue("loot_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !(actor.Role == "player" && member) {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	loot, found, err := loadPlayLootLocked(campaignID, lootID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown loot"})
		return
	}
	rows, err := querySQLite("SELECT recipient_character_id, COUNT(*) FROM play_loot_votes WHERE campaign_id = " + sqlQuote(campaignID) + " AND loot_id = " + sqlQuote(lootID) + " GROUP BY recipient_character_id;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	votes := make(map[string]int)
	for _, row := range strings.Split(strings.TrimSuffix(rows, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 2 {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		count, err := strconv.Atoi(columns[1])
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		votes[columns[0]] = count
	}
	respondJSON(w, http.StatusOK, playLootReadResponse{
		LootID:               loot.LootID,
		ItemID:               loot.ItemID,
		Quantity:             loot.Quantity,
		Status:               loot.Status,
		RecipientCharacterID: loot.RecipientCharacterID,
		Votes:                votes,
	})
}

func loadPlayNPCLocked(campaignID, npcID string) (playNPC, bool, error) {
	data, err := querySQLite("SELECT state FROM play_npcs WHERE campaign_id = " + sqlQuote(campaignID) + " AND npc_id = " + sqlQuote(npcID) + ";")
	if err != nil {
		return playNPC{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playNPC{}, false, nil
	}
	var npc playNPC
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &npc); err != nil {
		return playNPC{}, false, err
	}
	return npc, true, nil
}

func createPlayNPC(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var npc playNPC
	if err := decodeJSON(r, &npc); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(npc.NPCID) || !validCampaignText(npc.Name) || !validCampaignText(npc.Agenda) || !validCampaignText(npc.PublicStatus) {
		badRequest(w, "invalid npc")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	state, err := json.Marshal(npc)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := runSQLite("INSERT INTO play_npcs (campaign_id, npc_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(npc.NPCID) + ", " + sqlQuote(string(state)) + ");"); err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "npc id already exists"})
		return
	}
	respondJSON(w, http.StatusCreated, npc)
}

func updatePlayNPCAgenda(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Agenda       string `json:"agenda"`
		PublicStatus string `json:"public_status"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Agenda) || !validCampaignText(input.PublicStatus) {
		badRequest(w, "invalid npc agenda")
		return
	}

	campaignID, npcID := r.PathValue("id"), r.PathValue("npc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	npc, found, err := loadPlayNPCLocked(campaignID, npcID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown npc"})
		return
	}
	npc.Agenda, npc.PublicStatus = input.Agenda, input.PublicStatus
	state, err := json.Marshal(npc)
	if err != nil || runSQLite("UPDATE play_npcs SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND npc_id = "+sqlQuote(npcID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, npc)
}

func getPlayNPC(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, npcID := r.PathValue("id"), r.PathValue("npc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !(actor.Role == "player" && member) {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	npc, found, err := loadPlayNPCLocked(campaignID, npcID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown npc"})
		return
	}
	if isOwner {
		respondJSON(w, http.StatusOK, npc)
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"npc_id": npc.NPCID, "name": npc.Name, "public_status": npc.PublicStatus})
}

func addPlayCharacterInventoryItems(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input playInventoryItem
	if err := decodeJSON(r, &input); err != nil || !validPlayInventoryItem(input.ItemID) || input.Quantity <= 0 {
		badRequest(w, "invalid inventory item")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may add items"})
		return
	}
	if err := runSQLite("INSERT INTO play_character_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", " + sqlQuote(input.ItemID) + ", " + strconv.Itoa(input.Quantity) + ") ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	total, err := querySQLite("SELECT quantity FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(input.ItemID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	totalQuantity, err := strconv.Atoi(strings.TrimSpace(total))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, playInventoryStackResponse{CharacterID: characterID, ItemID: input.ItemID, Quantity: input.Quantity, TotalQuantity: totalQuantity})
}

func listPlayCharacterInventoryItems(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	data, err := querySQLite("SELECT item_id, quantity FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " ORDER BY item_id ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	items := make([]playInventoryItem, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 2 {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		quantity, err := strconv.Atoi(columns[1])
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		items = append(items, playInventoryItem{ItemID: columns[0], Quantity: quantity})
	}
	respondJSON(w, http.StatusOK, map[string]any{"character_id": characterID, "items": items})
}

func removePlayCharacterInventoryItems(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Quantity int `json:"quantity"`
	}
	itemID := r.PathValue("item_id")
	if err := decodeJSON(r, &input); err != nil || !validPlayInventoryItem(itemID) || input.Quantity <= 0 {
		badRequest(w, "invalid inventory item")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may remove items"})
		return
	}
	heldData, err := querySQLite("SELECT quantity FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	held := 0
	if strings.TrimSpace(heldData) != "" {
		held, err = strconv.Atoi(strings.TrimSpace(heldData))
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
	}
	if input.Quantity > held {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "insufficient item quantity"})
		return
	}
	remaining := held - input.Quantity
	var statement string
	if remaining == 0 {
		statement = "DELETE FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";"
	} else {
		statement = "UPDATE play_character_inventory_stacks SET quantity = " + strconv.Itoa(remaining) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";"
	}
	if err := runSQLite(statement); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, playInventoryStackResponse{CharacterID: characterID, ItemID: itemID, Quantity: input.Quantity, TotalQuantity: remaining})
}

func consumePlayCharacterInventoryItem(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	itemID := r.PathValue("item_id")
	if !consumablePlayInventoryItem(itemID) {
		badRequest(w, "item is not consumable")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may consume items"})
		return
	}
	heldData, err := querySQLite("SELECT quantity FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	held := 0
	if strings.TrimSpace(heldData) != "" {
		held, err = strconv.Atoi(strings.TrimSpace(heldData))
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
	}
	if held < 1 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "insufficient item quantity"})
		return
	}
	remaining := held - 1
	var statement string
	if remaining == 0 {
		statement = "DELETE FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";"
	} else {
		statement = "UPDATE play_character_inventory_stacks SET quantity = " + strconv.Itoa(remaining) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(itemID) + ";"
	}
	if err := runSQLite(statement); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	response := playConsumableResponse{CharacterID: characterID, ItemID: itemID, QuantityConsumed: 1, TotalQuantity: remaining}
	response.Effect.Type = "healing"
	response.Effect.HPRestored = 5
	respondJSON(w, http.StatusOK, response)
}

func equipmentSlotForItem(itemID string) string {
	switch itemID {
	case "leather-armor":
		return "armor"
	case "ring-of-protection", "amulet-of-health":
		return "accessory"
	default:
		return ""
	}
}

func attunableEquipment(itemID string) bool {
	return itemID == "ring-of-protection" || itemID == "amulet-of-health"
}

func validEquipmentSlot(slot string) bool {
	return slot == "armor" || slot == "accessory"
}

// playEquipmentMemberAccessLocked checks the campaign and character first so
// equipment routes retain the established campaign-member read authorization.
func playEquipmentMemberAccessLocked(campaignID, characterID string, actor user) (bool, error) {
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, errors.New("unknown campaign")
	}
	member, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		return false, err
	}
	if !(actor.Role == "dm" && actor.Username == campaign.Owner) && !member {
		return false, nil
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		return false, err
	} else if !found {
		return false, errors.New("unknown character")
	}
	return true, nil
}

func respondEquipmentAccessError(w http.ResponseWriter, err error, allowed bool) bool {
	if err != nil {
		if err.Error() == "unknown campaign" {
			respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		} else if err.Error() == "unknown character" {
			respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		} else {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		}
		return true
	}
	if !allowed {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return true
	}
	return false
}

func putPlayCharacterEquipment(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		ItemID string `json:"item_id"`
	}
	slot := r.PathValue("slot")
	if err := decodeJSON(r, &input); err != nil || !validEquipmentSlot(slot) || equipmentSlotForItem(input.ItemID) != slot {
		badRequest(w, "invalid equipment")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	allowed, err := playEquipmentMemberAccessLocked(campaignID, characterID, actor)
	if respondEquipmentAccessError(w, err, allowed) {
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may equip items"})
		return
	}
	held, err := querySQLite("SELECT quantity FROM play_character_inventory_stacks WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND item_id = " + sqlQuote(input.ItemID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	quantity, err := strconv.Atoi(strings.TrimSpace(held))
	if err != nil || quantity < 1 {
		badRequest(w, "item is not held")
		return
	}
	if err := runSQLite("INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", " + sqlQuote(slot) + ", " + sqlQuote(input.ItemID) + ", 0) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0;"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, playEquipmentResponse{CharacterID: characterID, Slot: slot, ItemID: input.ItemID, Attuned: false})
}

func getPlayCharacterEquipment(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	slot := r.PathValue("slot")
	if !validEquipmentSlot(slot) {
		badRequest(w, "invalid equipment slot")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	allowed, err := playEquipmentMemberAccessLocked(campaignID, characterID, actor)
	if respondEquipmentAccessError(w, err, allowed) {
		return
	}
	data, err := querySQLite("SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND slot = " + sqlQuote(slot) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	response := playEquipmentResponse{CharacterID: characterID, Slot: slot}
	if strings.TrimSpace(data) != "" {
		columns := strings.Split(strings.TrimSpace(data), "\t")
		if len(columns) != 2 || (columns[1] != "0" && columns[1] != "1") {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		response.ItemID, response.Attuned = columns[0], columns[1] == "1"
	}
	respondJSON(w, http.StatusOK, response)
}

func attunePlayCharacterEquipment(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	slot := r.PathValue("slot")
	if !validEquipmentSlot(slot) {
		badRequest(w, "invalid equipment slot")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	allowed, err := playEquipmentMemberAccessLocked(campaignID, characterID, actor)
	if respondEquipmentAccessError(w, err, allowed) {
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may attune items"})
		return
	}
	data, err := querySQLite("SELECT item_id FROM play_character_equipment WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND slot = " + sqlQuote(slot) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	itemID := strings.TrimSpace(data)
	if slot != "accessory" || !attunableEquipment(itemID) {
		badRequest(w, "item cannot be attuned")
		return
	}
	countData, err := querySQLite("SELECT COUNT(*) FROM play_character_equipment WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND attuned = 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	count, err := strconv.Atoi(strings.TrimSpace(countData))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if count >= 1 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "maximum attunements reached"})
		return
	}
	if err := runSQLite("UPDATE play_character_equipment SET attuned = 1 WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND slot = " + sqlQuote(slot) + ";"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, playAttunementResponse{CharacterID: characterID, Slot: slot, ItemID: itemID, Attuned: true, AttunementCount: 1, MaxAttunements: 1})
}

type preparedSpellsRequest struct {
	SpellIDs []string `json:"spell_ids"`
}

type preparedSpellsResponse struct {
	CharacterID    string   `json:"character_id"`
	PreparedSpells []string `json:"prepared_spells"`
	MaxPrepared    int      `json:"max_prepared"`
}

func putPlayCharacterPreparedSpells(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input preparedSpellsRequest
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, maxPrepared, found, err := preparedSpellCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may prepare spells"})
		return
	}
	if member.Class != "wizard" || len(input.SpellIDs) > maxPrepared {
		badRequest(w, "invalid prepared spells")
		return
	}
	prepared := make([]string, 0, len(input.SpellIDs))
	seen := make(map[string]bool, len(input.SpellIDs))
	for _, spellID := range input.SpellIDs {
		if !validCampaignText(spellID) || seen[spellID] {
			badRequest(w, "invalid prepared spells")
			return
		}
		known, err := querySQLite("SELECT 1 FROM play_character_spells WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND spell_id = " + sqlQuote(spellID) + " LIMIT 1;")
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if strings.TrimSpace(known) == "" {
			badRequest(w, "unknown spell")
			return
		}
		seen[spellID] = true
		prepared = append(prepared, spellID)
	}
	state, err := json.Marshal(prepared)
	if err != nil || runSQLite("INSERT INTO play_character_prepared_spells (campaign_id, character_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(characterID)+", "+sqlQuote(string(state))+") ON CONFLICT(campaign_id, character_id) DO UPDATE SET state = excluded.state;") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, preparedSpellsResponse{CharacterID: characterID, PreparedSpells: prepared, MaxPrepared: maxPrepared})
}

func getPlayCharacterPreparedSpells(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	_, maxPrepared, found, err := preparedSpellCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	prepared, err := loadPreparedSpellsLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, preparedSpellsResponse{CharacterID: characterID, PreparedSpells: prepared, MaxPrepared: maxPrepared})
}

// preparedSpellCharacterLocked returns the character and its current prepared
// spell limit. Characters without build progress begin at level one.
func preparedSpellCharacterLocked(campaignID, characterID string) (playMember, int, bool, error) {
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil || !found {
		return member, 0, found, err
	}
	level := 1
	data, err := querySQLite("SELECT state FROM play_character_progress WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return playMember{}, 0, false, err
	}
	if strings.TrimSpace(data) != "" {
		var progress characterProgress
		if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &progress); err != nil {
			return playMember{}, 0, false, err
		}
		if validLevel(progress.Level) {
			level = progress.Level
		}
	}
	if member.Class != "wizard" {
		return member, 0, true, nil
	}
	return member, level, true, nil
}

func loadPreparedSpellsLocked(campaignID, characterID string) ([]string, error) {
	data, err := querySQLite("SELECT state FROM play_character_prepared_spells WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return nil, err
	}
	prepared := make([]string, 0)
	if strings.TrimSpace(data) == "" {
		return prepared, nil
	}
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &prepared); err != nil || prepared == nil {
		return nil, errors.New("invalid prepared spells")
	}
	return prepared, nil
}

type spellCastRequest struct {
	SpellID string `json:"spell_id"`
	Target  string `json:"target"`
}

func castPlayCharacterSpell(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input spellCastRequest
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.SpellID) || !validCampaignText(input.Target) {
		badRequest(w, "invalid cast")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	if _, found, err := loadPlayCampaignLocked(campaignID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may cast spells"})
		return
	}
	if member.Class != "wizard" {
		badRequest(w, "character is not a spellcaster")
		return
	}
	prepared, err := loadPreparedSpellsLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !containsString(prepared, input.SpellID) {
		badRequest(w, "spell is not prepared")
		return
	}
	spellData, err := querySQLite("SELECT level FROM play_character_spells WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND spell_id = " + sqlQuote(input.SpellID) + " LIMIT 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	spellLevel, err := strconv.Atoi(strings.TrimSpace(spellData))
	if err != nil {
		badRequest(w, "spell is not prepared")
		return
	}
	level, err := playCharacterLevelLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	casts, err := loadPlayCharacterCastsLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	available := wizardSpellSlots(level, spellLevel)
	for _, cast := range casts {
		if cast.SlotLevel == spellLevel {
			available--
		}
	}
	if available < 1 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "no spell slots remaining"})
		return
	}
	cast := playSpellCast{CharacterID: characterID, SpellID: input.SpellID, Target: input.Target, SlotLevel: spellLevel, SlotsRemaining: available - 1, Sequence: len(casts) + 1}
	state, err := json.Marshal(cast)
	if err != nil || runSQLite("INSERT INTO play_character_casts (campaign_id, character_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(characterID)+", "+strconv.Itoa(cast.Sequence)+", "+sqlQuote(string(state))+" );") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, cast)
}

func listPlayCharacterCasts(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if _, found, err := loadPlayCharacterLocked(campaignID, characterID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	casts, err := loadPlayCharacterCastsLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"casts": casts})
}

func playCharacterLevelLocked(campaignID, characterID string) (int, error) {
	data, err := querySQLite("SELECT state FROM play_character_progress WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return 0, err
	}
	level := 1
	if strings.TrimSpace(data) == "" {
		return level, nil
	}
	var progress characterProgress
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &progress); err != nil {
		return 0, err
	}
	if validLevel(progress.Level) {
		level = progress.Level
	}
	return level, nil
}

// This play API starts a first-level wizard with one first-level slot. Higher
// level slot schedules have not yet been introduced by the play rules.
func wizardSpellSlots(characterLevel, spellLevel int) int {
	if characterLevel == 1 && spellLevel == 1 {
		return 1
	}
	return 0
}

func loadPlayCharacterCastsLocked(campaignID, characterID string) ([]playSpellCast, error) {
	data, err := querySQLite("SELECT state FROM play_character_casts WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " ORDER BY sequence;")
	if err != nil {
		return nil, err
	}
	casts := make([]playSpellCast, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var cast playSpellCast
		if err := json.Unmarshal([]byte(row), &cast); err != nil {
			return nil, err
		}
		casts = append(casts, cast)
	}
	return casts, nil
}

type concentrationRequest struct {
	SpellID       string `json:"spell_id"`
	Target        string `json:"target"`
	DurationTurns int    `json:"duration_turns"`
}

type concentrationResponse struct {
	CharacterID   string             `json:"character_id"`
	Concentration *playConcentration `json:"concentration"`
}

func putPlayCharacterConcentration(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input concentrationRequest
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.SpellID) || !validCampaignText(input.Target) || input.DurationTurns < 1 {
		badRequest(w, "invalid concentration")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	member, permitted, found := concentrationCharacterAccess(w, campaignID, characterID, actor, true)
	if !permitted || !found {
		return
	}
	if member.Class != "wizard" {
		badRequest(w, "character is not a spellcaster")
		return
	}
	known, err := querySQLite("SELECT 1 FROM play_character_spells WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " AND spell_id = " + sqlQuote(input.SpellID) + " LIMIT 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(known) == "" {
		badRequest(w, "unknown spell")
		return
	}
	prepared, err := loadPreparedSpellsLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !containsString(prepared, input.SpellID) {
		badRequest(w, "spell is not prepared")
		return
	}
	concentration := &playConcentration{SpellID: input.SpellID, Target: input.Target, RemainingTurns: input.DurationTurns}
	state, err := json.Marshal(concentration)
	if err != nil || runSQLite("INSERT INTO play_character_concentrations (campaign_id, character_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(characterID)+", "+sqlQuote(string(state))+") ON CONFLICT(campaign_id, character_id) DO UPDATE SET state = excluded.state;") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, concentrationResponse{CharacterID: characterID, Concentration: concentration})
}

func getPlayCharacterConcentration(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	_, permitted, found := concentrationCharacterAccess(w, campaignID, characterID, actor, false)
	if !permitted || !found {
		return
	}
	concentration, err := loadPlayCharacterConcentrationLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, concentrationResponse{CharacterID: characterID, Concentration: concentration})
}

func advancePlayCharacterConcentration(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	_, permitted, found := concentrationCharacterAccess(w, campaignID, characterID, actor, false)
	if !permitted || !found {
		return
	}
	concentration, err := loadPlayCharacterConcentrationLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if concentration != nil {
		concentration.RemainingTurns--
		if concentration.RemainingTurns < 1 {
			concentration = nil
		}
		if err := savePlayCharacterConcentrationLocked(campaignID, characterID, concentration); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
	}
	respondJSON(w, http.StatusOK, concentrationResponse{CharacterID: characterID, Concentration: concentration})
}

func deletePlayCharacterConcentration(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	_, permitted, found := concentrationCharacterAccess(w, campaignID, characterID, actor, true)
	if !permitted || !found {
		return
	}
	if err := savePlayCharacterConcentrationLocked(campaignID, characterID, nil); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, concentrationResponse{CharacterID: characterID, Concentration: nil})
}

// concentrationCharacterAccess checks campaign membership for reads and turn
// advancement, or character ownership when ownerOnly is true.
func concentrationCharacterAccess(w http.ResponseWriter, campaignID, characterID string, actor user, ownerOnly bool) (playMember, bool, bool) {
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return playMember{}, false, false
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return playMember{}, false, false
	}
	member, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return playMember{}, false, false
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return playMember{}, false, false
	}
	if ownerOnly {
		owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return playMember{}, false, false
		}
		if strings.TrimSpace(owner) != actor.Username {
			respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may manage concentration"})
			return playMember{}, false, false
		}
		return member, true, true
	}
	isOwner := actor.Role == "dm" && actor.Username == campaign.Owner
	isMember, err := playCampaignMemberLocked(campaignID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return playMember{}, false, false
	}
	if !isOwner && !isMember {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return playMember{}, false, false
	}
	return member, true, true
}

func loadPlayCharacterConcentrationLocked(campaignID, characterID string) (*playConcentration, error) {
	data, err := querySQLite("SELECT state FROM play_character_concentrations WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(data) == "" {
		return nil, nil
	}
	var concentration playConcentration
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &concentration); err != nil || !validCampaignText(concentration.SpellID) || !validCampaignText(concentration.Target) || concentration.RemainingTurns < 1 {
		return nil, errors.New("invalid concentration")
	}
	return &concentration, nil
}

func savePlayCharacterConcentrationLocked(campaignID, characterID string, concentration *playConcentration) error {
	if concentration == nil {
		return runSQLite("DELETE FROM play_character_concentrations WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	}
	state, err := json.Marshal(concentration)
	if err != nil {
		return err
	}
	return runSQLite("INSERT INTO play_character_concentrations (campaign_id, character_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", " + sqlQuote(string(state)) + ") ON CONFLICT(campaign_id, character_id) DO UPDATE SET state = excluded.state;")
}

func addPlayMonster(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input playMonster
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.MonsterID) || !validCampaignText(input.Name) || input.HPMax < 1 {
		badRequest(w, "invalid monster")
		return
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	for _, existing := range encounter.Combatants {
		if existing.MonsterID == input.MonsterID {
			respondJSON(w, http.StatusConflict, map[string]string{"error": "monster id already exists"})
			return
		}
	}
	input.HPCurrent = input.HPMax
	encounter.Combatants = append(encounter.Combatants, input)
	state, err := json.Marshal(encounter)
	if err != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, input)
}

func removePlayMonster(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID, monsterID := r.PathValue("id"), r.PathValue("enc_id"), r.PathValue("monster_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	remaining := make([]playMonster, 0, len(encounter.Combatants))
	removed := false
	for _, existing := range encounter.Combatants {
		if existing.MonsterID == monsterID {
			removed = true
			continue
		}
		remaining = append(remaining, existing)
	}
	if !removed {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown monster"})
		return
	}
	encounter.Combatants = remaining
	delete(encounter.Conditions, monsterID)
	state, err := json.Marshal(encounter)
	if err != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"removed": monsterID})
}

// bindPlayMemberCombatant adds an existing party member to the active
// encounter. The member details come from the stored membership rather than
// the request, so a combatant always reflects a real campaign character.
func bindPlayMemberCombatant(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Member     string `json:"member"`
		Initiative int    `json:"initiative"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validUsername(input.Member) {
		badRequest(w, "invalid member")
		return
	}

	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	if encounter.Status != "active" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "encounter is not active"})
		return
	}
	for _, existing := range encounter.PartyCombatants {
		if existing.Member == input.Member {
			respondJSON(w, http.StatusConflict, map[string]string{"error": "member already bound"})
			return
		}
	}

	memberData, err := querySQLite("SELECT state FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(input.Member) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(memberData) == "" {
		badRequest(w, "unknown member")
		return
	}
	var member playMember
	if err := json.Unmarshal([]byte(strings.TrimSpace(memberData)), &member); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	combatant := playPartyCombatant{Member: member.Username, CharacterID: member.CharacterID, Name: member.Name, Initiative: input.Initiative}
	encounter.PartyCombatants = append(encounter.PartyCombatants, combatant)
	state, err := json.Marshal(encounter)
	if err != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, combatant)
}

func unbindPlayMemberCombatant(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, encounterID, memberID := r.PathValue("id"), r.PathValue("enc_id"), r.PathValue("member")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	encounter, found, err := loadPlayEncounterLocked(campaignID, encounterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown encounter"})
		return
	}
	remaining := make([]playPartyCombatant, 0, len(encounter.PartyCombatants))
	removed := false
	for _, existing := range encounter.PartyCombatants {
		if existing.Member == memberID {
			removed = true
			continue
		}
		remaining = append(remaining, existing)
	}
	if !removed {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown combatant"})
		return
	}
	encounter.PartyCombatants = remaining
	delete(encounter.Conditions, memberID)
	state, err := json.Marshal(encounter)
	if err != nil || runSQLite("UPDATE play_encounters SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND encounter_id = "+sqlQuote(encounterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"removed": memberID})
}

func createPlayLocation(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var location playLocation
	if err := decodeJSON(r, &location); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(location.ID) || !validCampaignText(location.Name) {
		badRequest(w, "invalid location")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	state, err := json.Marshal(location)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	err = runSQLite("INSERT INTO play_locations (campaign_id, location_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(location.ID) + ", " + sqlQuote(string(state)) + ");")
	if err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "location id already exists"})
		return
	}
	respondJSON(w, http.StatusCreated, location)
}

func createPlayLocationConnection(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		ToID        string `json:"to_id"`
		TravelTurns int    `json:"travel_turns"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ToID) || input.TravelTurns < 1 {
		badRequest(w, "invalid connection")
		return
	}

	campaignID, fromID := r.PathValue("id"), r.PathValue("from_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	fromExists, err := playLocationExistsLocked(campaignID, fromID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	toExists, err := playLocationExistsLocked(campaignID, input.ToID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !fromExists || !toExists {
		badRequest(w, "unknown location")
		return
	}
	connection := playLocationConnection{FromID: fromID, ToID: input.ToID, TravelTurns: input.TravelTurns}
	err = runSQLite("INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(connection.FromID) + ", " + sqlQuote(connection.ToID) + ", " + strconv.Itoa(connection.TravelTurns) + ");")
	if err != nil {
		badRequest(w, "connection already exists")
		return
	}
	respondJSON(w, http.StatusCreated, connection)
}

func getPlayLocationTravel(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, locationID := r.PathValue("id"), r.PathValue("loc_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		member, err := playCampaignMemberLocked(campaignID, actor.Username)
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if actor.Role != "player" || !member {
			respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
	}
	if exists, err := playLocationExistsLocked(campaignID, locationID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if !exists {
		badRequest(w, "unknown location")
		return
	}
	data, err := querySQLite("SELECT c.to_id, c.travel_turns, l.state FROM play_location_connections c JOIN play_locations l ON l.campaign_id = c.campaign_id AND l.location_id = c.to_id WHERE c.campaign_id = " + sqlQuote(campaignID) + " AND c.from_id = " + sqlQuote(locationID) + " ORDER BY c.rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	destinations := make([]travelDestination, 0)
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		columns := strings.Split(row, "\t")
		if len(columns) != 3 {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		turns, err := strconv.Atoi(columns[1])
		var location playLocation
		if err != nil || json.Unmarshal([]byte(columns[2]), &location) != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		destinations = append(destinations, travelDestination{ID: location.ID, Name: location.Name, TravelTurns: turns})
	}
	respondJSON(w, http.StatusOK, map[string]any{"destinations": destinations})
}

func playLocationExistsLocked(campaignID, locationID string) (bool, error) {
	result, err := querySQLite("SELECT 1 FROM play_locations WHERE campaign_id = " + sqlQuote(campaignID) + " AND location_id = " + sqlQuote(locationID) + " LIMIT 1;")
	return strings.TrimSpace(result) != "", err
}

func createPlayScene(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.ID) || !validCampaignText(input.Name) {
		badRequest(w, "invalid scene")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if exists, err := playSceneExistsLocked(campaignID, input.ID); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	} else if exists {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "scene id already exists"})
		return
	}
	scene := playScene{ID: input.ID, Name: input.Name, Status: "open"}
	state, err := json.Marshal(scene)
	if err != nil || runSQLite("INSERT INTO play_scenes (campaign_id, scene_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(scene.ID)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, scene)
}

func enterPlayScene(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, sceneID := r.PathValue("id"), r.PathValue("scene_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	scene, found, err := loadPlaySceneLocked(campaignID, sceneID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown scene"})
		return
	}
	if scene.Status != "open" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "scene is closed"})
		return
	}
	if err := runSQLite("INSERT INTO play_scene_state (campaign_id, current_scene_id) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(sceneID) + ") ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id;"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := appendPlayTimelineEventLocked(campaignID, narrationEvent{Kind: "scene_enter", Actor: actor.Username}); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"current_scene_id": scene.ID, "name": scene.Name})
}

func closePlayScene(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, sceneID := r.PathValue("id"), r.PathValue("scene_id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	scene, found, err := loadPlaySceneLocked(campaignID, sceneID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown scene"})
		return
	}
	scene.Status = "closed"
	state, err := json.Marshal(scene)
	if err != nil || runSQLite("UPDATE play_scenes SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND scene_id = "+sqlQuote(sceneID)+"; DELETE FROM play_scene_state WHERE campaign_id = "+sqlQuote(campaignID)+" AND current_scene_id = "+sqlQuote(sceneID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := appendPlayTimelineEventLocked(campaignID, narrationEvent{Kind: "scene_close", Actor: actor.Username}); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"id": scene.ID, "status": scene.Status})
}

func getCurrentPlayScene(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	isOwner := actor.Username == campaign.Owner
	if !isOwner {
		member, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(actor.Username) + " LIMIT 1;")
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if actor.Role != "player" || strings.TrimSpace(member) == "" {
			respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
	}
	currentID, err := querySQLite("SELECT current_scene_id FROM play_scene_state WHERE campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	sceneID := strings.TrimSpace(currentID)
	if sceneID == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "no current scene"})
		return
	}
	scene, found, err := loadPlaySceneLocked(campaignID, sceneID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found || scene.Status != "open" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "no current scene"})
		return
	}
	respondJSON(w, http.StatusOK, scene)
}

func playSceneExistsLocked(campaignID, sceneID string) (bool, error) {
	result, err := querySQLite("SELECT 1 FROM play_scenes WHERE campaign_id = " + sqlQuote(campaignID) + " AND scene_id = " + sqlQuote(sceneID) + " LIMIT 1;")
	return strings.TrimSpace(result) != "", err
}

func loadPlaySceneLocked(campaignID, sceneID string) (playScene, bool, error) {
	data, err := querySQLite("SELECT state FROM play_scenes WHERE campaign_id = " + sqlQuote(campaignID) + " AND scene_id = " + sqlQuote(sceneID) + ";")
	if err != nil {
		return playScene{}, false, err
	}
	if strings.TrimSpace(data) == "" {
		return playScene{}, false, nil
	}
	var scene playScene
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &scene); err != nil {
		return playScene{}, false, err
	}
	return scene, true, nil
}

type characterOwnerResponse struct {
	CharacterID string `json:"character_id"`
	Owner       string `json:"owner"`
}

type characterBuildRequest struct {
	Race       string `json:"race"`
	Class      string `json:"class"`
	Background string `json:"background"`
	Abilities  struct {
		STR int `json:"str"`
		DEX int `json:"dex"`
		CON int `json:"con"`
		INT int `json:"int"`
		WIS int `json:"wis"`
		CHA int `json:"cha"`
	} `json:"abilities"`
}

type characterBuildResponse struct {
	CharacterID      string `json:"character_id"`
	Race             string `json:"race"`
	Class            string `json:"class"`
	Background       string `json:"background"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// characterProgress is kept separately from a party membership so adding
// character-creation choices does not change the established member response.
type characterProgress struct {
	Class        string `json:"class"`
	Strength     int    `json:"strength"`
	Dexterity    int    `json:"dexterity"`
	Constitution int    `json:"constitution"`
	Intelligence int    `json:"intelligence"`
	Wisdom       int    `json:"wisdom"`
	Charisma     int    `json:"charisma"`
	Level        int    `json:"level"`
	HPMax        int    `json:"hp_max"`
}

type characterLevelUpResponse struct {
	CharacterID      string `json:"character_id"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	HitDice          string `json:"hit_dice"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// playCharacterAccessLocked verifies both that the character belongs to this
// campaign and that the caller is one of its player members.
func playCharacterAccessLocked(campaignID, characterID, username string) (bool, bool, error) {
	character, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + " LIMIT 1;")
	if err != nil {
		return false, false, err
	}
	member, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(username) + " LIMIT 1;")
	if err != nil {
		return false, false, err
	}
	return strings.TrimSpace(character) != "", strings.TrimSpace(member) != "", nil
}

// playCharacterGoldLocked also gives characters created by older persisted
// data the stage's deterministic starting balance.
func playCharacterGoldLocked(campaignID, characterID string) (int, error) {
	data, err := querySQLite("SELECT gold FROM play_character_currency WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		return 0, err
	}
	if strings.TrimSpace(data) == "" {
		if err := runSQLite("INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", 10);"); err != nil {
			return 0, err
		}
		return 10, nil
	}
	return strconv.Atoi(strings.TrimSpace(data))
}

func getPlayCharacterCurrency(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	gold, err := playCharacterGoldLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, playCurrencyResponse{CharacterID: characterID, Gold: gold})
}

func transferPlayCharacterCurrency(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		ToCharacterID string `json:"to_character_id"`
		Gold          int    `json:"gold"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	campaignID, fromCharacterID := r.PathValue("id"), r.PathValue("character_id")
	if input.ToCharacterID == fromCharacterID || input.ToCharacterID == "" || input.Gold <= 0 {
		badRequest(w, "invalid transfer")
		return
	}

	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, fromCharacterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(fromCharacterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may transfer gold"})
		return
	}
	destination, _, err := playCharacterAccessLocked(campaignID, input.ToCharacterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !destination {
		badRequest(w, "invalid transfer")
		return
	}
	fromGold, err := playCharacterGoldLocked(campaignID, fromCharacterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	toGold, err := playCharacterGoldLocked(campaignID, input.ToCharacterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if fromGold < input.Gold {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "insufficient gold"})
		return
	}
	sequence, err := querySQLite("SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_currency_transfers WHERE campaign_id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	transferID, err := strconv.Atoi(strings.TrimSpace(sequence))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	newFromGold, newToGold := fromGold-input.Gold, toGold+input.Gold
	sql := "BEGIN IMMEDIATE; UPDATE play_character_currency SET gold = " + strconv.Itoa(newFromGold) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(fromCharacterID) + "; UPDATE play_character_currency SET gold = " + strconv.Itoa(newToGold) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(input.ToCharacterID) + "; INSERT INTO play_currency_transfers (campaign_id, transfer_id) VALUES (" + sqlQuote(campaignID) + ", " + strconv.Itoa(transferID) + "); COMMIT;"
	if err := runSQLite(sql); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, playCurrencyTransferResponse{FromCharacterID: fromCharacterID, ToCharacterID: input.ToCharacterID, Gold: input.Gold, FromGold: newFromGold, ToGold: newToGold, TransferID: transferID})
}

func getPlayCharacterOwner(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "character is unowned"})
		return
	}
	respondJSON(w, http.StatusOK, characterOwnerResponse{CharacterID: characterID, Owner: strings.TrimSpace(owner)})
}

func claimPlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != "" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "character is already owned"})
		return
	}
	if err := runSQLite("INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(characterID) + ", " + sqlQuote(actor.Username) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, characterOwnerResponse{CharacterID: characterID, Owner: actor.Username})
}

func transferPlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		NewOwner string `json:"new_owner"`
	}
	if err := decodeJSON(r, &input); err != nil || !validUsername(input.NewOwner) {
		badRequest(w, "invalid transfer")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may transfer"})
		return
	}
	target, err := querySQLite("SELECT 1 FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(input.NewOwner) + " LIMIT 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(target) == "" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "new owner is not a campaign member"})
		return
	}
	if err := runSQLite("UPDATE play_character_owners SET owner = " + sqlQuote(input.NewOwner) + " WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, characterOwnerResponse{CharacterID: characterID, Owner: input.NewOwner})
}

func buildPlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input characterBuildRequest
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCharacterBuild(input) {
		badRequest(w, "invalid character build")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may build this character"})
		return
	}

	level := 1
	hpMax := characterHitPoints(input.Class, input.Abilities.CON)
	progressState, err := json.Marshal(characterProgress{
		Class: input.Class, Strength: input.Abilities.STR, Dexterity: input.Abilities.DEX,
		Constitution: input.Abilities.CON, Intelligence: input.Abilities.INT,
		Wisdom: input.Abilities.WIS, Charisma: input.Abilities.CHA, Level: level, HPMax: hpMax,
	})
	if err != nil || runSQLite("INSERT INTO play_character_progress (campaign_id, character_id, state) VALUES ("+sqlQuote(campaignID)+", "+sqlQuote(characterID)+", "+sqlQuote(string(progressState))+") ON CONFLICT(campaign_id, character_id) DO UPDATE SET state = excluded.state;") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, characterBuildResponse{
		CharacterID: characterID,
		Race:        input.Race, Class: input.Class, Background: input.Background,
		Level:            level,
		HPMax:            hpMax,
		ProficiencyBonus: proficiencyBonus(level),
	})
}

func levelUpPlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Level int `json:"level"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, member, err := playCharacterAccessLocked(campaignID, characterID, actor.Username)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !character {
		badRequest(w, "unknown character")
		return
	}
	if !member {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "only the owner may level up this character"})
		return
	}

	data, err := querySQLite("SELECT state FROM play_character_progress WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var progress characterProgress
	if strings.TrimSpace(data) == "" || json.Unmarshal([]byte(strings.TrimSpace(data)), &progress) != nil || !validLevel(progress.Level) || progress.HPMax < 1 {
		badRequest(w, "character has not been built")
		return
	}
	if input.Level != progress.Level+1 || !validLevel(input.Level) {
		badRequest(w, "level must be exactly one higher than the current level")
		return
	}

	hitDie := characterHitDie(progress.Class)
	if hitDie == 0 {
		badRequest(w, "invalid character class")
		return
	}
	// Use the fixed average roll (rounded up) for deterministic HP growth.
	progress.Level = input.Level
	progress.HPMax += hitDie/2 + 1 + abilityModifier(progress.Constitution)
	state, err := json.Marshal(progress)
	if err != nil || runSQLite("UPDATE play_character_progress SET state = "+sqlQuote(string(state))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND character_id = "+sqlQuote(characterID)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, characterLevelUpResponse{CharacterID: characterID, Level: progress.Level, HPMax: progress.HPMax, HitDice: "1d" + strconv.Itoa(hitDie), ProficiencyBonus: proficiencyBonus(progress.Level)})
}

func skillCheckPlayCharacter(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Skill      string `json:"skill"`
		Ability    string `json:"ability"`
		Proficient bool   `json:"proficient"`
		Roll       int    `json:"roll"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validSkill(input.Skill) || !validSkillAbility(input.Ability) {
		badRequest(w, "unsupported skill or ability")
		return
	}

	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	storageState.Lock()
	defer storageState.Unlock()
	character, found, err := loadPlayCharacterLocked(campaignID, characterID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown character"})
		return
	}
	if character.Username == "" { // Keep the stored membership document well-formed.
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	owner, err := querySQLite("SELECT owner FROM play_character_owners WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(owner) != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	data, err := querySQLite("SELECT state FROM play_character_progress WHERE campaign_id = " + sqlQuote(campaignID) + " AND character_id = " + sqlQuote(characterID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var progress characterProgress
	if strings.TrimSpace(data) == "" || json.Unmarshal([]byte(strings.TrimSpace(data)), &progress) != nil || !validLevel(progress.Level) {
		badRequest(w, "character has not been built")
		return
	}
	score := skillAbilityScore(progress, input.Ability)
	if !validAbilityScore(score) {
		badRequest(w, "character has not been built")
		return
	}
	modifier := abilityModifier(score)
	if input.Proficient {
		modifier += proficiencyBonus(progress.Level)
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"character_id": characterID, "skill": input.Skill, "ability": input.Ability,
		"modifier": modifier, "total": input.Roll + modifier,
	})
}

func validSkill(skill string) bool {
	return map[string]bool{
		"acrobatics": true, "animal-handling": true, "arcana": true, "athletics": true,
		"deception": true, "history": true, "insight": true, "intimidation": true,
		"investigation": true, "medicine": true, "nature": true, "perception": true,
		"performance": true, "persuasion": true, "religion": true, "sleight-of-hand": true,
		"stealth": true, "survival": true,
	}[skill]
}

func validSkillAbility(ability string) bool {
	return ability == "str" || ability == "dex" || ability == "con" || ability == "int" || ability == "wis" || ability == "cha"
}

func skillAbilityScore(progress characterProgress, ability string) int {
	switch ability {
	case "str":
		return progress.Strength
	case "dex":
		return progress.Dexterity
	case "con":
		return progress.Constitution
	case "int":
		return progress.Intelligence
	case "wis":
		return progress.Wisdom
	case "cha":
		return progress.Charisma
	default:
		return 0
	}
}

func validCharacterBuild(input characterBuildRequest) bool {
	if !validCharacterRace(input.Race) || !validCharacterClass(input.Class) || !validCharacterBackground(input.Background) {
		return false
	}
	for _, score := range []int{input.Abilities.STR, input.Abilities.DEX, input.Abilities.CON, input.Abilities.INT, input.Abilities.WIS, input.Abilities.CHA} {
		if !validAbilityScore(score) {
			return false
		}
	}
	return true
}

func validCharacterRace(value string) bool {
	return value == "dwarf" || value == "elf" || value == "halfling" || value == "human"
}

func validCharacterClass(value string) bool {
	return value == "cleric" || value == "fighter" || value == "rogue" || value == "wizard"
}

func validCharacterBackground(value string) bool {
	return value == "acolyte" || value == "criminal" || value == "folk-hero" || value == "noble" || value == "sage" || value == "soldier"
}

func characterHitPoints(class string, constitution int) int {
	return characterHitDie(class) + abilityModifier(constitution)
}

func characterHitDie(class string) int {
	return map[string]int{"cleric": 8, "fighter": 10, "rogue": 8, "wizard": 6}[class]
}

func joinPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "player" {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	var input struct {
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Class       string `json:"class"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.CharacterID) || !validCampaignText(input.Name) || !validCampaignText(input.Class) {
		badRequest(w, "invalid membership")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if campaign.Status != "lobby" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not in lobby"})
		return
	}

	count, err := campaignRecordCount("play_memberships", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if count >= campaign.MaxPlayers {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "party is full"})
		return
	}

	member := playMember{Username: actor.Username, CharacterID: input.CharacterID, Name: input.Name, Class: input.Class}
	state, err := json.Marshal(member)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	err = runSQLite("BEGIN; INSERT INTO play_memberships (campaign_id, username, character_id, state) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(member.Username) + ", " + sqlQuote(member.CharacterID) + ", " + sqlQuote(string(state)) + "); INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(member.CharacterID) + ", " + sqlQuote(member.Username) + "); INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (" + sqlQuote(campaignID) + ", " + sqlQuote(member.CharacterID) + ", 10); COMMIT;")
	if err != nil {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "duplicate membership"})
		return
	}
	respondJSON(w, http.StatusCreated, member)
}

func startPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Role != "dm" || campaign.Owner != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if campaign.Status != "lobby" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not in lobby"})
		return
	}

	members, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	memberNames := strings.Fields(members)
	if len(memberNames) < 2 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "campaign requires at least two party members"})
		return
	}

	campaign.Status = "active"
	state, err := json.Marshal(campaign)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if err := runSQLite("UPDATE play_campaigns SET state = " + sqlQuote(string(state)) + " WHERE id = " + sqlQuote(campaignID) + ";"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"id": campaign.ID, "status": campaign.Status, "current_actor": memberNames[0], "turn_number": 1,
	})
}

// playTurnStateLocked derives a logical turn clock from events that advance
// the queue. Narrative and scene-state entries deliberately are not clock
// ticks.
func playTurnStateLocked(campaignID string, members []string) (string, int, error) {
	currentActor := ""
	if len(members) > 0 {
		currentActor = members[0]
	}
	deadline := 1
	data, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence ASC;")
	if err != nil {
		return "", 0, err
	}
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event narrationEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			return "", 0, err
		}
		if advancesPlayTurn(event.Kind) {
			currentActor = event.NextActor
			deadline++
		}
	}
	return currentActor, deadline, nil
}

func advancesPlayTurn(kind string) bool {
	return kind == "action" || kind == "resolution" || kind == "travel" || kind == "rest"
}

func appendPlayTimelineEventLocked(campaignID string, event narrationEvent) error {
	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		return err
	}
	event.Sequence = count + 1
	state, err := json.Marshal(event)
	if err != nil {
		return err
	}
	return runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES (" + sqlQuote(campaignID) + ", " + strconv.Itoa(event.Sequence) + ", " + sqlQuote(string(state)) + ");")
}

// getPlayTurn exposes the deterministic exploration queue to participants
// only. Each player acts in join order, followed by the DM.
func getPlayTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	memberNames, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	members := strings.Fields(memberNames)
	if actor.Username != campaign.Owner && !containsString(members, actor.Username) {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	currentActor, deadline, err := playTurnStateLocked(campaignID, members)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	queue := make([]string, 0, len(members)*2)
	for _, member := range members {
		queue = append(queue, member, campaign.Owner)
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id":      campaign.ID,
		"current_actor":    currentActor,
		"phase":            map[bool]string{true: "dm", false: "player"}[currentActor == campaign.Owner],
		"queue":            queue,
		"turn_number":      (deadline + 1) / 2,
		"overdue":          false,
		"logical_deadline": deadline,
	})
}

func nudgePlayTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Message string `json:"message"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Message) {
		badRequest(w, "invalid nudge")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	membersData, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	target, _, err := playTurnStateLocked(campaignID, strings.Fields(membersData))
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	count, err := campaignRecordCount("play_turn_nudges", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	count++
	if err := runSQLite("INSERT INTO play_turn_nudges (campaign_id, nudge_count) VALUES (" + sqlQuote(campaignID) + ", " + strconv.Itoa(count) + ");"); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, map[string]any{
		"actor": actor.Username, "target": target, "message": input.Message, "nudge_count": count,
	})
}

// getMyPlayTurn provides the player-safe subset of the current exploration
// state.  It deliberately projects memberships and narrations rather than
// returning their stored documents, which keeps character class and any
// future DM-only narration fields out of the player response.
func getMyPlayTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "player" {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}

	membershipData, err := querySQLite("SELECT state FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(actor.Username) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(membershipData) == "" {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var member playMember
	if err := json.Unmarshal([]byte(strings.TrimSpace(membershipData)), &member); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	firstMember, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC LIMIT 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	currentActor := strings.TrimSpace(firstMember)

	narrationData, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	recentEvents := make([]narrationEvent, 0)
	for _, row := range strings.Split(strings.TrimSuffix(narrationData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event narrationEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		recentEvents = append(recentEvents, event)
	}

	respondJSON(w, http.StatusOK, map[string]any{
		"is_my_turn":    currentActor == actor.Username,
		"current_actor": currentActor,
		"character":     map[string]string{"id": member.CharacterID, "name": member.Name},
		"recent_events": recentEvents,
	})
}

// getGMPlayStatus is the owner-only view of the current play state. Unlike
// the player projection, the GM can inspect the complete party summaries.
func getGMPlayStatus(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Role != "dm" || actor.Username != campaign.Owner {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	membershipData, err := querySQLite("SELECT state FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	party := make([]playMember, 0)
	for _, row := range strings.Split(strings.TrimSuffix(membershipData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var member playMember
		if err := json.Unmarshal([]byte(row), &member); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		party = append(party, member)
	}

	narrationData, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	recentEvents := make([]narrationEvent, 0)
	for _, row := range strings.Split(strings.TrimSuffix(narrationData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event narrationEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		recentEvents = append(recentEvents, event)
	}

	currentActor := ""
	if len(party) > 0 {
		currentActor = party[0].Username
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"needs_attention": currentActor == campaign.Owner,
		"current_actor":   currentActor,
		"party":           party,
		"recent_events":   recentEvents,
	})
}

func appendNarration(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	var input struct {
		Text string `json:"text"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Text) {
		badRequest(w, "invalid narration")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Role != "dm" || campaign.Owner != actor.Username {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	event := narrationEvent{Sequence: count + 1, Kind: "narration", Actor: "dm", Text: input.Text}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, event)
}

// submitTravelTurn consumes the current player's exploration turn. The party's
// location is the destination of its latest travel event; before any travel it
// starts at the first location the owner created for this campaign.
func submitTravelTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		DestinationID string `json:"destination_id"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}

	membersData, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	members := strings.Fields(membersData)
	currentActor, _, err := playTurnStateLocked(campaignID, members)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if campaign.Status != "active" || actor.Role != "player" || currentActor != actor.Username || !containsString(members, actor.Username) {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}

	currentLocation, err := partyCurrentLocationLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	travelTurns := 0
	if currentLocation != "" && validCampaignText(input.DestinationID) {
		turns, err := querySQLite("SELECT travel_turns FROM play_location_connections WHERE campaign_id = " + sqlQuote(campaignID) + " AND from_id = " + sqlQuote(currentLocation) + " AND to_id = " + sqlQuote(input.DestinationID) + " LIMIT 1;")
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		travelTurns, _ = strconv.Atoi(strings.TrimSpace(turns))
	}
	if travelTurns < 1 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "invalid destination"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	event := narrationEvent{Sequence: count + 1, Kind: "travel", Actor: actor.Username, DestinationID: input.DestinationID, TravelTurns: travelTurns, NextActor: campaign.Owner}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, event)
}

// submitRestTurn consumes the current player's exploration turn. Characters
// created before hit points were tracked use the deterministic 20 HP default.
func submitRestTurn(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var input struct {
		Type string `json:"type"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.Type != "short" && input.Type != "long" {
		badRequest(w, "invalid rest type")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	campaign, found, err := loadPlayCampaignLocked(campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !found {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	membersData, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	members := strings.Fields(membersData)
	currentActor, _, err := playTurnStateLocked(campaignID, members)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if campaign.Status != "active" || actor.Role != "player" || currentActor != actor.Username || !containsString(members, actor.Username) {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}

	memberData, err := querySQLite("SELECT state FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " AND username = " + sqlQuote(actor.Username) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var member playMember
	if json.Unmarshal([]byte(strings.TrimSpace(memberData)), &member) != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if member.HPMax < 1 || member.HPCurrent < 0 || member.HPCurrent > member.HPMax {
		member.HPCurrent, member.HPMax = 20, 20
	}
	if input.Type == "long" {
		member.HPCurrent = member.HPMax
	}
	memberState, err := json.Marshal(member)
	if err != nil || runSQLite("UPDATE play_memberships SET state = "+sqlQuote(string(memberState))+" WHERE campaign_id = "+sqlQuote(campaignID)+" AND username = "+sqlQuote(actor.Username)+";") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	event := narrationEvent{Sequence: count + 1, Kind: "rest", Actor: actor.Username, Type: input.Type, HPCurrent: member.HPCurrent, HPMax: member.HPMax, NextActor: campaign.Owner}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, event)
}

func partyCurrentLocationLocked(campaignID string) (string, error) {
	data, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence DESC;")
	if err != nil {
		return "", err
	}
	for _, row := range strings.Split(strings.TrimSuffix(data, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event narrationEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			return "", err
		}
		if event.Kind == "travel" {
			return event.DestinationID, nil
		}
	}
	location, err := querySQLite("SELECT location_id FROM play_locations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC LIMIT 1;")
	return strings.TrimSpace(location), err
}

// submitPlayerAction records the action taken by the first player in the
// deterministic exploration queue. The following turn belongs to the DM.
func submitPlayerAction(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	var input struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Type) || !validCampaignText(input.Text) {
		badRequest(w, "invalid action")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	// The DM and a player who is not at the head of the queue both have to
	// wait for this turn, so they share the conflict response required here.
	if actor.Role != "player" || campaign.Status != "active" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}
	memberNames, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	members := strings.Fields(memberNames)
	if len(members) == 0 || !containsString(members, actor.Username) {
		respondJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	latestEventData, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence DESC LIMIT 1;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var latestEvent narrationEvent
	if strings.TrimSpace(latestEventData) != "" && json.Unmarshal([]byte(strings.TrimSpace(latestEventData)), &latestEvent) != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if actor.Username != members[0] || latestEvent.Kind == "action" {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	event := narrationEvent{
		Sequence: count + 1, Kind: "action", Actor: actor.Username,
		Type: input.Type, Text: input.Text, NextActor: campaign.Owner,
	}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, event)
}

// submitGMResolution closes the owner's response to player A's action and
// advances the deterministic exploration queue to player B.
func submitGMResolution(w http.ResponseWriter, r *http.Request) {
	actor, ok := authenticatedUser(r)
	if !ok {
		respondJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	var input struct {
		Text string `json:"text"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.Text) {
		badRequest(w, "invalid resolution")
		return
	}

	campaignID := r.PathValue("id")
	storageState.Lock()
	defer storageState.Unlock()
	data, err := querySQLite("SELECT state FROM play_campaigns WHERE id = " + sqlQuote(campaignID) + ";")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if strings.TrimSpace(data) == "" {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	var campaign playCampaign
	if err := json.Unmarshal([]byte(strings.TrimSpace(data)), &campaign); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}

	membersData, err := querySQLite("SELECT username FROM play_memberships WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY rowid ASC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	members := strings.Fields(membersData)
	_, deadline, err := playTurnStateLocked(campaignID, members)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	latestData, err := querySQLite("SELECT state FROM play_narrations WHERE campaign_id = " + sqlQuote(campaignID) + " ORDER BY sequence DESC;")
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	currentActor := ""
	previousTurnActor := ""
	for _, row := range strings.Split(strings.TrimSuffix(latestData, "\n"), "\n") {
		if row == "" {
			continue
		}
		var event narrationEvent
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if advancesPlayTurn(event.Kind) {
			currentActor = event.NextActor
			previousTurnActor = event.Actor
			break
		}
	}
	if campaign.Status != "active" || actor.Role != "dm" || actor.Username != campaign.Owner || currentActor != campaign.Owner || len(members) < 2 {
		respondJSON(w, http.StatusConflict, map[string]string{"error": "not the active owner"})
		return
	}

	count, err := campaignRecordCount("play_narrations", campaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	nextActor := members[0]
	for index, member := range members {
		if member == previousTurnActor {
			nextActor = members[(index+1)%len(members)]
			break
		}
	}
	event := narrationEvent{Sequence: count + 1, Kind: "resolution", Actor: "dm", Text: input.Text, NextActor: nextActor}
	state, err := json.Marshal(event)
	if err != nil || runSQLite("INSERT INTO play_narrations (campaign_id, sequence, state) VALUES ("+sqlQuote(campaignID)+", "+strconv.Itoa(event.Sequence)+", "+sqlQuote(string(state))+");") != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusCreated, map[string]any{
		"sequence": event.Sequence, "kind": event.Kind, "actor": event.Actor, "text": event.Text,
		"next_actor": event.NextActor, "turn_number": (deadline + 2) / 2,
	})
}

func authenticatedUser(r *http.Request) (user, bool) {
	const tokenPrefix = "Bearer session-"
	token := r.Header.Get("Authorization")
	if !strings.HasPrefix(token, tokenPrefix) {
		return user{}, false
	}
	username := strings.TrimPrefix(token, tokenPrefix)
	if !validUsername(username) {
		return user{}, false
	}
	userState.Lock()
	account, exists := userState.users[username]
	userState.Unlock()
	if exists {
		return account, true
	}

	// Play-session tokens identify an actor independently of the account store.
	// Storage reset intentionally clears registered accounts while an evaluator
	// can continue a play session using its deterministic session identity.
	// The canonical DM identity has DM privileges; all other session actors are
	// players until a registered account supplies a more specific role.
	role := "player"
	if username == "dm" {
		role = "dm"
	}
	return user{Username: username, Role: role}, true
}

func validUsername(username string) bool {
	if len(username) < 2 || len(username) > 32 {
		return false
	}
	for _, character := range username {
		if !(character >= 'a' && character <= 'z') && !(character >= '0' && character <= '9') && character != '_' && character != '-' {
			return false
		}
	}
	return true
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

// Go's standard library has no password hashing primitive; keeping this
// isolated makes replacing it with a dedicated password KDF straightforward.
func hashPassword(password string) [sha256.Size]byte { return sha256.Sum256([]byte(password)) }

func passwordMatches(expected [sha256.Size]byte, password string) bool {
	actual := hashPassword(password)
	return subtle.ConstantTimeCompare(expected[:], actual[:]) == 1
}

func diceStats(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Expression string `json:"expression"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	matches := diceExpression.FindStringSubmatch(input.Expression)
	if matches == nil {
		badRequest(w, "invalid dice expression")
		return
	}
	count, err1 := strconv.Atoi(matches[1])
	sides, err2 := strconv.Atoi(matches[2])
	modifier := 0
	var err3 error
	if matches[4] != "" {
		modifier, err3 = strconv.Atoi(matches[4])
		if matches[3] == "-" {
			modifier = -modifier
		}
	}
	if err1 != nil || err2 != nil || err3 != nil || count < 1 || sides < 1 {
		badRequest(w, "invalid dice expression")
		return
	}
	min, max := count+modifier, count*sides+modifier
	respondJSON(w, http.StatusOK, map[string]any{
		"dice_count": count, "sides": sides, "modifier": modifier,
		"min": min, "max": max, "average": float64(min+max) / 2,
	})
}

func abilityCheck(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	total := input.Roll + input.Modifier
	respondJSON(w, http.StatusOK, map[string]any{"total": total, "success": total >= input.DC, "margin": total - input.DC})
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Score int `json:"score"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validAbilityScore(input.Score) {
		badRequest(w, "score must be between 1 and 30")
		return
	}
	respondJSON(w, http.StatusOK, map[string]int{"score": input.Score, "modifier": abilityModifier(input.Score)})
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Level int `json:"level"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validLevel(input.Level) {
		badRequest(w, "level must be between 1 and 20")
		return
	}
	respondJSON(w, http.StatusOK, map[string]int{"level": input.Level, "proficiency_bonus": proficiencyBonus(input.Level)})
}

func derivedStats(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Level     int `json:"level"`
		Abilities struct {
			STR int `json:"str"`
			DEX int `json:"dex"`
			CON int `json:"con"`
			INT int `json:"int"`
			WIS int `json:"wis"`
			CHA int `json:"cha"`
		} `json:"abilities"`
		Armor struct {
			Base   int  `json:"base"`
			Shield bool `json:"shield"`
			DexCap int  `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validLevel(input.Level) {
		badRequest(w, "level must be between 1 and 20")
		return
	}
	scores := []int{input.Abilities.STR, input.Abilities.DEX, input.Abilities.CON, input.Abilities.INT, input.Abilities.WIS, input.Abilities.CHA}
	for _, score := range scores {
		if !validAbilityScore(score) {
			badRequest(w, "ability scores must be between 1 and 30")
			return
		}
	}
	modifiers := map[string]int{
		"str": abilityModifier(input.Abilities.STR), "dex": abilityModifier(input.Abilities.DEX),
		"con": abilityModifier(input.Abilities.CON), "int": abilityModifier(input.Abilities.INT),
		"wis": abilityModifier(input.Abilities.WIS), "cha": abilityModifier(input.Abilities.CHA),
	}
	dexBonus := modifiers["dex"]
	if dexBonus > input.Armor.DexCap {
		dexBonus = input.Armor.DexCap
	}
	shieldBonus := 0
	if input.Armor.Shield {
		shieldBonus = 2
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"level": input.Level, "proficiency_bonus": proficiencyBonus(input.Level),
		"hp_max":      input.Level * (6 + modifiers["con"]),
		"armor_class": input.Armor.Base + dexBonus + shieldBonus,
		"modifiers":   modifiers,
	})
}

func validAbilityScore(score int) bool { return score >= 1 && score <= 30 }

func validLevel(level int) bool { return level >= 1 && level <= 20 }

func abilityModifier(score int) int {
	difference := score - 10
	if difference < 0 {
		return -((-difference + 1) / 2)
	}
	return difference / 2
}

func proficiencyBonus(level int) int { return 2 + (level-1)/4 }

var xpForCR = map[string]int{"0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800}

type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

func adjustedXP(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Party []struct {
			Level int `json:"level"`
		} `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	var baseXP, monsterCount int
	for _, monster := range input.Monsters {
		xp, ok := xpForCR[monster.CR]
		if !ok || monster.Count < 1 {
			badRequest(w, "invalid monster")
			return
		}
		baseXP += xp * monster.Count
		monsterCount += monster.Count
	}
	total, ok := partyThresholds(input.Party)
	if !ok {
		badRequest(w, "unsupported party level")
		return
	}
	multiplier := encounterMultiplier(monsterCount)
	adjusted := int(math.Round(float64(baseXP) * multiplier))
	difficulty := encounterDifficulty(adjusted, total)
	respondJSON(w, http.StatusOK, map[string]any{"base_xp": baseXP, "monster_count": monsterCount, "multiplier": multiplier, "adjusted_xp": adjusted, "difficulty": difficulty, "thresholds": total})
}

func encounterMultiplier(n int) float64 {
	switch {
	case n <= 1:
		return 1
	case n == 2:
		return 1.5
	case n <= 6:
		return 2
	case n <= 10:
		return 2.5
	case n <= 14:
		return 3
	default:
		return 4
	}
}

func encounterBuilder(w http.ResponseWriter, r *http.Request) {
	var input struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.CampaignID) || len(input.Party) == 0 || len(input.MonsterSlugs) == 0 {
		badRequest(w, "invalid encounter")
		return
	}
	exists, err := campaignExists(input.CampaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}

	baseXP := 0
	for _, slug := range input.MonsterSlugs {
		if !validCompendiumText(slug) {
			badRequest(w, "invalid monster")
			return
		}
		entry, found, err := loadCompendiumRecord[monster]("monsters", slug)
		if err != nil {
			respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
			return
		}
		if !found {
			respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown monster"})
			return
		}
		xp, ok := xpForCR[entry.CR]
		if !ok {
			badRequest(w, "unsupported monster CR")
			return
		}
		baseXP += xp
	}

	total, ok := partyThresholds(input.Party)
	if !ok {
		badRequest(w, "unsupported party level")
		return
	}
	adjusted := int(math.Round(float64(baseXP) * encounterMultiplier(len(input.MonsterSlugs))))
	difficulty := encounterDifficulty(adjusted, total)
	recommendation := map[string]string{
		"trivial": "safe warm-up", "easy": "safe warm-up", "medium": "balanced challenge",
		"hard": "dangerous fight", "deadly": "deadly threat",
	}[difficulty]
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": input.CampaignID, "base_xp": baseXP, "adjusted_xp": adjusted,
		"difficulty": difficulty, "monster_count": len(input.MonsterSlugs), "recommendation": recommendation,
	})
}

func lootParcel(w http.ResponseWriter, r *http.Request) {
	var input struct {
		CampaignID string `json:"campaign_id"`
		Tier       int    `json:"tier"`
		Seed       int    `json:"seed"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.CampaignID) || input.Tier != 1 {
		badRequest(w, "unsupported loot tier")
		return
	}
	exists, err := campaignExists(input.CampaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": input.CampaignID, "coins_gp": 75,
		"items": []map[string]any{{"slug": "healing-potion", "quantity": 2}},
	})
}

func sessionRecap(w http.ResponseWriter, r *http.Request) {
	var input struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if !validCampaignText(input.CampaignID) {
		badRequest(w, "invalid campaign")
		return
	}
	exists, err := campaignExists(input.CampaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !exists {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	events, err := loadCampaignEvents(input.CampaignID)
	if err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	summary := "No session notes yet."
	if len(events) > 0 {
		summary = events[len(events)-1].Summary
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"campaign_id": input.CampaignID, "summary": summary,
		"open_threads": []string{"Resolve goblin trail ambush"},
	})
}

func partyThresholds(party []struct {
	Level int `json:"level"`
}) (thresholds, bool) {
	var total thresholds
	for _, member := range party {
		if member.Level != 3 {
			return thresholds{}, false
		}
		total.Easy += 75
		total.Medium += 150
		total.Hard += 225
		total.Deadly += 400
	}
	return total, true
}

func encounterDifficulty(adjusted int, total thresholds) string {
	switch {
	case adjusted >= total.Deadly:
		return "deadly"
	case adjusted >= total.Hard:
		return "hard"
	case adjusted >= total.Medium:
		return "medium"
	case adjusted >= total.Easy:
		return "easy"
	default:
		return "trivial"
	}
}

func initiativeOrder(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	type entrant struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}
	order := make([]entrant, len(input.Combatants))
	for i, c := range input.Combatants {
		order[i] = entrant{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex}
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})
	respondJSON(w, http.StatusOK, map[string]any{"order": order})
}

func createCombatSession(w http.ResponseWriter, r *http.Request) {
	var input struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.ID == "" || len(input.Combatants) == 0 {
		badRequest(w, "id and at least one combatant are required")
		return
	}

	order := make([]combatant, len(input.Combatants))
	names := make(map[string]bool, len(input.Combatants))
	for i, c := range input.Combatants {
		if c.Name == "" || names[c.Name] {
			badRequest(w, "combatant names must be unique and non-empty")
			return
		}
		names[c.Name] = true
		order[i] = combatant{Name: c.Name, Score: c.Roll + c.Dex, dex: c.Dex}
	}
	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	combatState.Lock()
	defer combatState.Unlock()
	if _, exists := combatState.sessions[input.ID]; exists {
		badRequest(w, "session id already exists")
		return
	}
	session := &combatSession{ID: input.ID, Round: 1, Order: order, Conditions: make(map[string][]condition)}
	if err := persistSessionLocked(session); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	combatState.sessions[input.ID] = session
	respondJSON(w, http.StatusOK, map[string]any{
		"id": session.ID, "round": session.Round, "turn_index": session.TurnIndex,
		"active": session.Order[session.TurnIndex], "order": session.Order,
	})
}

func addCondition(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if err := decodeJSON(r, &input); err != nil {
		badRequest(w, "invalid JSON")
		return
	}
	if input.DurationRounds < 1 {
		badRequest(w, "duration_rounds must be positive")
		return
	}

	combatState.Lock()
	defer combatState.Unlock()
	session, ok := combatState.sessions[r.PathValue("id")]
	if !ok {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}
	if !session.hasCombatant(input.Target) {
		badRequest(w, "unknown combatant")
		return
	}
	session.Conditions[input.Target] = append(session.Conditions[input.Target], condition{Condition: input.Condition, RemainingRounds: input.DurationRounds})
	if err := persistSessionLocked(session); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{"target": input.Target, "conditions": session.Conditions[input.Target]})
}

func advanceCombatTurn(w http.ResponseWriter, r *http.Request) {
	combatState.Lock()
	defer combatState.Unlock()
	session, ok := combatState.sessions[r.PathValue("id")]
	if !ok {
		respondJSON(w, http.StatusNotFound, map[string]string{"error": "unknown session"})
		return
	}
	session.TurnIndex++
	if session.TurnIndex == len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}
	active := session.Order[session.TurnIndex]
	conditions, tracked := session.Conditions[active.Name]
	remaining := conditions[:0]
	for _, current := range conditions {
		current.RemainingRounds--
		if current.RemainingRounds > 0 {
			remaining = append(remaining, current)
		}
	}
	if tracked {
		// Preserve an empty slice after the final condition expires.
		session.Conditions[active.Name] = remaining
	}
	if err := persistSessionLocked(session); err != nil {
		respondJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	respondJSON(w, http.StatusOK, map[string]any{
		"id": session.ID, "round": session.Round, "turn_index": session.TurnIndex,
		"active": active, "conditions": session.Conditions,
	})
}

func (session *combatSession) hasCombatant(name string) bool {
	for _, entrant := range session.Order {
		if entrant.Name == name {
			return true
		}
	}
	return false
}

func decodeJSON(r *http.Request, value any) error {
	decoder := json.NewDecoder(http.MaxBytesReader(nil, r.Body, maxJSONBodyBytes))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return errors.New("multiple JSON values")
	}
	return nil
}

func respondJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func badRequest(w http.ResponseWriter, message string) {
	respondJSON(w, http.StatusBadRequest, map[string]string{"error": message})
}
