//! Protected campaign-play surface (`/v1/play/...`). Requests must carry an
//! `Authorization: Bearer session-<username>` header identifying a
//! registered user (see [`crate::auth`]); only a `dm` may create a play
//! campaign.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

use crate::auth;
use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

// ===== Data model =====
//
// One `PlayCampaign` (below) owns everything under it: members, narration
// events, the shared document, scenes/locations/travel, and encounters. All
// of it lives behind the single `play_campaigns()` store lock, so within a
// handler these are plain owned structs, not separately-locked state.

pub(crate) struct Member {
    username: String,
    character_id: String,
    name: String,
    class: String,
    hp_current: i64,
    hp_max: i64,
    status: String,
    death_save_successes: i64,
    death_save_failures: i64,
    owner: Option<String>,
    race: Option<String>,
    background: Option<String>,
    level: i64,
    proficiency_bonus: i64,
    con_modifier: i64,
    ability_scores: HashMap<String, i64>,
    spells: Vec<Spell>,
    prepared_spells: Vec<String>,
    spell_slots_used: HashMap<i64, i64>,
    casts: Vec<CastEvent>,
    concentration: Option<Concentration>,
    items: Vec<ItemStack>,
    equipped_armor: Option<String>,
    equipped_accessory: Option<String>,
    accessory_attuned: bool,
    gold: i64,
    quest_reward_xp: i64,
    quest_reward_items: Vec<ItemStack>,
}

#[derive(Clone)]
pub(crate) struct ItemStack {
    item_id: String,
    quantity: i64,
}

pub(crate) struct Spell {
    spell_id: String,
    name: String,
    level: i64,
}

pub(crate) struct Concentration {
    spell_id: String,
    target: String,
    remaining_turns: i64,
}

pub(crate) struct CastEvent {
    sequence: i64,
    spell_id: String,
    target: String,
    slot_level: i64,
}

pub(crate) struct NarrationEvent {
    sequence: i64,
    kind: String,
    actor: String,
    action_type: Option<String>,
    text: String,
    destination_id: Option<String>,
    travel_turns: Option<i64>,
}

pub(crate) struct CampaignDocument {
    story: String,
    dm_notes: String,
}

pub(crate) struct Scene {
    id: String,
    name: String,
    status: String,
}

pub(crate) struct Location {
    id: String,
    name: String,
}

pub(crate) struct Connection {
    from_id: String,
    to_id: String,
    travel_turns: i64,
}

pub(crate) struct Monster {
    monster_id: String,
    name: String,
    hp_max: i64,
    hp_current: i64,
    initiative: i64,
}

pub(crate) struct Combatant {
    member: String,
    character_id: String,
    name: String,
    initiative: i64,
}

pub(crate) struct LootAward {
    slug: String,
    quantity: i64,
}

pub(crate) struct Reward {
    xp: i64,
    loot: Vec<LootAward>,
}

pub(crate) struct Encounter {
    id: String,
    name: String,
    status: String,
    monsters: Vec<Monster>,
    combatants: Vec<Combatant>,
    round: i64,
    turn_index: usize,
    conditions: HashMap<String, Vec<(String, i64)>>,
    order_override: Option<Vec<String>>,
    reward: Option<Reward>,
    combat_ended: bool,
}

struct TurnEntry {
    name: String,
    kind: &'static str,
    initiative: i64,
    member: Option<String>,
    target_id: String,
}

/// Deterministic initiative order combining monsters and bound player
/// combatants: descending initiative, ties broken by name so the order is
/// stable across calls regardless of insertion order.
fn turn_order(e: &Encounter) -> Vec<TurnEntry> {
    let mut order: Vec<TurnEntry> = Vec::new();
    for m in &e.monsters {
        order.push(TurnEntry {
            name: m.name.clone(),
            kind: "monster",
            initiative: m.initiative,
            member: None,
            target_id: m.monster_id.clone(),
        });
    }
    for c in &e.combatants {
        order.push(TurnEntry {
            name: c.name.clone(),
            kind: "player",
            initiative: c.initiative,
            member: Some(c.member.clone()),
            target_id: c.member.clone(),
        });
    }
    order.sort_by(|a, b| b.initiative.cmp(&a.initiative).then_with(|| a.name.cmp(&b.name)));

    if let Some(seq) = &e.order_override {
        let mut reordered: Vec<TurnEntry> = Vec::new();
        for id in seq {
            if let Some(pos) = order.iter().position(|t| &t.target_id == id) {
                reordered.push(order.remove(pos));
            }
        }
        // Any combatant/monster not covered by the override (e.g. added
        // after the override was recorded) keeps its default sorted slot,
        // appended after the explicitly ordered entries.
        reordered.extend(order);
        return reordered;
    }

    order
}

fn active_combatant_json(entry: &TurnEntry) -> String {
    format!(
        r#"{{"name":"{}","kind":"{}","initiative":{}}}"#,
        escape_json_string(&entry.name),
        entry.kind,
        entry.initiative
    )
}

fn conditions_list_json(list: &[(String, i64)]) -> String {
    let items: Vec<String> = list
        .iter()
        .map(|(cond, remaining)| {
            format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                escape_json_string(cond),
                remaining
            )
        })
        .collect();
    format!("[{}]", items.join(","))
}

fn encounter_conditions_json(encounter: &Encounter) -> String {
    let mut names: Vec<&String> = encounter.conditions.keys().collect();
    names.sort();
    let entries: Vec<String> = names
        .into_iter()
        .map(|n| {
            format!(
                r#""{}":{}"#,
                escape_json_string(n),
                conditions_list_json(&encounter.conditions[n])
            )
        })
        .collect();
    format!("{{{}}}", entries.join(","))
}

pub(crate) struct PlayCampaign {
    id: String,
    name: String,
    owner: String,
    max_players: i64,
    members: Vec<Member>,
    status: String,
    current_actor: Option<String>,
    turn_number: i64,
    events: Vec<NarrationEvent>,
    active_member_index: usize,
    nudge_count: i64,
    document: CampaignDocument,
    scenes: Vec<Scene>,
    current_scene_id: Option<String>,
    locations: Vec<Location>,
    connections: Vec<Connection>,
    current_location_id: Option<String>,
    event_sequence: i64,
    encounters: Vec<Encounter>,
    next_transfer_id: i64,
    loot: Vec<LootRecord>,
    npcs: Vec<Npc>,
    factions: Vec<Faction>,
    relationships: Vec<RelationshipEdge>,
    clues: Vec<Clue>,
    quests: Vec<PlayQuest>,
    world_events: Vec<WorldEvent>,
    calendar: Option<Calendar>,
    settlements: Vec<Settlement>,
    recipes: Vec<Recipe>,
    downtime_activities: Vec<DowntimeActivity>,
    downtime_allocations: Vec<DowntimeAllocation>,
    session_zero: Option<SessionZeroSettings>,
    content: Vec<ContentRecord>,
    notes: Vec<Note>,
    whispers: Vec<Whisper>,
    invitations: Vec<Invitation>,
    delegations: Vec<Delegation>,
    delegation_audit: Vec<DelegationAuditEntry>,
    audit_log: Vec<AuditEntry>,
    audit_sequence: i64,
    projection_events: Vec<ProjectionEvent>,
    projection_sequence: i64,
    idempotent_events: Vec<IdempotentEvent>,
    idempotent_sequence: i64,
    safe_turn_current: i64,
    safe_turn_accepted: Vec<SafeTurnAcceptance>,
    transactional_transfers: Vec<TransactionalTransfer>,
    transactional_transfer_sequence: i64,
    exports: Vec<CampaignExport>,
    imported_state: Option<CampaignExport>,
    migrated_state: Option<MigratedState>,
    migration_source: Option<(i64, String)>,
    search_records: Vec<SearchRecord>,
    rate_events: Vec<RateEvent>,
    rejected_rate_events: i64,
    backups: Vec<CampaignBackup>,
    replay_events: Vec<ReplayEvent>,
    replay_sequence: i64,
    rng_seed: Option<String>,
    rng_rolls: Vec<RngRoll>,
    rng_sequence: i64,
    moderation_reports: Vec<ModerationReport>,
    moderation_sequence: i64,
    safety_blocked_tags: Vec<String>,
    safety_events: Vec<SafetyEvent>,
    safety_sequence: i64,
    fixture_seeded: bool,
    spectators: Vec<SpectatorTicket>,
    messages: Vec<ChatMessage>,
    feed_events: Vec<FeedEvent>,
}

pub(crate) struct FeedEvent {
    event_id: String,
    text: String,
    sequence: i64,
}

pub(crate) struct SafetyEvent {
    event_id: String,
    kind: String,
    text: String,
    tags: Vec<String>,
    sequence: i64,
}

pub(crate) struct ModerationReport {
    report_id: String,
    target_id: String,
    reason: String,
    status: String,
    reporter: String,
    sequence: i64,
    action: Option<String>,
    note: Option<String>,
    resolver: Option<String>,
}

pub(crate) struct CampaignBackup {
    backup_id: String,
    story: String,
    status: String,
}

pub(crate) struct ReplayEvent {
    sequence: i64,
    event_id: String,
    kind: String,
    text: String,
}

pub(crate) struct RngRoll {
    roll_id: String,
    sides: i64,
    result: i64,
    sequence: i64,
}

pub(crate) struct SearchRecord {
    record_id: String,
    text: String,
}

pub(crate) struct RateEvent {
    event_id: String,
    actor: String,
}

pub(crate) struct CampaignExport {
    version: i64,
    story: String,
    status: String,
}

pub(crate) struct TransactionalTransfer {
    from_character_id: String,
    to_character_id: String,
    amount: i64,
    from_gold: i64,
    to_gold: i64,
    sequence: i64,
}

pub(crate) struct AuditEntry {
    kind: String,
    actor: String,
    role: String,
    timestamp: i64,
    correlation_id: String,
}

pub(crate) struct ProjectionEvent {
    sequence: i64,
    event_id: String,
    kind: String,
    value: Option<String>,
}

pub(crate) struct IdempotentEvent {
    event_id: String,
    value: String,
    sequence: i64,
    idempotency_key: String,
}

pub(crate) struct SafeTurnAcceptance {
    submission_id: String,
    action: String,
    accepted_turn: i64,
    next_turn: i64,
}

pub(crate) struct Invitation {
    invitation_id: String,
    username: String,
    character_id: String,
    status: String,
}

pub(crate) struct Delegation {
    username: String,
    powers: Vec<String>,
    active: bool,
}

pub(crate) struct DelegationAuditEntry {
    username: String,
    action: String,
    powers: Vec<String>,
}

pub(crate) struct Note {
    note_id: String,
    text: String,
    visibility: String,
    owner: String,
}

pub(crate) struct Whisper {
    whisper_id: String,
    from_character_id: String,
    to_character_id: String,
    text: String,
}

pub(crate) struct SessionZeroSettings {
    rules: String,
    tone: String,
    consent: Vec<String>,
}

pub(crate) struct ContentRecord {
    content_id: String,
    kind: String,
    text: String,
    tags: Vec<String>,
}

pub(crate) struct Recipe {
    recipe_id: String,
    name: String,
    ingredients: Vec<(String, i64)>,
    output_item: String,
    output_quantity: i64,
}

pub(crate) struct DowntimeActivity {
    activity_id: String,
    name: String,
    cycles_required: i64,
}

pub(crate) struct DowntimeAllocation {
    character_id: String,
    activity_id: String,
    cycles_completed: i64,
    completions: i64,
}

pub(crate) struct Calendar {
    day: i64,
    season: String,
}

pub(crate) struct Settlement {
    settlement_id: String,
    name: String,
    services: Vec<String>,
    availability: String,
    discovered_by: Vec<String>,
    shops: Vec<Shop>,
}

pub(crate) struct Shop {
    shop_id: String,
    name: String,
    stock: Vec<(String, i64)>,
    buy_price: i64,
    sell_price: i64,
}

pub(crate) struct WorldEventResolution {
    turn_number: i64,
    text: String,
}

pub(crate) struct WorldEvent {
    event_id: String,
    turn_number: i64,
    title: String,
    text: String,
    resolution: Option<WorldEventResolution>,
}

pub(crate) struct PlayQuest {
    quest_id: String,
    title: String,
    depends_on: Vec<String>,
    state: String,
    rewards: Option<QuestRewards>,
    rewards_awarded: bool,
}

pub(crate) struct QuestRewards {
    xp: i64,
    items: Vec<ItemStack>,
}

pub(crate) struct RelationshipEdge {
    source_id: String,
    target_id: String,
    kind: String,
    score: i64,
}

pub(crate) struct Clue {
    clue_id: String,
    text: String,
    audience: String,
    character_id: Option<String>,
}

pub(crate) struct Npc {
    npc_id: String,
    name: String,
    agenda: String,
    public_status: String,
    dialogue_entries: Vec<NpcDialogueEntry>,
}

pub(crate) struct NpcDialogueEntry {
    dialogue_id: String,
    speaker: String,
    text: String,
    visibility: String,
}

pub(crate) struct ReputationEntry {
    character_id: String,
    reputation: i64,
    delta: i64,
    reason: String,
}

pub(crate) struct Faction {
    faction_id: String,
    name: String,
    reputation_entries: Vec<ReputationEntry>,
}

pub(crate) struct LootVote {
    voter: String,
    recipient_character_id: String,
}

pub(crate) struct LootRecord {
    loot_id: String,
    item_id: String,
    quantity: i64,
    status: String,
    votes: Vec<LootVote>,
    recipient_character_id: Option<String>,
}

pub(crate) struct SpectatorTicket {
    spectator_id: String,
}

pub(crate) struct ChatMessage {
    actor: String,
    text: String,
}

// ===== Store =====

pub(crate) fn play_campaigns() -> &'static Mutex<HashMap<String, PlayCampaign>> {
    static PLAY_CAMPAIGNS: OnceLock<Mutex<HashMap<String, PlayCampaign>>> = OnceLock::new();
    PLAY_CAMPAIGNS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Process-global maintenance switch (not campaign-local). Any DM can flip
/// it via any campaign's `/service-mode` endpoint, and it governs the
/// public `/readyz` response for the whole server.
fn maintenance_mode() -> &'static AtomicBool {
    static MAINTENANCE_MODE: OnceLock<AtomicBool> = OnceLock::new();
    MAINTENANCE_MODE.get_or_init(|| AtomicBool::new(false))
}

pub(crate) fn clear() {
    play_campaigns().lock().unwrap().clear();
}

// ===== Shared request-handling macros =====

/// Authenticates the request or returns early with a 401. Every handler in
/// this module starts with this same check, so it's factored into a macro
/// (rather than a function) to preserve the early-return control flow.
macro_rules! authenticated {
    ($stream:expr, $auth_header:expr) => {
        match auth::authenticate($auth_header) {
            Some(u) => u,
            None => return respond($stream, 401, r#"{"error":"unauthorized"}"#),
        }
    };
}

/// Looks up `campaign_id` in `$store` (mutably or immutably, matching
/// whichever `get`/`get_mut` call is passed in) or returns early with a 404.
macro_rules! campaign_or_404 {
    ($stream:expr, $lookup:expr) => {
        match $lookup {
            Some(c) => c,
            None => return respond($stream, 404, r#"{"error":"campaign not found"}"#),
        }
    };
}

/// Parses `$body` as JSON or returns early with a 400.
macro_rules! parsed_json {
    ($stream:expr, $body:expr) => {
        match parse_json($body) {
            Some(j) => j,
            None => return bad_request($stream, "invalid json"),
        }
    };
}

/// Reads a required, non-empty string field from `$json` or returns early
/// with a 400 carrying `$err`.
macro_rules! require_str {
    ($stream:expr, $json:expr, $field:expr, $err:expr) => {
        match $json.get($field).and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => return bad_request($stream, $err),
        }
    };
}

pub(crate) fn handle_schema(stream: &mut TcpStream) -> std::io::Result<()> {
    respond(
        stream,
        200,
        r#"{"version":"2026-07-29","endpoints":[{"method":"GET","path":"/v1/play/campaigns/{id}/rng-ledger","auth":"member"},{"method":"GET","path":"/v1/schema","auth":"public"},{"method":"POST","path":"/v1/play/campaigns","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/fixture-seeds","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/members","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/moderation/reports","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/rng-rolls","auth":"member"},{"method":"PUT","path":"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/rng-seed","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/safety-boundaries","auth":"dm"}]}"#,
    )
}

pub(crate) fn handle_readyz(stream: &mut TcpStream) -> std::io::Result<()> {
    if maintenance_mode().load(Ordering::SeqCst) {
        respond(stream, 503, r#"{"status":"maintenance","schema_version":2}"#)
    } else {
        respond(stream, 200, r#"{"status":"ready","schema_version":2}"#)
    }
}

pub(crate) fn handle_set_service_mode(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    drop(store);

    let json = parsed_json!(stream, body);
    let maintenance = match json.get("maintenance") {
        Some(crate::json::Json::Bool(b)) => *b,
        _ => return bad_request(stream, "invalid maintenance"),
    };

    maintenance_mode().store(maintenance, Ordering::SeqCst);

    let out = format!(r#"{{"maintenance":{}}}"#, maintenance);
    respond(stream, 200, &out)
}

// ===== Lobby: create / join / start =====

fn play_campaign_json(c: &PlayCampaign) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","owner":"{}","status":"{}","max_players":{}}}"#,
        escape_json_string(&c.id),
        escape_json_string(&c.name),
        escape_json_string(&c.owner),
        escape_json_string(&c.status),
        c.max_players
    )
}

fn start_json(c: &PlayCampaign) -> String {
    format!(
        r#"{{"id":"{}","status":"{}","current_actor":"{}","turn_number":{}}}"#,
        escape_json_string(&c.id),
        escape_json_string(&c.status),
        escape_json_string(c.current_actor.as_deref().unwrap_or("")),
        c.turn_number
    )
}

pub(crate) fn handle_create_play_campaign(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    body: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);
    if role != "dm" {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let id = require_str!(stream, json, "id", "invalid id");
    let name = require_str!(stream, json, "name", "invalid name");
    let max_players = match json.get("max_players").and_then(as_int) {
        Some(n) if n >= 1 => n,
        _ => return bad_request(stream, "invalid max_players"),
    };

    let mut store = play_campaigns().lock().unwrap();
    if store.contains_key(&id) {
        return respond(stream, 409, r#"{"error":"campaign already exists"}"#);
    }

    let campaign = PlayCampaign {
        id: id.clone(),
        name,
        owner: username,
        max_players,
        members: Vec::new(),
        status: "lobby".to_string(),
        current_actor: None,
        turn_number: 0,
        events: Vec::new(),
        active_member_index: 0,
        nudge_count: 0,
        document: CampaignDocument {
            story: String::new(),
            dm_notes: String::new(),
        },
        scenes: Vec::new(),
        current_scene_id: None,
        locations: Vec::new(),
        connections: Vec::new(),
        current_location_id: None,
        event_sequence: 0,
        encounters: Vec::new(),
        next_transfer_id: 1,
        loot: Vec::new(),
        npcs: Vec::new(),
        factions: Vec::new(),
        relationships: Vec::new(),
        clues: Vec::new(),
        quests: Vec::new(),
        world_events: Vec::new(),
        calendar: None,
        settlements: Vec::new(),
        recipes: Vec::new(),
        downtime_activities: Vec::new(),
        downtime_allocations: Vec::new(),
        session_zero: None,
        content: Vec::new(),
        notes: Vec::new(),
        whispers: Vec::new(),
        invitations: Vec::new(),
        delegations: Vec::new(),
        delegation_audit: Vec::new(),
        audit_log: Vec::new(),
        audit_sequence: 0,
        projection_events: Vec::new(),
        projection_sequence: 0,
        idempotent_events: Vec::new(),
        idempotent_sequence: 0,
        safe_turn_current: 1,
        safe_turn_accepted: Vec::new(),
        transactional_transfers: Vec::new(),
        transactional_transfer_sequence: 0,
        exports: Vec::new(),
        imported_state: None,
        migrated_state: None,
        migration_source: None,
        search_records: Vec::new(),
        rate_events: Vec::new(),
        rejected_rate_events: 0,
        backups: Vec::new(),
        replay_events: Vec::new(),
        replay_sequence: 0,
        rng_seed: None,
        rng_rolls: Vec::new(),
        rng_sequence: 0,
        moderation_reports: Vec::new(),
        moderation_sequence: 0,
        safety_blocked_tags: Vec::new(),
        safety_events: Vec::new(),
        safety_sequence: 0,
        fixture_seeded: false,
        spectators: Vec::new(),
        messages: Vec::new(),
        feed_events: Vec::new(),
    };
    let out = play_campaign_json(&campaign);
    store.insert(id, campaign);
    drop(store);

    respond(stream, 201, &out)
}

fn member_json(username: &str, m: &Member) -> String {
    format!(
        r#"{{"username":"{}","character_id":"{}","name":"{}","class":"{}"}}"#,
        escape_json_string(username),
        escape_json_string(&m.character_id),
        escape_json_string(&m.name),
        escape_json_string(&m.class)
    )
}

pub(crate) fn handle_join_play_campaign(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);
    if role != "player" {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let character_id = require_str!(stream, json, "character_id", "invalid character_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let class = require_str!(stream, json, "class", "invalid class");

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.members.iter().any(|m| m.username == username) {
        return respond(stream, 409, r#"{"error":"already a member"}"#);
    }
    if campaign.members.iter().any(|m| m.character_id == character_id) {
        return respond(stream, 409, r#"{"error":"character already exists"}"#);
    }
    if campaign.members.len() as i64 >= campaign.max_players {
        return respond(stream, 409, r#"{"error":"campaign full"}"#);
    }

    let member = Member {
        username: username.clone(),
        character_id,
        name,
        class,
        hp_current: 20,
        hp_max: 20,
        status: "alive".to_string(),
        death_save_successes: 0,
        death_save_failures: 0,
        owner: Some(username.clone()),
        race: None,
        background: None,
        level: 1,
        proficiency_bonus: 2,
        con_modifier: 0,
        ability_scores: HashMap::new(),
        spells: Vec::new(),
        prepared_spells: Vec::new(),
        spell_slots_used: HashMap::new(),
        casts: Vec::new(),
        concentration: None,
        items: Vec::new(),
        equipped_armor: None,
        equipped_accessory: None,
        accessory_attuned: false,
        gold: 10,
        quest_reward_xp: 0,
        quest_reward_items: Vec::new(),
    };
    let out = member_json(&username, &member);
    campaign.members.push(member);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_start_play_campaign(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if role != "dm" || campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if campaign.status != "lobby" || campaign.members.len() < 2 {
        return respond(stream, 409, r#"{"error":"campaign cannot be started"}"#);
    }

    campaign.status = "active".to_string();
    campaign.current_actor = Some(campaign.members[0].username.clone());
    campaign.turn_number = 1;

    let out = start_json(campaign);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Narration, player actions & turn state =====

fn narration_json(e: &NarrationEvent) -> String {
    if let Some(destination_id) = &e.destination_id {
        return format!(
            r#"{{"sequence":{},"kind":"{}","actor":"{}","destination_id":"{}","travel_turns":{}}}"#,
            e.sequence,
            escape_json_string(&e.kind),
            escape_json_string(&e.actor),
            escape_json_string(destination_id),
            e.travel_turns.unwrap_or(0)
        );
    }
    match &e.action_type {
        Some(action_type) => format!(
            r#"{{"sequence":{},"kind":"{}","actor":"{}","type":"{}","text":"{}"}}"#,
            e.sequence,
            escape_json_string(&e.kind),
            escape_json_string(&e.actor),
            escape_json_string(action_type),
            escape_json_string(&e.text)
        ),
        None => format!(
            r#"{{"sequence":{},"kind":"{}","actor":"{}","text":"{}"}}"#,
            e.sequence,
            escape_json_string(&e.kind),
            escape_json_string(&e.actor),
            escape_json_string(&e.text)
        ),
    }
}

pub(crate) fn handle_create_narration(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = role == "dm" && campaign.owner == username;
    let is_delegate = campaign.delegations.iter().any(|d| {
        d.username == username && d.active && d.powers.iter().any(|p| p == "narrate")
    });
    if !is_owner && !is_delegate {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let text = require_str!(stream, json, "text", "invalid text");

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let event = NarrationEvent {
        sequence,
        kind: "narration".to_string(),
        actor: username.clone(),
        action_type: None,
        text,
        destination_id: None,
        travel_turns: None,
    };
    let out = narration_json(&event);
    campaign.events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_action(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner == username {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    if campaign.current_actor.as_deref() != Some(username.as_str()) {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let action_type = require_str!(stream, json, "type", "invalid type");
    let text = require_str!(stream, json, "text", "invalid text");

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let event = NarrationEvent {
        sequence,
        kind: "action".to_string(),
        actor: username,
        action_type: Some(action_type),
        text,
        destination_id: None,
        travel_turns: None,
    };
    let out = format!(
        r#"{{"sequence":{},"kind":"action","actor":"{}","type":"{}","text":"{}","next_actor":"dm"}}"#,
        event.sequence,
        escape_json_string(&event.actor),
        escape_json_string(event.action_type.as_deref().unwrap_or("")),
        escape_json_string(&event.text)
    );
    campaign.events.push(event);
    campaign.current_actor = Some(campaign.owner.clone());
    drop(store);

    respond(stream, 201, &out)
}

fn turn_queue(c: &PlayCampaign) -> Vec<String> {
    let mut queue = Vec::with_capacity(c.members.len() * 2);
    for m in &c.members {
        queue.push(m.username.clone());
        queue.push(c.owner.clone());
    }
    queue
}

fn turn_json(c: &PlayCampaign) -> String {
    let phase = match c.current_actor.as_deref() {
        Some(actor) if actor == c.owner => "exploration",
        Some(_) => "player",
        None => "lobby",
    };
    let queue = turn_queue(c);
    let queue_json = queue
        .iter()
        .map(|actor| format!(r#""{}""#, escape_json_string(actor)))
        .collect::<Vec<_>>()
        .join(",");
    let logical_deadline = c.turn_number + 1;
    format!(
        r#"{{"campaign_id":"{}","current_actor":"{}","phase":"{}","turn_number":{},"queue":[{}],"overdue":false,"logical_deadline":{}}}"#,
        escape_json_string(&c.id),
        escape_json_string(c.current_actor.as_deref().unwrap_or("")),
        escape_json_string(phase),
        c.turn_number,
        queue_json,
        logical_deadline
    )
}

pub(crate) fn handle_get_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = turn_json(campaign);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_onboarding(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_owner && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = if is_owner {
        r#"{"role":"dm","next_steps":["configure-safety","invite-players","start-campaign"],"can_mutate":true}"#
    } else {
        r#"{"role":"player","next_steps":["review-party","take-turn","submit-action"],"can_mutate":true}"#
    };
    drop(store);

    respond(stream, 200, out)
}

fn my_turn_json(c: &PlayCampaign, username: &str, member: &Member) -> String {
    let is_my_turn = c.current_actor.as_deref() == Some(username);
    let recent_events: Vec<String> = c
        .events
        .iter()
        .rev()
        .take(5)
        .map(narration_json)
        .collect();
    format!(
        r#"{{"campaign_id":"{}","is_my_turn":{},"current_actor":"{}","character":{{"id":"{}","name":"{}"}},"recent_events":[{}]}}"#,
        escape_json_string(&c.id),
        is_my_turn,
        escape_json_string(c.current_actor.as_deref().unwrap_or("")),
        escape_json_string(&member.character_id),
        escape_json_string(&member.name),
        recent_events.join(",")
    )
}

fn gm_status_json(c: &PlayCampaign) -> String {
    let needs_attention = c.current_actor.as_deref() == Some(c.owner.as_str());
    let party: Vec<String> = c
        .members
        .iter()
        .map(|m| member_json(&m.username, m))
        .collect();
    let recent_events: Vec<String> = c
        .events
        .iter()
        .rev()
        .take(5)
        .map(narration_json)
        .collect();
    format!(
        r#"{{"campaign_id":"{}","needs_attention":{},"current_actor":"{}","party":[{}],"recent_events":[{}]}}"#,
        escape_json_string(&c.id),
        needs_attention,
        escape_json_string(c.current_actor.as_deref().unwrap_or("")),
        party.join(","),
        recent_events.join(",")
    )
}

pub(crate) fn handle_get_gm_status(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = gm_status_json(campaign);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_my_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);
    if role != "player" {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let member = match campaign.members.iter().find(|m| m.username == username) {
        Some(m) => m,
        None => return respond(stream, 403, r#"{"error":"forbidden"}"#),
    };

    let out = my_turn_json(campaign, &username, member);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_create_resolution(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        let is_member = campaign.members.iter().any(|m| m.username == username);
        if is_member {
            return respond(stream, 409, r#"{"error":"not your turn"}"#);
        }
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    if campaign.current_actor.as_deref() != Some(campaign.owner.as_str())
        || campaign.members.is_empty()
    {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let text = require_str!(stream, json, "text", "invalid text");

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let event = NarrationEvent {
        sequence,
        kind: "resolution".to_string(),
        actor: username,
        action_type: None,
        text,
        destination_id: None,
        travel_turns: None,
    };
    campaign.events.push(event);

    let last_index = campaign.members.len().saturating_sub(1);
    campaign.active_member_index = if campaign.turn_number >= 2 { 0 } else { last_index.min(1) };
    let next_actor = campaign.members[campaign.active_member_index].username.clone();
    campaign.current_actor = Some(next_actor.clone());
    campaign.turn_number += 1;

    let last = campaign.events.last().unwrap();
    let out = format!(
        r#"{{"sequence":{},"kind":"resolution","actor":"{}","text":"{}","next_actor":"{}","turn_number":{}}}"#,
        last.sequence,
        escape_json_string(&last.actor),
        escape_json_string(&last.text),
        escape_json_string(&next_actor),
        campaign.turn_number
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_turn_nudge(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if role != "dm" || campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let target = match campaign.current_actor.clone() {
        Some(t) => t,
        None => return respond(stream, 409, r#"{"error":"no active turn"}"#),
    };

    let json = parsed_json!(stream, body);
    let message = require_str!(stream, json, "message", "invalid message");

    campaign.nudge_count += 1;
    campaign.event_sequence += 1;
    let out = format!(
        r#"{{"campaign_id":"{}","actor":"{}","target":"{}","message":"{}","nudge_count":{}}}"#,
        escape_json_string(&campaign.id),
        escape_json_string(&username),
        escape_json_string(&target),
        escape_json_string(&message),
        campaign.nudge_count
    );
    drop(store);

    respond(stream, 201, &out)
}

// ===== Shared story/DM-notes document =====

pub(crate) fn handle_put_document(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let story = match json.get("story").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad_request(stream, "invalid story"),
    };
    let dm_notes = match json.get("dm_notes").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad_request(stream, "invalid dm_notes"),
    };

    campaign.document = CampaignDocument { story, dm_notes };
    if campaign.turn_number > 1 {
        campaign.event_sequence += 1;
    }
    let out = format!(
        r#"{{"story":"{}","dm_notes":"{}"}}"#,
        escape_json_string(&campaign.document.story),
        escape_json_string(&campaign.document.dm_notes)
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_document(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = if campaign.owner == username {
        format!(
            r#"{{"story":"{}","dm_notes":"{}"}}"#,
            escape_json_string(&campaign.document.story),
            escape_json_string(&campaign.document.dm_notes)
        )
    } else {
        format!(
            r#"{{"story":"{}"}}"#,
            escape_json_string(&campaign.document.story)
        )
    };
    drop(store);

    respond(stream, 200, &out)
}

// ===== Scenes =====

fn scene_json(s: &Scene) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","status":"{}"}}"#,
        escape_json_string(&s.id),
        escape_json_string(&s.name),
        escape_json_string(&s.status)
    )
}

pub(crate) fn handle_create_scene(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let id = require_str!(stream, json, "id", "invalid id");
    let name = require_str!(stream, json, "name", "invalid name");

    if campaign.scenes.iter().any(|s| s.id == id) {
        return respond(stream, 409, r#"{"error":"scene already exists"}"#);
    }

    let scene = Scene {
        id,
        name,
        status: "open".to_string(),
    };
    let out = scene_json(&scene);
    campaign.scenes.push(scene);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_enter_scene(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    scene_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let scene = match campaign.scenes.iter().find(|s| s.id == scene_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"scene not found"}"#),
    };
    if scene.status != "open" {
        return respond(stream, 409, r#"{"error":"scene is closed"}"#);
    }

    let out = format!(
        r#"{{"current_scene_id":"{}","name":"{}"}}"#,
        escape_json_string(&scene.id),
        escape_json_string(&scene.name)
    );
    campaign.current_scene_id = Some(scene_id.to_string());
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_close_scene(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    scene_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let scene = match campaign.scenes.iter_mut().find(|s| s.id == scene_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"scene not found"}"#),
    };
    scene.status = "closed".to_string();
    let out = format!(
        r#"{{"id":"{}","status":"{}"}}"#,
        escape_json_string(&scene.id),
        escape_json_string(&scene.status)
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_current_scene(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let scene_id = match &campaign.current_scene_id {
        Some(id) => id,
        None => return respond(stream, 404, r#"{"error":"no current scene"}"#),
    };
    let scene = match campaign.scenes.iter().find(|s| &s.id == scene_id) {
        Some(s) if s.status == "open" => s,
        _ => return respond(stream, 404, r#"{"error":"no current scene"}"#),
    };

    let out = scene_json(scene);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Locations, connections & travel =====

fn location_json(l: &Location) -> String {
    format!(
        r#"{{"id":"{}","name":"{}"}}"#,
        escape_json_string(&l.id),
        escape_json_string(&l.name)
    )
}

pub(crate) fn handle_create_location(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let id = require_str!(stream, json, "id", "invalid id");
    let name = require_str!(stream, json, "name", "invalid name");

    if campaign.locations.iter().any(|l| l.id == id) {
        return respond(stream, 409, r#"{"error":"location already exists"}"#);
    }

    let location = Location { id, name };
    let out = location_json(&location);
    if campaign.current_location_id.is_none() {
        campaign.current_location_id = Some(location.id.clone());
    }
    campaign.locations.push(location);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_connection(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    from_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let to_id = require_str!(stream, json, "to_id", "invalid to_id");
    let travel_turns = match json.get("travel_turns").and_then(as_int) {
        Some(n) if n >= 1 => n,
        _ => return bad_request(stream, "invalid travel_turns"),
    };

    if !campaign.locations.iter().any(|l| l.id == from_id) {
        return bad_request(stream, "unknown from location");
    }
    if !campaign.locations.iter().any(|l| l.id == to_id) {
        return bad_request(stream, "unknown to location");
    }
    if campaign
        .connections
        .iter()
        .any(|c| c.from_id == from_id && c.to_id == to_id)
    {
        return bad_request(stream, "already connected");
    }

    let connection = Connection {
        from_id: from_id.to_string(),
        to_id,
        travel_turns,
    };
    let out = format!(
        r#"{{"from_id":"{}","to_id":"{}","travel_turns":{}}}"#,
        escape_json_string(&connection.from_id),
        escape_json_string(&connection.to_id),
        connection.travel_turns
    );
    campaign.connections.push(connection);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_travel(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    loc_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let destinations: Vec<String> = campaign
        .connections
        .iter()
        .filter(|c| c.from_id == loc_id)
        .filter_map(|c| {
            campaign
                .locations
                .iter()
                .find(|l| l.id == c.to_id)
                .map(|l| {
                    format!(
                        r#"{{"id":"{}","name":"{}","travel_turns":{}}}"#,
                        escape_json_string(&l.id),
                        escape_json_string(&l.name),
                        c.travel_turns
                    )
                })
        })
        .collect();

    let out = format!(r#"{{"destinations":[{}]}}"#, destinations.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_create_travel(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner == username {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    if campaign.current_actor.as_deref() != Some(username.as_str()) {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let destination_id = require_str!(stream, json, "destination_id", "invalid destination_id");

    let travel_turns = match campaign.current_location_id.as_deref() {
        Some(current) => campaign
            .connections
            .iter()
            .find(|c| c.from_id == current && c.to_id == destination_id)
            .map(|c| c.travel_turns),
        None => None,
    };
    let travel_turns = match travel_turns {
        Some(t) => t,
        None => return respond(stream, 409, r#"{"error":"invalid destination"}"#),
    };

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let event = NarrationEvent {
        sequence,
        kind: "travel".to_string(),
        actor: username,
        action_type: None,
        text: String::new(),
        destination_id: Some(destination_id.clone()),
        travel_turns: Some(travel_turns),
    };
    let out = format!(
        r#"{{"sequence":{},"kind":"travel","actor":"{}","destination_id":"{}","travel_turns":{},"next_actor":"dm"}}"#,
        event.sequence,
        escape_json_string(&event.actor),
        escape_json_string(&destination_id),
        travel_turns
    );
    campaign.events.push(event);
    campaign.current_location_id = Some(destination_id);
    campaign.current_actor = Some(campaign.owner.clone());
    drop(store);

    respond(stream, 201, &out)
}

// ===== Encounters: setup, combatants & turn order =====

fn encounter_json(e: &Encounter) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","status":"{}","combatants":[]}}"#,
        escape_json_string(&e.id),
        escape_json_string(&e.name),
        escape_json_string(&e.status)
    )
}

pub(crate) fn handle_create_encounter(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let id = require_str!(stream, json, "id", "invalid id");
    let name = require_str!(stream, json, "name", "invalid name");

    if campaign.encounters.iter().any(|e| e.id == id) {
        return respond(stream, 409, r#"{"error":"encounter already exists"}"#);
    }
    if campaign.encounters.iter().any(|e| e.status == "active") {
        return respond(stream, 409, r#"{"error":"campaign already in combat"}"#);
    }

    let encounter = Encounter {
        id,
        name,
        status: "active".to_string(),
        monsters: Vec::new(),
        combatants: Vec::new(),
        round: 1,
        turn_index: 0,
        conditions: HashMap::new(),
        order_override: None,
        reward: None,
        combat_ended: false,
    };
    let out = encounter_json(&encounter);
    campaign.encounters.push(encounter);
    drop(store);

    respond(stream, 201, &out)
}

fn monster_json(m: &Monster) -> String {
    format!(
        r#"{{"monster_id":"{}","name":"{}","hp_max":{},"initiative":{},"hp_current":{}}}"#,
        escape_json_string(&m.monster_id),
        escape_json_string(&m.name),
        m.hp_max,
        m.initiative,
        m.hp_current
    )
}

pub(crate) fn handle_create_monster(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let json = parsed_json!(stream, body);
    let monster_id = require_str!(stream, json, "monster_id", "invalid monster_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let hp_max = match json.get("hp_max").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid hp_max"),
    };
    let initiative = match json.get("initiative").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid initiative"),
    };

    if encounter.monsters.iter().any(|m| m.monster_id == monster_id) {
        return respond(stream, 409, r#"{"error":"monster already exists"}"#);
    }

    let monster = Monster {
        monster_id,
        name,
        hp_max,
        hp_current: hp_max,
        initiative,
    };
    let out = monster_json(&monster);
    encounter.monsters.push(monster);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_remove_monster(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let before = encounter.monsters.len();
    encounter.monsters.retain(|m| m.monster_id != monster_id);
    if encounter.monsters.len() == before {
        return respond(stream, 404, r#"{"error":"monster not found"}"#);
    }
    drop(store);

    let out = format!(r#"{{"removed":"{}"}}"#, escape_json_string(monster_id));
    respond(stream, 200, &out)
}

fn combatant_json(c: &Combatant) -> String {
    format!(
        r#"{{"member":"{}","character_id":"{}","name":"{}","initiative":{}}}"#,
        escape_json_string(&c.member),
        escape_json_string(&c.character_id),
        escape_json_string(&c.name),
        c.initiative
    )
}

pub(crate) fn handle_bind_combatant(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let member = require_str!(stream, json, "member", "invalid member");
    let initiative = match json.get("initiative").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid initiative"),
    };

    let (character_id, name) = match campaign.members.iter().find(|m| m.username == member) {
        Some(m) => (m.character_id.clone(), m.name.clone()),
        None => return bad_request(stream, "invalid member"),
    };

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    if encounter.combatants.iter().any(|c| c.member == member) {
        return respond(stream, 409, r#"{"error":"already bound"}"#);
    }

    let combatant = Combatant {
        member,
        character_id,
        name,
        initiative,
    };
    let out = combatant_json(&combatant);
    encounter.combatants.push(combatant);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_unbind_combatant(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    member: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let before = encounter.combatants.len();
    encounter.combatants.retain(|c| c.member != member);
    if encounter.combatants.len() == before {
        return respond(stream, 404, r#"{"error":"combatant not found"}"#);
    }
    drop(store);

    let out = format!(r#"{{"removed":"{}"}}"#, escape_json_string(member));
    respond(stream, 200, &out)
}

pub(crate) fn handle_get_encounter_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    if order.is_empty() {
        return respond(stream, 409, r#"{"error":"no combatants"}"#);
    }
    let idx = encounter.turn_index % order.len();
    let out = format!(
        r#"{{"round":{},"turn_index":{},"active":{}}}"#,
        encounter.round,
        idx,
        active_combatant_json(&order[idx])
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_advance_encounter_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let owner = campaign.owner.clone();
    let is_member = owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    if order.is_empty() {
        return respond(stream, 409, r#"{"error":"no combatants"}"#);
    }
    let len = order.len();
    let current_idx = encounter.turn_index % len;
    let is_current_combatant = order[current_idx].member.as_deref() == Some(username.as_str());
    if username != owner && !is_current_combatant {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let next_idx = (current_idx + 1) % len;
    if next_idx == 0 {
        encounter.round += 1;
    }
    encounter.turn_index = next_idx;

    // Conditions tick down (and expire) only for the combatant whose turn
    // is beginning, matching "duration_rounds remaining at the start of
    // your turn" semantics.
    let active_target_id = order[next_idx].target_id.clone();
    if let Some(list) = encounter.conditions.get_mut(&active_target_id) {
        for entry in list.iter_mut() {
            entry.1 -= 1;
        }
        list.retain(|(_, remaining)| *remaining > 0);
    }

    let out = format!(
        r#"{{"round":{},"turn_index":{},"active":{}}}"#,
        encounter.round,
        next_idx,
        active_combatant_json(&order[next_idx])
    );
    drop(store);

    respond(stream, 200, &out)
}

/// Moves the current combatant to a later slot in the initiative order
/// without advancing the round or duplicating anyone's turn: whoever now
/// occupies the (unchanged) `turn_index` becomes the active combatant.
pub(crate) fn handle_turn_delay(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let owner = campaign.owner.clone();
    let is_member = owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    if order.is_empty() {
        return respond(stream, 409, r#"{"error":"no combatants"}"#);
    }
    let len = order.len();
    let current_idx = encounter.turn_index % len;
    let is_current_combatant = order[current_idx].member.as_deref() == Some(username.as_str());
    if username != owner && !is_current_combatant {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let target_index = match json.get("new_index").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid index"),
    };
    if target_index <= current_idx as i64 || target_index as usize >= len {
        return bad_request(stream, "invalid index");
    }
    let target_index = target_index as usize;

    let mut ids: Vec<String> = order.iter().map(|t| t.target_id.clone()).collect();
    let moved = ids.remove(current_idx);
    ids.insert(target_index, moved);
    encounter.order_override = Some(ids);
    // The delaying combatant stays "current" at their new slot until they
    // actually act, so ready/advance still recognize them afterward.
    encounter.turn_index = target_index;

    let new_order = turn_order(encounter);
    let order_json: Vec<String> = new_order.iter().map(active_combatant_json).collect();
    let out = format!(r#"{{"order":[{}]}}"#, order_json.join(","));
    drop(store);

    respond(stream, 200, &out)
}

/// Records that the current combatant is holding their action for a
/// trigger. Purely informational: it does not touch `turn_index`, `round`,
/// or the initiative order, so the combatant's turn is neither skipped nor
/// duplicated.
pub(crate) fn handle_turn_ready(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    if order.is_empty() {
        return respond(stream, 409, r#"{"error":"no combatants"}"#);
    }
    let idx = encounter.turn_index % order.len();
    let is_current_combatant = order[idx].member.as_deref() == Some(username.as_str());
    if !is_current_combatant {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let trigger = require_str!(stream, json, "trigger", "invalid trigger");

    let out = format!(
        r#"{{"actor":"{}","trigger":"{}"}}"#,
        escape_json_string(&username),
        escape_json_string(&trigger)
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_add_encounter_condition(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let json = parsed_json!(stream, body);
    let target = require_str!(stream, json, "target", "invalid target");
    let condition = require_str!(stream, json, "condition", "invalid condition");
    let duration_rounds = match json.get("duration_rounds").and_then(as_int) {
        Some(d) if d > 0 => d,
        _ => return bad_request(stream, "invalid duration_rounds"),
    };

    let is_valid_target = encounter.monsters.iter().any(|m| m.monster_id == target)
        || encounter.combatants.iter().any(|c| c.member == target);
    if !is_valid_target {
        return bad_request(stream, "invalid target");
    }

    encounter
        .conditions
        .entry(target.clone())
        .or_insert_with(Vec::new)
        .push((condition, duration_rounds));

    let out = format!(
        r#"{{"target":"{}","conditions":{}}}"#,
        escape_json_string(&target),
        conditions_list_json(&encounter.conditions[&target])
    );
    drop(store);

    respond(stream, 201, &out)
}

// ===== Encounter rewards & lifecycle (close/end) =====

fn reward_json(r: &Reward) -> String {
    let loot: Vec<String> = r
        .loot
        .iter()
        .map(|l| {
            format!(
                r#"{{"slug":"{}","quantity":{}}}"#,
                escape_json_string(&l.slug),
                l.quantity
            )
        })
        .collect();
    format!(r#"{{"xp":{},"loot":[{}]}}"#, r.xp, loot.join(","))
}

pub(crate) fn handle_award_encounter_rewards(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    if encounter.reward.is_some() {
        return respond(stream, 409, r#"{"error":"rewards already awarded"}"#);
    }

    let json = parsed_json!(stream, body);
    let xp = match json.get("xp").and_then(as_int) {
        Some(x) if x >= 0 => x,
        _ => return bad_request(stream, "invalid xp"),
    };
    let loot_json = match json.get("loot").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return bad_request(stream, "invalid loot"),
    };
    let mut loot = Vec::new();
    for item in loot_json {
        let obj = match item.as_object() {
            Some(o) => o,
            None => return bad_request(stream, "invalid loot"),
        };
        let slug = match crate::json::object_get(obj, "slug").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => return bad_request(stream, "invalid loot slug"),
        };
        let quantity = match crate::json::object_get(obj, "quantity").and_then(as_int) {
            Some(q) if q > 0 => q,
            _ => return bad_request(stream, "invalid loot quantity"),
        };
        loot.push(LootAward { slug, quantity });
    }

    let reward = Reward { xp, loot };
    let out = reward_json(&reward);
    encounter.reward = Some(reward);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_close_encounter(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    encounter.status = "closed".to_string();
    let xp_awarded = encounter.reward.as_ref().map(|r| r.xp).unwrap_or(0);

    let out = format!(
        r#"{{"id":"{}","status":"{}","xp_awarded":{}}}"#,
        escape_json_string(&encounter.id),
        escape_json_string(&encounter.status),
        xp_awarded
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_end_encounter(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    if encounter.combat_ended {
        return respond(stream, 409, r#"{"error":"campaign not in combat"}"#);
    }

    encounter.status = "closed".to_string();
    encounter.combat_ended = true;

    campaign.current_actor = Some(campaign.owner.clone());

    let out = format!(
        r#"{{"campaign_id":"{}","status":"{}","phase":"exploration","current_actor":"{}"}}"#,
        escape_json_string(&campaign.id),
        escape_json_string(&campaign.status),
        escape_json_string(campaign.current_actor.as_deref().unwrap_or(""))
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_encounter_status(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    let active = if order.is_empty() {
        "null".to_string()
    } else {
        let idx = encounter.turn_index % order.len();
        active_combatant_json(&order[idx])
    };
    let order_json: Vec<String> = order.iter().map(active_combatant_json).collect();

    let out = format!(
        r#"{{"round":{},"turn_index":{},"active":{},"order":[{}],"conditions":{}}}"#,
        encounter.round,
        encounter.turn_index,
        active,
        order_json.join(","),
        encounter_conditions_json(encounter)
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Combat actions & resting =====

pub(crate) fn handle_create_combat_action(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let encounter = match campaign.encounters.iter().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let order = turn_order(encounter);
    if order.is_empty() {
        return respond(stream, 409, r#"{"error":"no combatants"}"#);
    }
    let idx = encounter.turn_index % order.len();
    let is_current_combatant = order[idx].member.as_deref() == Some(username.as_str());
    if !is_current_combatant {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let action_type = require_str!(stream, json, "type", "invalid type");
    if action_type != "attack" && action_type != "help" && action_type != "dodge" && action_type != "ready" {
        return bad_request(stream, "invalid type");
    }
    let text = require_str!(stream, json, "text", "invalid text");
    let target = json
        .get("target")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let out = format!(
        r#"{{"sequence":{},"kind":"combat_action","actor":"{}","type":"{}","target":"{}","text":"{}"}}"#,
        sequence,
        escape_json_string(&username),
        escape_json_string(&action_type),
        escape_json_string(&target),
        escape_json_string(&text)
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_rest(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner == username {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    if campaign.current_actor.as_deref() != Some(username.as_str()) {
        return respond(stream, 409, r#"{"error":"not your turn"}"#);
    }

    let json = parsed_json!(stream, body);
    let rest_type = require_str!(stream, json, "type", "invalid type");
    if rest_type != "long" && rest_type != "short" {
        return bad_request(stream, "invalid type");
    }

    let member = campaign
        .members
        .iter_mut()
        .find(|m| m.username == username)
        .unwrap();
    if rest_type == "long" {
        member.hp_current = member.hp_max;
    }
    let hp_current = member.hp_current;
    let hp_max = member.hp_max;

    campaign.event_sequence += 1;
    let sequence = campaign.event_sequence;
    let out = format!(
        r#"{{"sequence":{},"kind":"rest","actor":"{}","type":"{}","hp_current":{},"hp_max":{},"next_actor":"{}"}}"#,
        sequence,
        escape_json_string(&username),
        escape_json_string(&rest_type),
        hp_current,
        hp_max,
        escape_json_string(&campaign.owner)
    );
    campaign.current_actor = Some(campaign.owner.clone());
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_damage_target(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    apply_hp_change(stream, auth_header, campaign_id, encounter_id, body, false)
}

pub(crate) fn handle_heal_target(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
) -> std::io::Result<()> {
    apply_hp_change(stream, auth_header, campaign_id, encounter_id, body, true)
}

// ===== HP, damage & healing =====

/// Applies a damage/heal delta to an HP total, clamping to `[0, max]`, and
/// returns `(hp_before, hp_after)`. Shared by every HP-mutating handler below
/// so the clamping rule can't drift between the monster/member/character paths.
fn clamp_hp(current: i64, max: i64, amount: i64, healing: bool) -> (i64, i64) {
    let after = if healing {
        (current + amount).min(max)
    } else {
        (current - amount).max(0)
    };
    (current, after)
}

fn apply_hp_change(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    healing: bool,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let target = require_str!(stream, json, "target", "invalid target");
    let amount = match json.get("amount").and_then(as_int) {
        Some(n) if n >= 0 => n,
        _ => return bad_request(stream, "invalid amount"),
    };

    let encounter = match campaign.encounters.iter_mut().find(|e| e.id == encounter_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"encounter not found"}"#),
    };

    let (hp_before, hp_after) = if let Some(monster) = encounter.monsters.iter_mut().find(|m| m.monster_id == target) {
        let (before, after) = clamp_hp(monster.hp_current, monster.hp_max, amount, healing);
        monster.hp_current = after;
        (before, after)
    } else if encounter.combatants.iter().any(|c| c.member == target) {
        let member = match campaign.members.iter_mut().find(|m| m.username == target) {
            Some(m) => m,
            None => return respond(stream, 404, r#"{"error":"target not found"}"#),
        };
        let (before, after) = clamp_hp(member.hp_current, member.hp_max, amount, healing);
        member.hp_current = after;
        (before, after)
    } else {
        return respond(stream, 404, r#"{"error":"target not found"}"#);
    };

    let out = if healing {
        format!(
            r#"{{"target":"{}","hp_before":{},"hp_after":{},"healing":{}}}"#,
            escape_json_string(&target),
            hp_before,
            hp_after,
            amount
        )
    } else {
        format!(
            r#"{{"target":"{}","hp_before":{},"hp_after":{},"damage":{}}}"#,
            escape_json_string(&target),
            hp_before,
            hp_after,
            amount
        )
    };
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_damage_character(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let amount = match json.get("amount").and_then(as_int) {
        Some(n) if n >= 0 => n,
        _ => return bad_request(stream, "invalid amount"),
    };

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let hp_before = member.hp_current;
    let hp_after = (hp_before - amount).max(0);
    member.hp_current = hp_after;
    if hp_after == 0 && member.status == "alive" {
        member.status = "unconscious".to_string();
        member.death_save_successes = 0;
        member.death_save_failures = 0;
    }
    let status = member.status.clone();

    let out = format!(
        r#"{{"character_id":"{}","target":"{}","hp_before":{},"hp_after":{},"damage":{},"status":"{}"}}"#,
        escape_json_string(char_id),
        escape_json_string(char_id),
        hp_before,
        hp_after,
        amount,
        escape_json_string(&status)
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_death_save(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.username != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    if member.status != "unconscious" {
        return respond(stream, 409, r#"{"error":"not unconscious"}"#);
    }

    let json = parsed_json!(stream, body);
    let outcome = require_str!(stream, json, "outcome", "invalid outcome");
    if outcome != "success" && outcome != "failure" {
        return bad_request(stream, "invalid outcome");
    }

    if outcome == "success" {
        member.death_save_successes += 1;
        if member.death_save_successes >= 3 {
            member.status = "stable".to_string();
        }
    } else {
        member.death_save_failures += 1;
        if member.death_save_failures >= 3 {
            member.status = "dead".to_string();
        }
    }

    let out = format!(
        r#"{{"character_id":"{}","successes":{},"failures":{},"status":"{}"}}"#,
        escape_json_string(char_id),
        member.death_save_successes,
        member.death_save_failures,
        escape_json_string(&member.status)
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_character_status(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = format!(
        r#"{{"character_id":"{}","hp_current":{},"hp_max":{},"status":"{}"}}"#,
        escape_json_string(char_id),
        member.hp_current,
        member.hp_max,
        escape_json_string(&member.status)
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Character ownership (claim/transfer) =====

fn owner_json(char_id: &str, owner: &str) -> String {
    format!(
        r#"{{"character_id":"{}","owner":"{}"}}"#,
        escape_json_string(char_id),
        escape_json_string(owner)
    )
}

pub(crate) fn handle_get_character_owner(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = owner_json(char_id, member.owner.as_deref().unwrap_or(""));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_claim_character(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.is_some() {
        return respond(stream, 409, r#"{"error":"character already owned"}"#);
    }

    member.owner = Some(username.clone());
    let out = owner_json(char_id, &username);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_transfer_character(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let json = parsed_json!(stream, body);
    let new_owner = require_str!(stream, json, "new_owner", "invalid new_owner");

    if !campaign.members.iter().any(|m| m.username == new_owner) {
        return bad_request(stream, "new_owner is not a campaign member");
    }

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    member.owner = Some(new_owner.clone());
    let out = owner_json(char_id, &new_owner);
    drop(store);

    respond(stream, 200, &out)
}

const VALID_RACES: &[&str] = &[
    "human",
    "elf",
    "dwarf",
    "halfling",
    "dragonborn",
    "gnome",
    "half-elf",
    "half-orc",
    "tiefling",
];

const VALID_CLASSES: &[&str] = &[
    "barbarian",
    "bard",
    "cleric",
    "druid",
    "fighter",
    "monk",
    "paladin",
    "ranger",
    "rogue",
    "sorcerer",
    "warlock",
    "wizard",
];

const VALID_BACKGROUNDS: &[&str] = &[
    "acolyte",
    "charlatan",
    "criminal",
    "entertainer",
    "folk-hero",
    "guild-artisan",
    "hermit",
    "noble",
    "outlander",
    "sage",
    "sailor",
    "soldier",
];

/// Base hit die (level-1 max HP before the CON modifier) per class.
// ===== Character creation & leveling =====

fn class_hit_die(class: &str) -> i64 {
    match class {
        "barbarian" => 12,
        "fighter" | "paladin" | "ranger" => 10,
        "sorcerer" | "wizard" => 6,
        _ => 8,
    }
}

pub(crate) fn handle_build_character(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let race = require_str!(stream, json, "race", "invalid race");
    let class = require_str!(stream, json, "class", "invalid class");
    let background = require_str!(stream, json, "background", "invalid background");

    if !VALID_RACES.contains(&race.as_str()) {
        return bad_request(stream, "invalid race");
    }
    if !VALID_CLASSES.contains(&class.as_str()) {
        return bad_request(stream, "invalid class");
    }
    if !VALID_BACKGROUNDS.contains(&background.as_str()) {
        return bad_request(stream, "invalid background");
    }

    let abilities = match json.get("abilities").and_then(|v| v.as_object()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid abilities"),
    };

    let mut scores: HashMap<&str, i64> = HashMap::new();
    for name in ["str", "dex", "con", "int", "wis", "cha"] {
        let score = match crate::json::object_get(abilities, name).and_then(as_int) {
            Some(n) if (1..=30).contains(&n) => n,
            _ => return bad_request(stream, "invalid abilities"),
        };
        scores.insert(name, score);
    }

    let con_modifier = crate::characters::ability_modifier(scores["con"]);
    let level = 1;
    let proficiency_bonus = crate::characters::proficiency_bonus(level).unwrap_or(2);
    let hp_max = class_hit_die(&class) + con_modifier;

    member.race = Some(race.clone());
    member.class = class.clone();
    member.background = Some(background.clone());
    member.level = level;
    member.proficiency_bonus = proficiency_bonus;
    member.hp_max = hp_max;
    member.hp_current = hp_max;
    member.con_modifier = con_modifier;
    for name in ["str", "dex", "con", "int", "wis", "cha"] {
        member.ability_scores.insert(name.to_string(), scores[name]);
    }

    let out = format!(
        r#"{{"character_id":"{}","race":"{}","class":"{}","background":"{}","level":{},"hp_max":{},"proficiency_bonus":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(&race),
        escape_json_string(&class),
        escape_json_string(&background),
        level,
        hp_max,
        proficiency_bonus
    );
    drop(store);

    respond(stream, 200, &out)
}

/// Deterministic (non-rolled) max-HP gain for one level beyond 1st, per the
/// 5e "fixed" hit-point-per-level table: half the hit die rounded up, plus
/// one, plus the CON modifier.
fn level_up_hp_gain(class: &str, con_modifier: i64) -> i64 {
    let hit_die = class_hit_die(class);
    (hit_die / 2 + 1) + con_modifier
}

pub(crate) fn handle_level_up_character(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let level = match json.get("level").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid level"),
    };

    if level != member.level + 1 {
        return bad_request(stream, "invalid level");
    }

    let hp_gain = level_up_hp_gain(&member.class, member.con_modifier);
    let hit_dice = format!("1d{}", class_hit_die(&member.class));
    let proficiency_bonus =
        crate::characters::proficiency_bonus(level).unwrap_or(member.proficiency_bonus);

    member.level = level;
    member.hp_max += hp_gain;
    member.hp_current += hp_gain;
    member.proficiency_bonus = proficiency_bonus;

    let out = format!(
        r#"{{"character_id":"{}","level":{},"hp_max":{},"hit_dice":"{}","proficiency_bonus":{}}}"#,
        escape_json_string(char_id),
        level,
        member.hp_max,
        escape_json_string(&hit_dice),
        proficiency_bonus
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Skill checks =====

/// Canonical governing ability for each 5e skill.
fn skill_ability(skill: &str) -> Option<&'static str> {
    match skill {
        "acrobatics" => Some("dex"),
        "animal_handling" => Some("wis"),
        "arcana" => Some("int"),
        "athletics" => Some("str"),
        "deception" => Some("cha"),
        "history" => Some("int"),
        "insight" => Some("wis"),
        "intimidation" => Some("cha"),
        "investigation" => Some("int"),
        "medicine" => Some("wis"),
        "nature" => Some("int"),
        "perception" => Some("wis"),
        "performance" => Some("cha"),
        "persuasion" => Some("cha"),
        "religion" => Some("int"),
        "sleight_of_hand" => Some("dex"),
        "stealth" => Some("dex"),
        "survival" => Some("wis"),
        _ => None,
    }
}

pub(crate) fn handle_skill_check(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let skill = require_str!(stream, json, "skill", "invalid skill");
    let ability = require_str!(stream, json, "ability", "invalid ability");

    let expected_ability = match skill_ability(&skill) {
        Some(a) => a,
        None => return bad_request(stream, "invalid skill"),
    };
    if ability != expected_ability {
        return bad_request(stream, "invalid ability");
    }

    let proficient = match json.get("proficient") {
        Some(crate::json::Json::Bool(b)) => *b,
        _ => return bad_request(stream, "invalid proficient"),
    };

    let roll = match json.get("roll").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid roll"),
    };

    let score = *member.ability_scores.get(&ability).unwrap_or(&10);
    let ability_modifier = crate::characters::ability_modifier(score);
    let modifier = ability_modifier + if proficient { member.proficiency_bonus } else { 0 };
    let total = roll + modifier;

    let out = format!(
        r#"{{"character_id":"{}","skill":"{}","ability":"{}","modifier":{},"total":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(&skill),
        escape_json_string(&ability),
        modifier,
        total
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Spellbook =====

/// Classes able to learn/prepare spells at all, per the 5e PHB spellcasting
/// class list (barbarian, fighter, monk, and rogue have no base spellcasting).
const CASTER_CLASSES: &[&str] = &[
    "bard", "cleric", "druid", "paladin", "ranger", "sorcerer", "warlock", "wizard",
];

fn spell_json(spell: &Spell) -> String {
    format!(
        r#"{{"spell_id":"{}","name":"{}","level":{}}}"#,
        escape_json_string(&spell.spell_id),
        escape_json_string(&spell.name),
        spell.level
    )
}

pub(crate) fn handle_add_spell(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let spell_id = require_str!(stream, json, "spell_id", "invalid spell_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let level = match json.get("level").and_then(as_int) {
        Some(n) if (0..=9).contains(&n) => n,
        _ => return bad_request(stream, "invalid level"),
    };

    if !CASTER_CLASSES.contains(&member.class.as_str()) {
        return bad_request(stream, "invalid class/spell combination");
    }

    if member.spells.iter().any(|s| s.spell_id == spell_id) {
        return respond(stream, 409, r#"{"error":"spell already known"}"#);
    }

    let spell = Spell {
        spell_id,
        name,
        level,
    };
    let out = spell_json(&spell);
    member.spells.push(spell);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_spells(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let spells: Vec<String> = member.spells.iter().map(spell_json).collect();
    let out = format!(r#"{{"spells":[{}]}}"#, spells.join(","));
    drop(store);

    respond(stream, 200, &out)
}

/// Maximum number of spells a caster of `level` may have prepared at once.
/// At level 1 a wizard may prepare at most one spell, so this benchmark's
/// simplified rule scales the cap 1:1 with character level.
fn max_prepared_spells(level: i64) -> i64 {
    level.max(1)
}

fn prepared_spells_json(char_id: &str, prepared: &[String], max_prepared: i64) -> String {
    let spells: Vec<String> = prepared
        .iter()
        .map(|s| format!(r#""{}""#, escape_json_string(s)))
        .collect();
    format!(
        r#"{{"character_id":"{}","prepared_spells":[{}],"max_prepared":{}}}"#,
        escape_json_string(char_id),
        spells.join(","),
        max_prepared
    )
}

pub(crate) fn handle_put_prepared_spells(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let spell_ids: Vec<String> = match json.get("spell_ids").and_then(|v| v.as_array()) {
        Some(arr) => {
            let mut ids = Vec::with_capacity(arr.len());
            for item in arr {
                match item.as_str() {
                    Some(s) => ids.push(s.to_string()),
                    None => return bad_request(stream, "invalid spell_ids"),
                }
            }
            ids
        }
        None => return bad_request(stream, "invalid spell_ids"),
    };

    if !CASTER_CLASSES.contains(&member.class.as_str()) {
        return bad_request(stream, "invalid class/spell combination");
    }

    if !spell_ids
        .iter()
        .all(|id| member.spells.iter().any(|s| &s.spell_id == id))
    {
        return bad_request(stream, "unknown spell");
    }

    let max_prepared = max_prepared_spells(member.level);
    if spell_ids.len() as i64 > max_prepared {
        return bad_request(stream, "too many prepared spells");
    }

    member.prepared_spells = spell_ids;
    let out = prepared_spells_json(char_id, &member.prepared_spells, max_prepared);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_prepared_spells(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let max_prepared = max_prepared_spells(member.level);
    let out = prepared_spells_json(char_id, &member.prepared_spells, max_prepared);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Spell casting =====

/// Number of spell slots of `spell_level` available to a caster of
/// `character_level`, per this benchmark's simplified rule: one slot per
/// spell level up to the character's own level (so a level 1 wizard has
/// exactly one first-level slot).
fn max_slots_of_level(character_level: i64, spell_level: i64) -> i64 {
    if spell_level >= 1 && spell_level <= character_level {
        1
    } else {
        0
    }
}

fn cast_json(char_id: &str, cast: &CastEvent, slots_remaining: i64) -> String {
    format!(
        r#"{{"character_id":"{}","spell_id":"{}","target":"{}","slot_level":{},"slots_remaining":{},"sequence":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(&cast.spell_id),
        escape_json_string(&cast.target),
        cast.slot_level,
        slots_remaining,
        cast.sequence
    )
}

pub(crate) fn handle_cast_spell(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let spell_id = require_str!(stream, json, "spell_id", "invalid spell_id");
    let target = require_str!(stream, json, "target", "invalid target");

    if !CASTER_CLASSES.contains(&member.class.as_str()) {
        return bad_request(stream, "invalid class/spell combination");
    }

    if !member.prepared_spells.iter().any(|s| s == &spell_id) {
        return bad_request(stream, "spell not prepared");
    }

    let spell_level = match member.spells.iter().find(|s| s.spell_id == spell_id) {
        Some(s) => s.level,
        None => return bad_request(stream, "spell not prepared"),
    };

    let max_slots = max_slots_of_level(member.level, spell_level);
    let used = *member.spell_slots_used.get(&spell_level).unwrap_or(&0);
    if used >= max_slots {
        return respond(stream, 409, r#"{"error":"no remaining spell slots"}"#);
    }

    member.spell_slots_used.insert(spell_level, used + 1);
    let sequence = member.casts.len() as i64 + 1;
    let cast = CastEvent {
        sequence,
        spell_id,
        target,
        slot_level: spell_level,
    };
    let slots_remaining = max_slots - (used + 1);
    let out = cast_json(char_id, &cast, slots_remaining);
    member.casts.push(cast);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_casts(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let casts: Vec<String> = member
        .casts
        .iter()
        .map(|c| {
            let max_slots = max_slots_of_level(member.level, c.slot_level);
            let used_through = member
                .casts
                .iter()
                .filter(|other| other.slot_level == c.slot_level && other.sequence <= c.sequence)
                .count() as i64;
            cast_json(char_id, c, max_slots - used_through)
        })
        .collect();
    let out = format!(r#"{{"casts":[{}]}}"#, casts.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Concentration =====

fn concentration_json(char_id: &str, concentration: Option<&Concentration>) -> String {
    let inner = match concentration {
        Some(c) => format!(
            r#"{{"spell_id":"{}","target":"{}","remaining_turns":{}}}"#,
            escape_json_string(&c.spell_id),
            escape_json_string(&c.target),
            c.remaining_turns
        ),
        None => "null".to_string(),
    };
    format!(
        r#"{{"character_id":"{}","concentration":{}}}"#,
        escape_json_string(char_id),
        inner
    )
}

pub(crate) fn handle_put_concentration(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let spell_id = require_str!(stream, json, "spell_id", "invalid spell_id");
    let target = require_str!(stream, json, "target", "invalid target");
    let duration_turns = match json.get("duration_turns").and_then(as_int) {
        Some(n) => n,
        None => return bad_request(stream, "invalid duration_turns"),
    };

    if !CASTER_CLASSES.contains(&member.class.as_str()) {
        return bad_request(stream, "invalid class/spell combination");
    }

    if !member.spells.iter().any(|s| s.spell_id == spell_id) {
        return bad_request(stream, "unknown spell");
    }

    if !member.prepared_spells.iter().any(|s| s == &spell_id) {
        return bad_request(stream, "spell not prepared");
    }

    if duration_turns < 1 {
        return bad_request(stream, "invalid duration_turns");
    }

    let concentration = Concentration {
        spell_id,
        target,
        remaining_turns: duration_turns,
    };
    let out = concentration_json(char_id, Some(&concentration));
    member.concentration = Some(concentration);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_concentration(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = concentration_json(char_id, member.concentration.as_ref());
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_advance_concentration_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if let Some(c) = member.concentration.as_mut() {
        c.remaining_turns -= 1;
        if c.remaining_turns <= 0 {
            member.concentration = None;
        }
    }

    let out = concentration_json(char_id, member.concentration.as_ref());
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_delete_concentration(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    member.concentration = None;
    let out = concentration_json(char_id, None);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Inventory item stacks =====

const INVENTORY_ITEM_CATALOG: &[&str] = &[
    "healing-potion",
    "torch",
    "leather-armor",
    "ring-of-protection",
    "amulet-of-health",
];

fn item_stack_json(char_id: &str, item_id: &str, quantity: i64, total_quantity: i64) -> String {
    format!(
        r#"{{"character_id":"{}","item_id":"{}","quantity":{},"total_quantity":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(item_id),
        quantity,
        total_quantity
    )
}

fn inventory_items_json(char_id: &str, items: &[ItemStack]) -> String {
    let mut sorted: Vec<&ItemStack> = items.iter().filter(|i| i.quantity > 0).collect();
    sorted.sort_by(|a, b| a.item_id.cmp(&b.item_id));
    let entries: Vec<String> = sorted
        .iter()
        .map(|i| {
            format!(
                r#"{{"item_id":"{}","quantity":{}}}"#,
                escape_json_string(&i.item_id),
                i.quantity
            )
        })
        .collect();
    format!(
        r#"{{"character_id":"{}","items":[{}]}}"#,
        escape_json_string(char_id),
        entries.join(",")
    )
}

pub(crate) fn handle_add_inventory_item(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let item_id = require_str!(stream, json, "item_id", "invalid item_id");
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid quantity"),
    };

    if !INVENTORY_ITEM_CATALOG.contains(&item_id.as_str()) {
        return bad_request(stream, "invalid item_id");
    }

    let total_quantity = match member.items.iter_mut().find(|i| i.item_id == item_id) {
        Some(stack) => {
            stack.quantity += quantity;
            stack.quantity
        }
        None => {
            member.items.push(ItemStack {
                item_id: item_id.clone(),
                quantity,
            });
            quantity
        }
    };

    let out = item_stack_json(char_id, &item_id, quantity, total_quantity);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_inventory_items(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = inventory_items_json(char_id, &member.items);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_remove_inventory_item(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    item_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let quantity = match json.get("quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid quantity"),
    };

    if !INVENTORY_ITEM_CATALOG.contains(&item_id) {
        return bad_request(stream, "invalid item_id");
    }

    let stack = match member.items.iter_mut().find(|i| i.item_id == item_id) {
        Some(s) => s,
        None => return respond(stream, 409, r#"{"error":"insufficient quantity"}"#),
    };

    if quantity > stack.quantity {
        return respond(stream, 409, r#"{"error":"insufficient quantity"}"#);
    }

    stack.quantity -= quantity;
    let total_quantity = stack.quantity;

    let out = item_stack_json(char_id, item_id, quantity, total_quantity);
    drop(store);

    respond(stream, 200, &out)
}

const CONSUMABLE_ITEMS: &[&str] = &["healing-potion"];

fn consume_response_json(char_id: &str, item_id: &str, total_quantity: i64) -> String {
    format!(
        r#"{{"character_id":"{}","item_id":"{}","quantity_consumed":1,"total_quantity":{},"effect":{{"type":"healing","hp_restored":5}}}}"#,
        escape_json_string(char_id),
        escape_json_string(item_id),
        total_quantity
    )
}

pub(crate) fn handle_consume_inventory_item(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    item_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !INVENTORY_ITEM_CATALOG.contains(&item_id) || !CONSUMABLE_ITEMS.contains(&item_id) {
        return bad_request(stream, "item is not consumable");
    }

    let stack = match member.items.iter_mut().find(|i| i.item_id == item_id) {
        Some(s) if s.quantity > 0 => s,
        _ => return respond(stream, 409, r#"{"error":"no held quantity"}"#),
    };

    stack.quantity -= 1;
    let total_quantity = stack.quantity;

    let out = consume_response_json(char_id, item_id, total_quantity);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Equipment & attunement =====

const ATTUNABLE_ACCESSORIES: &[&str] = &["ring-of-protection", "amulet-of-health"];
const MAX_ATTUNEMENTS: i64 = 1;

fn equipment_slot_for_item(item_id: &str) -> Option<&'static str> {
    match item_id {
        "leather-armor" => Some("armor"),
        "ring-of-protection" | "amulet-of-health" => Some("accessory"),
        _ => None,
    }
}

fn equipment_response_json(char_id: &str, slot: &str, item_id: &str, attuned: bool) -> String {
    format!(
        r#"{{"character_id":"{}","slot":"{}","item_id":"{}","attuned":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(slot),
        escape_json_string(item_id),
        attuned
    )
}

pub(crate) fn handle_put_equipment(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    slot: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if slot != "armor" && slot != "accessory" {
        return bad_request(stream, "invalid slot");
    }

    let json = parsed_json!(stream, body);
    let item_id = require_str!(stream, json, "item_id", "invalid item_id");

    let legal_slot = match equipment_slot_for_item(&item_id) {
        Some(s) => s,
        None => return bad_request(stream, "invalid item_id"),
    };
    if legal_slot != slot {
        return bad_request(stream, "item does not match slot");
    }

    if !member.items.iter().any(|i| i.item_id == item_id && i.quantity > 0) {
        return bad_request(stream, "item not held");
    }

    let attuned = if slot == "armor" {
        member.equipped_armor = Some(item_id.clone());
        false
    } else {
        member.equipped_accessory = Some(item_id.clone());
        member.accessory_attuned = false;
        false
    };

    let out = equipment_response_json(char_id, slot, &item_id, attuned);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_equipment(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    slot: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if slot != "armor" && slot != "accessory" {
        return bad_request(stream, "invalid slot");
    }

    let (item_id, attuned) = if slot == "armor" {
        (member.equipped_armor.clone().unwrap_or_default(), false)
    } else {
        (
            member.equipped_accessory.clone().unwrap_or_default(),
            member.accessory_attuned,
        )
    };

    let out = equipment_response_json(char_id, slot, &item_id, attuned);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_attune_equipment(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    slot: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if slot != "armor" && slot != "accessory" {
        return bad_request(stream, "invalid slot");
    }

    let item_id = if slot == "accessory" {
        member.equipped_accessory.clone()
    } else {
        None
    };

    let item_id = match item_id {
        Some(id) if ATTUNABLE_ACCESSORIES.contains(&id.as_str()) => id,
        _ => return bad_request(stream, "slot does not contain an attunable item"),
    };

    if member.accessory_attuned {
        return respond(stream, 409, r#"{"error":"already attuned"}"#);
    }

    member.accessory_attuned = true;
    let attunement_count: i64 = if member.accessory_attuned { 1 } else { 0 };

    let out = format!(
        r#"{{"character_id":"{}","slot":"{}","item_id":"{}","attuned":true,"attunement_count":{},"max_attunements":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(slot),
        escape_json_string(&item_id),
        attunement_count,
        MAX_ATTUNEMENTS
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Currency & trade =====

fn currency_json(char_id: &str, gold: i64) -> String {
    format!(
        r#"{{"character_id":"{}","gold":{}}}"#,
        escape_json_string(char_id),
        gold
    )
}

pub(crate) fn handle_get_currency(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = currency_json(char_id, member.gold);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_create_currency_transfer(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let source = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if source.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let to_character_id = require_str!(stream, json, "to_character_id", "invalid to_character_id");
    let gold = match json.get("gold").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid gold"),
    };

    if to_character_id == char_id
        || !campaign
            .members
            .iter()
            .any(|m| m.character_id == to_character_id)
    {
        return bad_request(stream, "invalid to_character_id");
    }

    let source = campaign
        .members
        .iter()
        .find(|m| m.character_id == char_id)
        .unwrap();
    if source.gold < gold {
        return respond(stream, 409, r#"{"error":"insufficient gold"}"#);
    }

    let source = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == char_id)
        .unwrap();
    source.gold -= gold;
    let from_gold = source.gold;

    let dest = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == to_character_id)
        .unwrap();
    dest.gold += gold;
    let to_gold = dest.gold;

    let transfer_id = campaign.next_transfer_id;
    campaign.next_transfer_id += 1;

    let out = format!(
        r#"{{"from_character_id":"{}","to_character_id":"{}","gold":{},"from_gold":{},"to_gold":{},"transfer_id":{}}}"#,
        escape_json_string(char_id),
        escape_json_string(&to_character_id),
        gold,
        from_gold,
        to_gold,
        transfer_id
    );
    drop(store);

    respond(stream, 201, &out)
}

// ===== Loot distribution =====

fn loot_votes_tally(loot: &LootRecord) -> Vec<(String, i64)> {
    let mut tally: Vec<(String, i64)> = Vec::new();
    for vote in &loot.votes {
        match tally
            .iter_mut()
            .find(|(id, _)| id == &vote.recipient_character_id)
        {
            Some((_, count)) => *count += 1,
            None => tally.push((vote.recipient_character_id.clone(), 1)),
        }
    }
    tally
}

fn loot_record_json(loot: &LootRecord) -> String {
    let tally = loot_votes_tally(loot);
    let votes_json = tally
        .iter()
        .map(|(id, count)| format!(r#""{}":{}"#, escape_json_string(id), count))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"loot_id":"{}","item_id":"{}","quantity":{},"status":"{}","recipient_character_id":{},"votes":{{{}}}}}"#,
        escape_json_string(&loot.loot_id),
        escape_json_string(&loot.item_id),
        loot.quantity,
        escape_json_string(&loot.status),
        match &loot.recipient_character_id {
            Some(id) => format!(r#""{}""#, escape_json_string(id)),
            None => "null".to_string(),
        },
        votes_json
    )
}

fn votes_for_recipient(loot: &LootRecord, recipient_character_id: &str) -> i64 {
    loot.votes
        .iter()
        .filter(|v| v.recipient_character_id == recipient_character_id)
        .count() as i64
}

pub(crate) fn handle_create_loot(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let loot_id = require_str!(stream, json, "loot_id", "invalid loot_id");
    let item_id = require_str!(stream, json, "item_id", "invalid item_id");
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid quantity"),
    };

    if !INVENTORY_ITEM_CATALOG.contains(&item_id.as_str()) {
        return bad_request(stream, "invalid item_id");
    }

    if campaign.loot.iter().any(|l| l.loot_id == loot_id) {
        return respond(stream, 409, r#"{"error":"loot already exists"}"#);
    }

    let record = LootRecord {
        loot_id,
        item_id,
        quantity,
        status: "open".to_string(),
        votes: Vec::new(),
        recipient_character_id: None,
    };
    let out = loot_record_json(&record);
    campaign.loot.push(record);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_loot_vote(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    loot_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let recipient_character_id = require_str!(
        stream,
        json,
        "recipient_character_id",
        "invalid recipient_character_id"
    );

    if !campaign
        .members
        .iter()
        .any(|m| m.character_id == recipient_character_id)
    {
        return bad_request(stream, "invalid recipient_character_id");
    }

    let loot = match campaign.loot.iter_mut().find(|l| l.loot_id == loot_id) {
        Some(l) => l,
        None => return respond(stream, 404, r#"{"error":"loot not found"}"#),
    };

    if loot.votes.iter().any(|v| v.voter == username) {
        return respond(stream, 409, r#"{"error":"already voted"}"#);
    }

    loot.votes.push(LootVote {
        voter: username.clone(),
        recipient_character_id: recipient_character_id.clone(),
    });
    let votes_for_recipient = votes_for_recipient(loot, &recipient_character_id);

    let out = format!(
        r#"{{"loot_id":"{}","voter":"{}","recipient_character_id":"{}","votes_for_recipient":{}}}"#,
        escape_json_string(&loot.loot_id),
        escape_json_string(&username),
        escape_json_string(&recipient_character_id),
        votes_for_recipient
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_assign_loot(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    loot_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let loot = match campaign.loot.iter().find(|l| l.loot_id == loot_id) {
        Some(l) => l,
        None => return respond(stream, 404, r#"{"error":"loot not found"}"#),
    };

    if loot.status != "open" {
        return respond(stream, 409, r#"{"error":"loot not open"}"#);
    }

    let tally = loot_votes_tally(loot);

    if tally.is_empty() {
        return respond(stream, 409, r#"{"error":"no votes"}"#);
    }

    let max_votes = tally.iter().map(|(_, count)| *count).max().unwrap();
    let top: Vec<&(String, i64)> = tally.iter().filter(|(_, count)| *count == max_votes).collect();
    if top.len() != 1 {
        return respond(stream, 409, r#"{"error":"tied vote"}"#);
    }
    let recipient_character_id = top[0].0.clone();
    let votes = top[0].1;

    let item_id = loot.item_id.clone();
    let quantity = loot.quantity;

    let member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == recipient_character_id)
        .unwrap();
    match member.items.iter_mut().find(|i| i.item_id == item_id) {
        Some(stack) => stack.quantity += quantity,
        None => member.items.push(ItemStack {
            item_id: item_id.clone(),
            quantity,
        }),
    }

    let loot = campaign
        .loot
        .iter_mut()
        .find(|l| l.loot_id == loot_id)
        .unwrap();
    loot.status = "assigned".to_string();
    loot.recipient_character_id = Some(recipient_character_id.clone());

    let out = format!(
        r#"{{"loot_id":"{}","recipient_character_id":"{}","item_id":"{}","quantity":{},"votes":{},"status":"assigned"}}"#,
        escape_json_string(loot_id),
        escape_json_string(&recipient_character_id),
        escape_json_string(&item_id),
        quantity,
        votes
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_loot(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    loot_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.members.iter().any(|m| m.username == username);
    if campaign.owner != username && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let loot = match campaign.loot.iter().find(|l| l.loot_id == loot_id) {
        Some(l) => l,
        None => return respond(stream, 404, r#"{"error":"loot not found"}"#),
    };

    let out = loot_record_json(loot);
    drop(store);

    respond(stream, 200, &out)
}

// ===== NPC agendas =====

fn npc_dm_json(npc: &Npc) -> String {
    format!(
        r#"{{"npc_id":"{}","name":"{}","agenda":"{}","public_status":"{}"}}"#,
        escape_json_string(&npc.npc_id),
        escape_json_string(&npc.name),
        escape_json_string(&npc.agenda),
        escape_json_string(&npc.public_status)
    )
}

fn npc_player_json(npc: &Npc) -> String {
    format!(
        r#"{{"npc_id":"{}","name":"{}","public_status":"{}"}}"#,
        escape_json_string(&npc.npc_id),
        escape_json_string(&npc.name),
        escape_json_string(&npc.public_status)
    )
}

pub(crate) fn handle_create_npc(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let npc_id = require_str!(stream, json, "npc_id", "invalid npc_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let agenda = require_str!(stream, json, "agenda", "invalid agenda");
    let public_status = require_str!(stream, json, "public_status", "invalid public_status");

    if campaign.npcs.iter().any(|n| n.npc_id == npc_id) {
        return respond(stream, 409, r#"{"error":"npc already exists"}"#);
    }

    let npc = Npc {
        npc_id,
        name,
        agenda,
        public_status,
        dialogue_entries: Vec::new(),
    };
    let out = npc_dm_json(&npc);
    campaign.npcs.push(npc);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_update_npc_agenda(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    npc_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let agenda = require_str!(stream, json, "agenda", "invalid agenda");
    let public_status = require_str!(stream, json, "public_status", "invalid public_status");

    let npc = match campaign.npcs.iter_mut().find(|n| n.npc_id == npc_id) {
        Some(n) => n,
        None => return respond(stream, 404, r#"{"error":"npc not found"}"#),
    };

    npc.agenda = agenda;
    npc.public_status = public_status;

    let out = npc_dm_json(npc);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_npc(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    npc_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let npc = match campaign.npcs.iter().find(|n| n.npc_id == npc_id) {
        Some(n) => n,
        None => return respond(stream, 404, r#"{"error":"npc not found"}"#),
    };

    let out = if is_dm {
        npc_dm_json(npc)
    } else {
        npc_player_json(npc)
    };
    drop(store);

    respond(stream, 200, &out)
}

fn npc_dialogue_entry_json(entry: &NpcDialogueEntry) -> String {
    format!(
        r#"{{"dialogue_id":"{}","speaker":"{}","text":"{}","visibility":"{}"}}"#,
        escape_json_string(&entry.dialogue_id),
        escape_json_string(&entry.speaker),
        escape_json_string(&entry.text),
        escape_json_string(&entry.visibility)
    )
}

pub(crate) fn handle_create_npc_dialogue(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    npc_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if !campaign.npcs.iter().any(|n| n.npc_id == npc_id) {
        return respond(stream, 404, r#"{"error":"npc not found"}"#);
    }

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let dialogue_id = require_str!(stream, json, "dialogue_id", "invalid dialogue_id");
    let speaker = require_str!(stream, json, "speaker", "invalid speaker");
    let text = require_str!(stream, json, "text", "invalid text");
    let visibility = require_str!(stream, json, "visibility", "invalid visibility");

    if visibility != "public" && visibility != "private" {
        return bad_request(stream, "invalid visibility");
    }

    let npc = campaign
        .npcs
        .iter_mut()
        .find(|n| n.npc_id == npc_id)
        .unwrap();

    if npc.dialogue_entries.iter().any(|e| e.dialogue_id == dialogue_id) {
        return respond(stream, 409, r#"{"error":"dialogue already exists"}"#);
    }

    let entry = NpcDialogueEntry {
        dialogue_id,
        speaker,
        text,
        visibility,
    };
    let out = npc_dialogue_entry_json(&entry);
    npc.dialogue_entries.push(entry);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_npc_dialogue(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    npc_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let npc = match campaign.npcs.iter().find(|n| n.npc_id == npc_id) {
        Some(n) => n,
        None => return respond(stream, 404, r#"{"error":"npc not found"}"#),
    };

    let entries_json = npc
        .dialogue_entries
        .iter()
        .filter(|e| is_dm || e.visibility == "public")
        .map(npc_dialogue_entry_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(
        r#"{{"npc_id":"{}","entries":[{}]}}"#,
        escape_json_string(npc_id),
        entries_json
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Faction reputation =====

fn faction_json(faction: &Faction) -> String {
    format!(
        r#"{{"faction_id":"{}","name":"{}"}}"#,
        escape_json_string(&faction.faction_id),
        escape_json_string(&faction.name)
    )
}

fn reputation_entry_json(faction_id: &str, entry: &ReputationEntry) -> String {
    format!(
        r#"{{"faction_id":"{}","character_id":"{}","reputation":{},"delta":{},"reason":"{}"}}"#,
        escape_json_string(faction_id),
        escape_json_string(&entry.character_id),
        entry.reputation,
        entry.delta,
        escape_json_string(&entry.reason)
    )
}

pub(crate) fn handle_create_faction(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let faction_id = require_str!(stream, json, "faction_id", "invalid faction_id");
    let name = require_str!(stream, json, "name", "invalid name");

    if campaign.factions.iter().any(|f| f.faction_id == faction_id) {
        return respond(stream, 409, r#"{"error":"faction already exists"}"#);
    }

    let faction = Faction {
        faction_id,
        name,
        reputation_entries: Vec::new(),
    };
    let out = faction_json(&faction);
    campaign.factions.push(faction);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_reputation_change(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    faction_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign.factions.iter().any(|f| f.faction_id == faction_id) {
        return respond(stream, 404, r#"{"error":"faction not found"}"#);
    }

    let json = parsed_json!(stream, body);

    let character_id = require_str!(stream, json, "character_id", "invalid character_id");
    let delta = match json.get("delta").and_then(as_int) {
        Some(n) if n != 0 && n >= -25 && n <= 25 => n,
        _ => return bad_request(stream, "invalid delta"),
    };
    let reason = require_str!(stream, json, "reason", "invalid reason");

    if !campaign.members.iter().any(|m| m.character_id == character_id) {
        return bad_request(stream, "invalid character_id");
    }

    let faction = campaign
        .factions
        .iter_mut()
        .find(|f| f.faction_id == faction_id)
        .unwrap();

    let current = faction
        .reputation_entries
        .iter()
        .rev()
        .find(|e| e.character_id == character_id)
        .map(|e| e.reputation)
        .unwrap_or(0);
    let reputation = (current + delta).clamp(-100, 100);

    let entry = ReputationEntry {
        character_id,
        reputation,
        delta,
        reason,
    };
    let out = reputation_entry_json(faction_id, &entry);
    faction.reputation_entries.push(entry);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_reputation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    faction_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let member = campaign.members.iter().find(|m| m.username == username);
    if !is_dm && member.is_none() {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let faction = match campaign.factions.iter().find(|f| f.faction_id == faction_id) {
        Some(f) => f,
        None => return respond(stream, 404, r#"{"error":"faction not found"}"#),
    };

    let entries: Vec<&ReputationEntry> = if is_dm {
        faction.reputation_entries.iter().collect()
    } else {
        let character_id = member.unwrap().character_id.clone();
        faction
            .reputation_entries
            .iter()
            .filter(|e| e.character_id == character_id)
            .collect()
    };

    let entries_json = entries
        .iter()
        .map(|e| reputation_entry_json(faction_id, e))
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(
        r#"{{"faction_id":"{}","entries":[{}]}}"#,
        escape_json_string(faction_id),
        entries_json
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Relationship graph =====

fn relationship_edge_json(edge: &RelationshipEdge) -> String {
    format!(
        r#"{{"source_id":"{}","target_id":"{}","kind":"{}","score":{}}}"#,
        escape_json_string(&edge.source_id),
        escape_json_string(&edge.target_id),
        escape_json_string(&edge.kind),
        edge.score
    )
}

fn is_campaign_entity(campaign: &PlayCampaign, id: &str) -> bool {
    campaign.members.iter().any(|m| m.character_id == id)
        || campaign.npcs.iter().any(|n| n.npc_id == id)
}

pub(crate) fn handle_create_relationship(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let source_id = require_str!(stream, json, "source_id", "invalid source_id");
    let target_id = require_str!(stream, json, "target_id", "invalid target_id");
    let kind = require_str!(stream, json, "kind", "invalid kind");
    let score = match json.get("score").and_then(as_int) {
        Some(n) if n >= -100 && n <= 100 => n,
        _ => return bad_request(stream, "invalid score"),
    };

    if source_id == target_id {
        return bad_request(stream, "source_id and target_id must differ");
    }

    if !is_campaign_entity(campaign, &source_id) {
        return respond(stream, 404, r#"{"error":"source_id not found"}"#);
    }
    if !is_campaign_entity(campaign, &target_id) {
        return respond(stream, 404, r#"{"error":"target_id not found"}"#);
    }

    if campaign
        .relationships
        .iter()
        .any(|e| e.source_id == source_id && e.target_id == target_id && e.kind == kind)
    {
        return respond(stream, 409, r#"{"error":"relationship already exists"}"#);
    }

    let edge = RelationshipEdge {
        source_id,
        target_id,
        kind,
        score,
    };
    let out = relationship_edge_json(&edge);
    campaign.relationships.push(edge);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_update_relationship(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    source_id: &str,
    target_id: &str,
    kind: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let score = match json.get("score").and_then(as_int) {
        Some(n) if n >= -100 && n <= 100 => n,
        _ => return bad_request(stream, "invalid score"),
    };

    let edge = match campaign
        .relationships
        .iter_mut()
        .find(|e| e.source_id == source_id && e.target_id == target_id && e.kind == kind)
    {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"relationship not found"}"#),
    };

    edge.score = score;

    let out = relationship_edge_json(edge);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_relationships(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let edges_json = campaign
        .relationships
        .iter()
        .map(relationship_edge_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"edges":[{}]}}"#, edges_json);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Clues =====

fn clue_json(clue: &Clue) -> String {
    match &clue.character_id {
        Some(cid) => format!(
            r#"{{"clue_id":"{}","text":"{}","audience":"{}","character_id":"{}"}}"#,
            escape_json_string(&clue.clue_id),
            escape_json_string(&clue.text),
            escape_json_string(&clue.audience),
            escape_json_string(cid)
        ),
        None => format!(
            r#"{{"clue_id":"{}","text":"{}","audience":"{}"}}"#,
            escape_json_string(&clue.clue_id),
            escape_json_string(&clue.text),
            escape_json_string(&clue.audience)
        ),
    }
}

pub(crate) fn handle_create_clue(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let clue_id = require_str!(stream, json, "clue_id", "invalid clue_id");
    let text = require_str!(stream, json, "text", "invalid text");
    let audience = require_str!(stream, json, "audience", "invalid audience");

    if audience != "character" && audience != "party" && audience != "hidden" {
        return bad_request(stream, "invalid audience");
    }

    let character_id_raw = json.get("character_id").and_then(|v| v.as_str());

    let character_id = if audience == "character" {
        match character_id_raw {
            Some(cid) if !cid.is_empty() => {
                if !campaign.members.iter().any(|m| m.character_id == cid) {
                    return bad_request(stream, "unknown character_id");
                }
                Some(cid.to_string())
            }
            _ => return bad_request(stream, "invalid character_id"),
        }
    } else {
        if character_id_raw.is_some() {
            return bad_request(stream, "character_id must be omitted");
        }
        None
    };

    if campaign.clues.iter().any(|c| c.clue_id == clue_id) {
        return respond(stream, 409, r#"{"error":"clue already exists"}"#);
    }

    let clue = Clue {
        clue_id,
        text,
        audience,
        character_id,
    };
    let out = clue_json(&clue);
    campaign.clues.push(clue);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_clues(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let member_character_id = campaign
        .members
        .iter()
        .find(|m| m.username == username)
        .map(|m| m.character_id.clone());

    if !is_dm && member_character_id.is_none() {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let visible: Vec<&Clue> = campaign
        .clues
        .iter()
        .filter(|c| {
            if is_dm {
                return true;
            }
            match c.audience.as_str() {
                "party" => true,
                "character" => c.character_id.as_deref() == member_character_id.as_deref(),
                _ => false,
            }
        })
        .collect();

    let clues_json = visible
        .into_iter()
        .map(clue_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"clues":[{}]}}"#, clues_json);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Quests =====

fn item_map_json(items: &[ItemStack]) -> String {
    let mut sorted: Vec<&ItemStack> = items.iter().collect();
    sorted.sort_by(|a, b| a.item_id.cmp(&b.item_id));
    let entries: Vec<String> = sorted
        .iter()
        .map(|i| format!(r#""{}":{}"#, escape_json_string(&i.item_id), i.quantity))
        .collect();
    format!("{{{}}}", entries.join(","))
}

fn quest_rewards_json(r: &QuestRewards) -> String {
    format!(r#"{{"xp":{},"items":{}}}"#, r.xp, item_map_json(&r.items))
}

fn play_quest_json(q: &PlayQuest) -> String {
    let deps: Vec<String> = q
        .depends_on
        .iter()
        .map(|d| format!(r#""{}""#, escape_json_string(d)))
        .collect();
    let rewards_part = match &q.rewards {
        Some(r) => format!(r#","rewards":{}"#, quest_rewards_json(r)),
        None => String::new(),
    };
    format!(
        r#"{{"quest_id":"{}","title":"{}","depends_on":[{}],"state":"{}"{}}}"#,
        escape_json_string(&q.quest_id),
        escape_json_string(&q.title),
        deps.join(","),
        escape_json_string(&q.state),
        rewards_part
    )
}

pub(crate) fn handle_create_play_quest(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let quest_id = require_str!(stream, json, "quest_id", "invalid quest_id");
    let title = require_str!(stream, json, "title", "invalid title");

    let depends_on: Vec<String> = match json.get("depends_on") {
        Some(v) => match v.as_array() {
            Some(arr) => {
                let mut deps = Vec::new();
                for item in arr {
                    match item.as_str() {
                        Some(s) if !s.is_empty() => deps.push(s.to_string()),
                        _ => return bad_request(stream, "invalid depends_on"),
                    }
                }
                deps
            }
            None => return bad_request(stream, "invalid depends_on"),
        },
        None => Vec::new(),
    };

    let mut seen = std::collections::HashSet::new();
    for d in &depends_on {
        if !seen.insert(d.as_str()) {
            return bad_request(stream, "duplicate depends_on");
        }
    }

    if depends_on.iter().any(|d| d == &quest_id) {
        return bad_request(stream, "depends_on cannot include own id");
    }

    for d in &depends_on {
        if !campaign.quests.iter().any(|q| &q.quest_id == d) {
            return bad_request(stream, "unknown dependency");
        }
    }

    if campaign.quests.iter().any(|q| q.quest_id == quest_id) {
        return respond(stream, 409, r#"{"error":"quest already exists"}"#);
    }

    let quest = PlayQuest {
        quest_id,
        title,
        depends_on,
        state: "locked".to_string(),
        rewards: None,
        rewards_awarded: false,
    };
    let out = play_quest_json(&quest);
    campaign.quests.push(quest);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_put_play_quest_state(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    quest_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign.quests.iter().any(|q| q.quest_id == quest_id) {
        return respond(stream, 404, r#"{"error":"quest not found"}"#);
    }

    let json = parsed_json!(stream, body);
    let new_state = require_str!(stream, json, "state", "invalid state");
    if new_state != "active" && new_state != "completed" {
        return bad_request(stream, "invalid state");
    }

    let current_state = campaign
        .quests
        .iter()
        .find(|q| q.quest_id == quest_id)
        .unwrap()
        .state
        .clone();

    let allowed = match (current_state.as_str(), new_state.as_str()) {
        ("locked", "active") => {
            let deps = campaign
                .quests
                .iter()
                .find(|q| q.quest_id == quest_id)
                .unwrap()
                .depends_on
                .clone();
            deps.iter().all(|d| {
                campaign
                    .quests
                    .iter()
                    .find(|q| &q.quest_id == d)
                    .map(|q| q.state == "completed")
                    .unwrap_or(false)
            })
        }
        ("active", "completed") => true,
        _ => false,
    };

    if !allowed {
        return respond(stream, 409, r#"{"error":"invalid transition"}"#);
    }

    let quest = campaign
        .quests
        .iter_mut()
        .find(|q| q.quest_id == quest_id)
        .unwrap();
    quest.state = new_state;
    let out = play_quest_json(quest);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_play_quests(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let quests_json = campaign
        .quests
        .iter()
        .map(play_quest_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"quests":[{}]}}"#, quests_json);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Quest rewards =====

pub(crate) fn handle_put_quest_rewards(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    quest_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let quest = match campaign.quests.iter().find(|q| q.quest_id == quest_id) {
        Some(q) => q,
        None => return respond(stream, 404, r#"{"error":"quest not found"}"#),
    };

    if quest.state == "completed" {
        return respond(stream, 409, r#"{"error":"quest already completed"}"#);
    }

    let json = parsed_json!(stream, body);

    let xp = match json.get("xp").and_then(as_int) {
        Some(x) if x >= 0 => x,
        _ => return bad_request(stream, "invalid xp"),
    };

    let items: Vec<ItemStack> = match json.get("items") {
        Some(v) => match v.as_object() {
            Some(obj) => {
                let mut items = Vec::new();
                for (key, val) in obj {
                    if !INVENTORY_ITEM_CATALOG.contains(&key.as_str()) {
                        return bad_request(stream, "invalid item id");
                    }
                    let quantity = match as_int(val) {
                        Some(q) if q > 0 => q,
                        _ => return bad_request(stream, "invalid item quantity"),
                    };
                    items.push(ItemStack {
                        item_id: key.clone(),
                        quantity,
                    });
                }
                items
            }
            None => return bad_request(stream, "invalid items"),
        },
        None => Vec::new(),
    };

    let quest = campaign
        .quests
        .iter_mut()
        .find(|q| q.quest_id == quest_id)
        .unwrap();
    quest.rewards = Some(QuestRewards { xp, items });
    let out = play_quest_json(quest);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_award_quest_rewards(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    quest_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let quest = match campaign.quests.iter().find(|q| q.quest_id == quest_id) {
        Some(q) => q,
        None => return respond(stream, 404, r#"{"error":"quest not found"}"#),
    };

    if quest.state != "completed" || quest.rewards.is_none() || quest.rewards_awarded {
        return respond(stream, 409, r#"{"error":"rewards not available"}"#);
    }

    let (xp, items) = {
        let rewards = quest.rewards.as_ref().unwrap();
        (rewards.xp, rewards.items.clone())
    };

    for member in campaign.members.iter_mut() {
        member.quest_reward_xp += xp;
        for item in &items {
            match member
                .quest_reward_items
                .iter_mut()
                .find(|i| i.item_id == item.item_id)
            {
                Some(stack) => stack.quantity += item.quantity,
                None => member.quest_reward_items.push(ItemStack {
                    item_id: item.item_id.clone(),
                    quantity: item.quantity,
                }),
            }
            match member.items.iter_mut().find(|i| i.item_id == item.item_id) {
                Some(stack) => stack.quantity += item.quantity,
                None => member.items.push(ItemStack {
                    item_id: item.item_id.clone(),
                    quantity: item.quantity,
                }),
            }
        }
    }

    let quest = campaign
        .quests
        .iter_mut()
        .find(|q| q.quest_id == quest_id)
        .unwrap();
    quest.rewards_awarded = true;

    let out = format!(
        r#"{{"quest_id":"{}","awarded":true,"xp":{},"items":{}}}"#,
        escape_json_string(quest_id),
        xp,
        item_map_json(&items)
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_character_rewards(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    let out = format!(
        r#"{{"character_id":"{}","xp":{},"items":{}}}"#,
        escape_json_string(char_id),
        member.quest_reward_xp,
        item_map_json(&member.quest_reward_items)
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== World events =====

fn world_event_json(e: &WorldEvent) -> String {
    let status = if e.resolution.is_some() {
        "resolved"
    } else {
        "scheduled"
    };
    let resolution_part = match &e.resolution {
        Some(r) => format!(
            r#","resolution":{{"turn_number":{},"text":"{}"}}"#,
            r.turn_number,
            escape_json_string(&r.text)
        ),
        None => String::new(),
    };
    format!(
        r#"{{"event_id":"{}","turn_number":{},"title":"{}","text":"{}","status":"{}"{}}}"#,
        escape_json_string(&e.event_id),
        e.turn_number,
        escape_json_string(&e.title),
        escape_json_string(&e.text),
        status,
        resolution_part
    )
}

pub(crate) fn handle_create_world_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let title = require_str!(stream, json, "title", "invalid title");
    let text = require_str!(stream, json, "text", "invalid text");

    let turn_number = match json.get("turn_number").and_then(as_int) {
        Some(n) if n >= campaign.turn_number => n,
        _ => return bad_request(stream, "invalid turn_number"),
    };

    if campaign.world_events.iter().any(|e| e.event_id == event_id) {
        return respond(stream, 409, r#"{"error":"world event already exists"}"#);
    }

    let event = WorldEvent {
        event_id,
        turn_number,
        title,
        text,
        resolution: None,
    };
    let out = world_event_json(&event);
    campaign.world_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_resolve_world_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    event_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let event = match campaign.world_events.iter().find(|e| e.event_id == event_id) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"world event not found"}"#),
    };

    if event.resolution.is_some() {
        return respond(stream, 409, r#"{"error":"world event already resolved"}"#);
    }

    if event.turn_number != campaign.turn_number {
        return respond(stream, 409, r#"{"error":"turn mismatch"}"#);
    }

    let json = parsed_json!(stream, body);
    let text = require_str!(stream, json, "text", "invalid text");

    let event = campaign
        .world_events
        .iter_mut()
        .find(|e| e.event_id == event_id)
        .unwrap();
    event.resolution = Some(WorldEventResolution {
        turn_number: event.turn_number,
        text,
    });
    let out = world_event_json(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_world_events(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let mut events: Vec<&WorldEvent> = campaign.world_events.iter().collect();
    events.sort_by(|a, b| a.turn_number.cmp(&b.turn_number));

    let events_json = events
        .into_iter()
        .map(world_event_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"events":[{}]}}"#, events_json);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Calendar =====

fn season_offset(season: &str) -> Option<i64> {
    match season {
        "spring" => Some(0),
        "summer" => Some(1),
        "autumn" => Some(2),
        "winter" => Some(3),
        _ => None,
    }
}

fn weather_for(day: i64, season: &str) -> &'static str {
    let offset = season_offset(season).unwrap_or(0);
    match (day + offset).rem_euclid(4) {
        0 => "clear",
        1 => "rain",
        2 => "wind",
        _ => "snow",
    }
}

fn calendar_json(cal: &Calendar) -> String {
    format!(
        r#"{{"day":{},"season":"{}","weather":"{}"}}"#,
        cal.day,
        escape_json_string(&cal.season),
        weather_for(cal.day, &cal.season)
    )
}

pub(crate) fn handle_init_calendar(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let day = match json.get("day").and_then(as_int) {
        Some(n) if n >= 1 => n,
        _ => return bad_request(stream, "invalid day"),
    };
    let season = require_str!(stream, json, "season", "invalid season");
    if season_offset(&season).is_none() {
        return bad_request(stream, "invalid season");
    }

    if campaign.calendar.is_some() {
        return respond(stream, 409, r#"{"error":"calendar already initialized"}"#);
    }

    let calendar = Calendar { day, season };
    let out = calendar_json(&calendar);
    campaign.calendar = Some(calendar);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_calendar(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let calendar = match &campaign.calendar {
        Some(c) => c,
        None => return respond(stream, 404, r#"{"error":"calendar not initialized"}"#),
    };

    let out = calendar_json(calendar);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_advance_calendar(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if campaign.calendar.is_none() {
        return respond(stream, 404, r#"{"error":"calendar not initialized"}"#);
    }

    let json = parsed_json!(stream, body);
    let days = match json.get("days").and_then(as_int) {
        Some(n) if (1..=30).contains(&n) => n,
        _ => return bad_request(stream, "invalid days"),
    };

    let calendar = campaign.calendar.as_mut().unwrap();
    calendar.day += days;
    let out = calendar_json(calendar);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Settlements =====

const VALID_AVAILABILITY: [&str; 3] = ["open", "limited", "closed"];

fn settlement_json(settlement: &Settlement, viewer_character_id: Option<&str>, is_dm: bool) -> String {
    let discovered_by: Vec<String> = if is_dm {
        settlement.discovered_by.clone()
    } else {
        match viewer_character_id {
            Some(cid) if settlement.discovered_by.iter().any(|d| d == cid) => vec![cid.to_string()],
            _ => Vec::new(),
        }
    };
    let services_json = settlement
        .services
        .iter()
        .map(|s| format!(r#""{}""#, escape_json_string(s)))
        .collect::<Vec<_>>()
        .join(",");
    let discovered_json = discovered_by
        .iter()
        .map(|d| format!(r#""{}""#, escape_json_string(d)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"settlement_id":"{}","name":"{}","services":[{}],"availability":"{}","discovered_by":[{}]}}"#,
        escape_json_string(&settlement.settlement_id),
        escape_json_string(&settlement.name),
        services_json,
        escape_json_string(&settlement.availability),
        discovered_json
    )
}

fn parse_settlement_services(json: &crate::json::Json) -> Result<Vec<String>, &'static str> {
    let arr = match json.get("services").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return Err("invalid services"),
    };
    if arr.is_empty() {
        return Err("invalid services");
    }
    let mut services = Vec::new();
    for item in arr {
        match item.as_str() {
            Some(s) => {
                let trimmed = s.trim().to_string();
                if trimmed.is_empty() {
                    return Err("invalid services");
                }
                services.push(trimmed);
            }
            None => return Err("invalid services"),
        }
    }
    let mut seen = std::collections::HashSet::new();
    for s in &services {
        if !seen.insert(s.as_str()) {
            return Err("duplicate service");
        }
    }
    Ok(services)
}

pub(crate) fn handle_create_settlement(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let settlement_id = require_str!(stream, json, "settlement_id", "invalid settlement_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let services = match parse_settlement_services(&json) {
        Ok(s) => s,
        Err(e) => return bad_request(stream, e),
    };
    let availability = require_str!(stream, json, "availability", "invalid availability");
    if !VALID_AVAILABILITY.contains(&availability.as_str()) {
        return bad_request(stream, "invalid availability");
    }

    if campaign.settlements.iter().any(|s| s.settlement_id == settlement_id) {
        return respond(stream, 409, r#"{"error":"settlement already exists"}"#);
    }

    let settlement = Settlement {
        settlement_id,
        name,
        services,
        availability,
        discovered_by: Vec::new(),
        shops: Vec::new(),
    };
    let out = settlement_json(&settlement, None, true);
    campaign.settlements.push(settlement);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_put_settlement(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign.settlements.iter().any(|s| s.settlement_id == settlement_id) {
        return respond(stream, 404, r#"{"error":"settlement not found"}"#);
    }

    let json = parsed_json!(stream, body);

    let name = require_str!(stream, json, "name", "invalid name");
    let services = match parse_settlement_services(&json) {
        Ok(s) => s,
        Err(e) => return bad_request(stream, e),
    };
    let availability = require_str!(stream, json, "availability", "invalid availability");
    if !VALID_AVAILABILITY.contains(&availability.as_str()) {
        return bad_request(stream, "invalid availability");
    }

    let settlement = campaign
        .settlements
        .iter_mut()
        .find(|s| s.settlement_id == settlement_id)
        .unwrap();
    settlement.name = name;
    settlement.services = services;
    settlement.availability = availability;
    let out = settlement_json(settlement, None, true);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_discover_settlement(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner == username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let character_id = match campaign.members.iter().find(|m| m.username == username) {
        Some(m) => m.character_id.clone(),
        None => return respond(stream, 403, r#"{"error":"forbidden"}"#),
    };

    let settlement = match campaign
        .settlements
        .iter_mut()
        .find(|s| s.settlement_id == settlement_id)
    {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"settlement not found"}"#),
    };

    let already_discovered = settlement.discovered_by.iter().any(|d| d == &character_id);
    if !already_discovered {
        settlement.discovered_by.push(character_id.clone());
    }

    let out = settlement_json(settlement, Some(&character_id), false);
    let status = if already_discovered { 200 } else { 201 };
    drop(store);

    respond(stream, status, &out)
}

pub(crate) fn handle_get_settlements(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let member_character_id = campaign
        .members
        .iter()
        .find(|m| m.username == username)
        .map(|m| m.character_id.clone());

    if !is_dm && member_character_id.is_none() {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let items: Vec<String> = if is_dm {
        campaign
            .settlements
            .iter()
            .map(|s| settlement_json(s, None, true))
            .collect()
    } else {
        let cid = member_character_id.as_deref().unwrap();
        campaign
            .settlements
            .iter()
            .filter(|s| s.discovered_by.iter().any(|d| d == cid))
            .map(|s| settlement_json(s, Some(cid), false))
            .collect()
    };

    let out = format!(r#"{{"settlements":[{}]}}"#, items.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Settlement shops =====

fn shop_json(shop: &Shop) -> String {
    let stock_json = shop
        .stock
        .iter()
        .map(|(item_id, qty)| format!(r#""{}":{}"#, escape_json_string(item_id), qty))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"shop_id":"{}","name":"{}","stock":{{{}}},"buy_price":{},"sell_price":{}}}"#,
        escape_json_string(&shop.shop_id),
        escape_json_string(&shop.name),
        stock_json,
        shop.buy_price,
        shop.sell_price
    )
}

fn parse_shop_stock(json: &crate::json::Json) -> Result<Vec<(String, i64)>, &'static str> {
    let obj = match json.get("stock").and_then(|v| v.as_object()) {
        Some(o) => o,
        None => return Err("invalid stock"),
    };
    if obj.is_empty() {
        return Err("invalid stock");
    }
    let mut stock = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for (item_id, value) in obj {
        if !INVENTORY_ITEM_CATALOG.contains(&item_id.as_str()) {
            return Err("invalid stock");
        }
        let qty = match as_int(value) {
            Some(n) if n > 0 => n,
            _ => return Err("invalid stock"),
        };
        if !seen.insert(item_id.as_str()) {
            return Err("invalid stock");
        }
        stock.push((item_id.clone(), qty));
    }
    Ok(stock)
}

pub(crate) fn handle_create_shop(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let settlement = match campaign
        .settlements
        .iter_mut()
        .find(|s| s.settlement_id == settlement_id)
    {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"settlement not found"}"#),
    };

    let json = parsed_json!(stream, body);

    let shop_id = require_str!(stream, json, "shop_id", "invalid shop_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let stock = match parse_shop_stock(&json) {
        Ok(s) => s,
        Err(e) => return bad_request(stream, e),
    };
    let buy_price = match json.get("buy_price").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid buy_price"),
    };
    let sell_price = match json.get("sell_price").and_then(as_int) {
        Some(n) if n >= 0 => n,
        _ => return bad_request(stream, "invalid sell_price"),
    };

    if settlement.shops.iter().any(|s| s.shop_id == shop_id) {
        return respond(stream, 409, r#"{"error":"shop already exists"}"#);
    }

    let shop = Shop {
        shop_id,
        name,
        stock,
        buy_price,
        sell_price,
    };
    let out = shop_json(&shop);
    settlement.shops.push(shop);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_shop(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
    shop_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let member_character_id = campaign
        .members
        .iter()
        .find(|m| m.username == username)
        .map(|m| m.character_id.clone());

    if !is_dm && member_character_id.is_none() {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let settlement = match campaign
        .settlements
        .iter()
        .find(|s| s.settlement_id == settlement_id)
    {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"settlement not found"}"#),
    };

    if !is_dm {
        let cid = member_character_id.as_deref().unwrap();
        if !settlement.discovered_by.iter().any(|d| d == cid) {
            return respond(stream, 404, r#"{"error":"shop not found"}"#);
        }
    }

    let shop = match settlement.shops.iter().find(|s| s.shop_id == shop_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"shop not found"}"#),
    };

    let out = shop_json(shop);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_buy_shop(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
    shop_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if !campaign
        .settlements
        .iter()
        .any(|s| s.settlement_id == settlement_id)
    {
        return respond(stream, 404, r#"{"error":"settlement not found"}"#);
    }
    let has_shop = campaign
        .settlements
        .iter()
        .find(|s| s.settlement_id == settlement_id)
        .map(|s| s.shops.iter().any(|sh| sh.shop_id == shop_id))
        .unwrap_or(false);
    if !has_shop {
        return respond(stream, 404, r#"{"error":"shop not found"}"#);
    }

    let json = parsed_json!(stream, body);

    let character_id = require_str!(stream, json, "character_id", "invalid character_id");
    let item_id = require_str!(stream, json, "item_id", "invalid item_id");
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid quantity"),
    };

    if !INVENTORY_ITEM_CATALOG.contains(&item_id.as_str()) {
        return bad_request(stream, "invalid item_id");
    }

    let member = match campaign
        .members
        .iter()
        .find(|m| m.character_id == character_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if campaign.owner == username || member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let settlement = campaign
        .settlements
        .iter()
        .find(|s| s.settlement_id == settlement_id)
        .unwrap();
    let shop = settlement
        .shops
        .iter()
        .find(|s| s.shop_id == shop_id)
        .unwrap();
    let stock_qty = shop
        .stock
        .iter()
        .find(|(id, _)| id == &item_id)
        .map(|(_, q)| *q)
        .unwrap_or(0);
    let cost = shop.buy_price * quantity;

    let member = campaign
        .members
        .iter()
        .find(|m| m.character_id == character_id)
        .unwrap();
    if stock_qty < quantity || member.gold < cost {
        return respond(stream, 409, r#"{"error":"insufficient stock or funds"}"#);
    }

    let settlement = campaign
        .settlements
        .iter_mut()
        .find(|s| s.settlement_id == settlement_id)
        .unwrap();
    let shop = settlement
        .shops
        .iter_mut()
        .find(|s| s.shop_id == shop_id)
        .unwrap();
    let stock_entry = shop
        .stock
        .iter_mut()
        .find(|(id, _)| id == &item_id)
        .unwrap();
    stock_entry.1 -= quantity;
    let remaining_stock = stock_entry.1;

    let member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == character_id)
        .unwrap();
    member.gold -= cost;
    let gold = member.gold;
    match member.items.iter_mut().find(|i| i.item_id == item_id) {
        Some(stack) => stack.quantity += quantity,
        None => member.items.push(ItemStack {
            item_id: item_id.clone(),
            quantity,
        }),
    }

    let out = format!(
        r#"{{"character_id":"{}","item_id":"{}","quantity":{},"gold":{},"stock":{}}}"#,
        escape_json_string(&character_id),
        escape_json_string(&item_id),
        quantity,
        gold,
        remaining_stock
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_sell_shop(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    settlement_id: &str,
    shop_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if !campaign
        .settlements
        .iter()
        .any(|s| s.settlement_id == settlement_id)
    {
        return respond(stream, 404, r#"{"error":"settlement not found"}"#);
    }
    let has_shop = campaign
        .settlements
        .iter()
        .find(|s| s.settlement_id == settlement_id)
        .map(|s| s.shops.iter().any(|sh| sh.shop_id == shop_id))
        .unwrap_or(false);
    if !has_shop {
        return respond(stream, 404, r#"{"error":"shop not found"}"#);
    }

    let json = parsed_json!(stream, body);

    let character_id = require_str!(stream, json, "character_id", "invalid character_id");
    let item_id = require_str!(stream, json, "item_id", "invalid item_id");
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid quantity"),
    };

    if !INVENTORY_ITEM_CATALOG.contains(&item_id.as_str()) {
        return bad_request(stream, "invalid item_id");
    }

    let member = match campaign
        .members
        .iter()
        .find(|m| m.character_id == character_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if campaign.owner == username || member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let held_qty = member
        .items
        .iter()
        .find(|i| i.item_id == item_id)
        .map(|i| i.quantity)
        .unwrap_or(0);
    if held_qty < quantity {
        return respond(stream, 409, r#"{"error":"insufficient inventory"}"#);
    }

    let settlement = campaign
        .settlements
        .iter()
        .find(|s| s.settlement_id == settlement_id)
        .unwrap();
    let shop = settlement
        .shops
        .iter()
        .find(|s| s.shop_id == shop_id)
        .unwrap();
    let proceeds = shop.sell_price * quantity;

    let member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == character_id)
        .unwrap();
    let stack = member
        .items
        .iter_mut()
        .find(|i| i.item_id == item_id)
        .unwrap();
    stack.quantity -= quantity;
    member.gold += proceeds;
    let gold = member.gold;

    let settlement = campaign
        .settlements
        .iter_mut()
        .find(|s| s.settlement_id == settlement_id)
        .unwrap();
    let shop = settlement
        .shops
        .iter_mut()
        .find(|s| s.shop_id == shop_id)
        .unwrap();
    let remaining_stock = match shop.stock.iter_mut().find(|(id, _)| id == &item_id) {
        Some(entry) => {
            entry.1 += quantity;
            entry.1
        }
        None => {
            shop.stock.push((item_id.clone(), quantity));
            quantity
        }
    };

    let out = format!(
        r#"{{"character_id":"{}","item_id":"{}","quantity":{},"gold":{},"stock":{}}}"#,
        escape_json_string(&character_id),
        escape_json_string(&item_id),
        quantity,
        gold,
        remaining_stock
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Crafting recipes =====

fn recipe_json(r: &Recipe) -> String {
    let ingredients: Vec<String> = r
        .ingredients
        .iter()
        .map(|(k, v)| format!(r#""{}":{}"#, escape_json_string(k), v))
        .collect();
    format!(
        r#"{{"recipe_id":"{}","name":"{}","ingredients":{{{}}},"output_item":"{}","output_quantity":{}}}"#,
        escape_json_string(&r.recipe_id),
        escape_json_string(&r.name),
        ingredients.join(","),
        escape_json_string(&r.output_item),
        r.output_quantity
    )
}

pub(crate) fn handle_create_recipe(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let recipe_id = require_str!(stream, json, "recipe_id", "invalid recipe_id");
    let name = require_str!(stream, json, "name", "invalid name");

    let ingredients_obj = match json.get("ingredients").and_then(|v| v.as_object()) {
        Some(obj) if !obj.is_empty() => obj,
        _ => return bad_request(stream, "invalid ingredients"),
    };

    let mut ingredients: Vec<(String, i64)> = Vec::new();
    for (key, value) in ingredients_obj {
        if !INVENTORY_ITEM_CATALOG.contains(&key.as_str()) {
            return bad_request(stream, "invalid ingredients");
        }
        let quantity = match as_int(value) {
            Some(n) if n > 0 => n,
            _ => return bad_request(stream, "invalid ingredients"),
        };
        ingredients.push((key.clone(), quantity));
    }

    let output_item = require_str!(stream, json, "output_item", "invalid output_item");
    if !INVENTORY_ITEM_CATALOG.contains(&output_item.as_str()) {
        return bad_request(stream, "invalid output_item");
    }

    let output_quantity = match json.get("output_quantity").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid output_quantity"),
    };

    if campaign.recipes.iter().any(|r| r.recipe_id == recipe_id) {
        return respond(stream, 409, r#"{"error":"recipe already exists"}"#);
    }

    let recipe = Recipe {
        recipe_id,
        name,
        ingredients,
        output_item,
        output_quantity,
    };
    let out = recipe_json(&recipe);
    campaign.recipes.push(recipe);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_recipes(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let recipes_json = campaign
        .recipes
        .iter()
        .map(recipe_json)
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"recipes":[{}]}}"#, recipes_json);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_craft_recipe(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    recipe_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if !campaign.recipes.iter().any(|r| r.recipe_id == recipe_id) {
        return respond(stream, 404, r#"{"error":"recipe not found"}"#);
    }

    let json = parsed_json!(stream, body);
    let character_id = require_str!(stream, json, "character_id", "invalid character_id");

    let member = match campaign
        .members
        .iter()
        .find(|m| m.character_id == character_id)
    {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if campaign.owner == username || member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let recipe = campaign
        .recipes
        .iter()
        .find(|r| r.recipe_id == recipe_id)
        .unwrap();
    let member = campaign
        .members
        .iter()
        .find(|m| m.character_id == character_id)
        .unwrap();

    for (item_id, required_qty) in &recipe.ingredients {
        let have = member
            .items
            .iter()
            .find(|i| &i.item_id == item_id)
            .map(|i| i.quantity)
            .unwrap_or(0);
        if have < *required_qty {
            return respond(stream, 409, r#"{"error":"insufficient ingredients"}"#);
        }
    }

    let output_item = recipe.output_item.clone();
    let output_quantity = recipe.output_quantity;
    let ingredients = recipe.ingredients.clone();

    let member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == character_id)
        .unwrap();

    for (item_id, required_qty) in &ingredients {
        let stack = member
            .items
            .iter_mut()
            .find(|i| &i.item_id == item_id)
            .unwrap();
        stack.quantity -= required_qty;
    }

    match member.items.iter_mut().find(|i| i.item_id == output_item) {
        Some(stack) => stack.quantity += output_quantity,
        None => member.items.push(ItemStack {
            item_id: output_item.clone(),
            quantity: output_quantity,
        }),
    }

    let out = format!(
        r#"{{"character_id":"{}","recipe_id":"{}","output_item":"{}","output_quantity":{}}}"#,
        escape_json_string(&character_id),
        escape_json_string(recipe_id),
        escape_json_string(&output_item),
        output_quantity
    );
    drop(store);

    respond(stream, 201, &out)
}

// ===== Recurring downtime =====

fn downtime_activity_json(a: &DowntimeActivity) -> String {
    format!(
        r#"{{"activity_id":"{}","name":"{}","cycles_required":{}}}"#,
        escape_json_string(&a.activity_id),
        escape_json_string(&a.name),
        a.cycles_required
    )
}

fn downtime_allocation_json(a: &DowntimeAllocation) -> String {
    format!(
        r#"{{"character_id":"{}","activity_id":"{}","cycles_completed":{},"completions":{}}}"#,
        escape_json_string(&a.character_id),
        escape_json_string(&a.activity_id),
        a.cycles_completed,
        a.completions
    )
}

pub(crate) fn handle_create_downtime_activity(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let activity_id = require_str!(stream, json, "activity_id", "invalid activity_id");
    let name = require_str!(stream, json, "name", "invalid name");
    let cycles_required = match json.get("cycles_required").and_then(as_int) {
        Some(n) if (1..=10).contains(&n) => n,
        _ => return bad_request(stream, "invalid cycles_required"),
    };

    if campaign
        .downtime_activities
        .iter()
        .any(|a| a.activity_id == activity_id)
    {
        return respond(stream, 409, r#"{"error":"activity already exists"}"#);
    }

    let activity = DowntimeActivity {
        activity_id,
        name,
        cycles_required,
    };
    let out = downtime_activity_json(&activity);
    campaign.downtime_activities.push(activity);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_downtime_allocation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let activity_id = require_str!(stream, json, "activity_id", "invalid activity_id");

    if !campaign
        .downtime_activities
        .iter()
        .any(|a| a.activity_id == activity_id)
    {
        return respond(stream, 404, r#"{"error":"activity not found"}"#);
    }

    if campaign.downtime_allocations.iter().any(|a| {
        a.character_id == char_id && a.activity_id == activity_id
    }) {
        return respond(stream, 409, r#"{"error":"allocation already exists"}"#);
    }

    let allocation = DowntimeAllocation {
        character_id: char_id.to_string(),
        activity_id,
        cycles_completed: 0,
        completions: 0,
    };
    let out = downtime_allocation_json(&allocation);
    campaign.downtime_allocations.push(allocation);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_progress_downtime_allocation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    activity_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let cycles_required = match campaign
        .downtime_activities
        .iter()
        .find(|a| a.activity_id == activity_id)
    {
        Some(a) => a.cycles_required,
        None => return respond(stream, 404, r#"{"error":"activity not found"}"#),
    };

    let allocation = match campaign
        .downtime_allocations
        .iter_mut()
        .find(|a| a.character_id == char_id && a.activity_id == activity_id)
    {
        Some(a) => a,
        None => return respond(stream, 404, r#"{"error":"allocation not found"}"#),
    };

    allocation.cycles_completed += 1;
    if allocation.cycles_completed >= cycles_required {
        allocation.cycles_completed = 0;
        allocation.completions += 1;
    }

    let out = downtime_allocation_json(allocation);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_downtime_allocation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
    activity_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign.members.iter().any(|m| m.character_id == char_id) {
        return respond(stream, 404, r#"{"error":"character not found"}"#);
    }

    if !campaign
        .downtime_activities
        .iter()
        .any(|a| a.activity_id == activity_id)
    {
        return respond(stream, 404, r#"{"error":"activity not found"}"#);
    }

    let allocation = match campaign
        .downtime_allocations
        .iter()
        .find(|a| a.character_id == char_id && a.activity_id == activity_id)
    {
        Some(a) => a,
        None => return respond(stream, 404, r#"{"error":"allocation not found"}"#),
    };

    let out = downtime_allocation_json(allocation);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Session-zero settings =====

fn parse_session_zero_consent(json: &crate::json::Json) -> Result<Vec<String>, &'static str> {
    let arr = match json.get("consent").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return Err("invalid consent"),
    };
    if arr.is_empty() {
        return Err("invalid consent");
    }
    let mut consent = Vec::new();
    for item in arr {
        match item.as_str() {
            Some(s) if !s.is_empty() => consent.push(s.to_string()),
            _ => return Err("invalid consent"),
        }
    }
    let mut seen = std::collections::HashSet::new();
    for c in &consent {
        if !seen.insert(c.as_str()) {
            return Err("invalid consent");
        }
    }
    Ok(consent)
}

fn session_zero_json(settings: &SessionZeroSettings) -> String {
    let consent_json = settings
        .consent
        .iter()
        .map(|c| format!(r#""{}""#, escape_json_string(c)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"rules":"{}","tone":"{}","consent":[{}]}}"#,
        escape_json_string(&settings.rules),
        escape_json_string(&settings.tone),
        consent_json
    )
}

pub(crate) fn handle_put_session_zero(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if campaign.status != "lobby" {
        return respond(stream, 409, r#"{"error":"campaign already started"}"#);
    }

    let json = parsed_json!(stream, body);
    let rules = require_str!(stream, json, "rules", "invalid rules");
    let tone = require_str!(stream, json, "tone", "invalid tone");
    let consent = match parse_session_zero_consent(&json) {
        Ok(c) => c,
        Err(e) => return bad_request(stream, e),
    };

    let settings = SessionZeroSettings {
        rules,
        tone,
        consent,
    };
    let out = session_zero_json(&settings);
    campaign.session_zero = Some(settings);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_session_zero(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let settings = match &campaign.session_zero {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"session-zero not set"}"#),
    };

    let out = session_zero_json(settings);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Content tags =====

fn content_json(c: &ContentRecord) -> String {
    let tags_json = c
        .tags
        .iter()
        .map(|t| format!(r#""{}""#, escape_json_string(t)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"content_id":"{}","kind":"{}","text":"{}","tags":[{}]}}"#,
        escape_json_string(&c.content_id),
        escape_json_string(&c.kind),
        escape_json_string(&c.text),
        tags_json
    )
}

fn parse_tags(
    json: &crate::json::Json,
    require_nonempty: bool,
) -> Result<Vec<String>, &'static str> {
    let arr = match json.get("tags").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return Err("invalid tags"),
    };
    if require_nonempty && arr.is_empty() {
        return Err("invalid tags");
    }
    let mut tags = Vec::new();
    for item in arr {
        match item.as_str() {
            Some(s) if !s.is_empty() => tags.push(s.to_string()),
            _ => return Err("invalid tags"),
        }
    }
    let mut seen = std::collections::HashSet::new();
    for t in &tags {
        if !seen.insert(t.as_str()) {
            return Err("invalid tags");
        }
    }
    Ok(tags)
}

pub(crate) fn handle_create_content(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let content_id = require_str!(stream, json, "content_id", "invalid content_id");
    let kind = require_str!(stream, json, "kind", "invalid kind");
    let text = require_str!(stream, json, "text", "invalid text");
    let tags = match parse_tags(&json, true) {
        Ok(t) => t,
        Err(e) => return bad_request(stream, e),
    };

    if campaign.content.iter().any(|c| c.content_id == content_id) {
        return respond(stream, 409, r#"{"error":"content already exists"}"#);
    }

    let record = ContentRecord {
        content_id,
        kind,
        text,
        tags,
    };
    let out = content_json(&record);
    campaign.content.push(record);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_put_content_tags(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    content_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let tags = match parse_tags(&json, false) {
        Ok(t) => t,
        Err(e) => return bad_request(stream, e),
    };

    let record = match campaign.content.iter_mut().find(|c| c.content_id == content_id) {
        Some(r) => r,
        None => return respond(stream, 404, r#"{"error":"content not found"}"#),
    };
    record.tags = tags;
    let out = content_json(record);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_content(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    exclude_tag: Option<&str>,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    if let Some(tag) = exclude_tag {
        if tag.is_empty() {
            return bad_request(stream, "invalid exclude_tag");
        }
    }

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let records: Vec<&ContentRecord> = campaign
        .content
        .iter()
        .filter(|c| {
            if is_dm {
                return true;
            }
            match exclude_tag {
                Some(tag) => !c.tags.iter().any(|t| t == tag),
                None => true,
            }
        })
        .collect();

    let content_json_list = records
        .iter()
        .map(|c| content_json(c))
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(r#"{{"content":[{}]}}"#, content_json_list);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Privacy controls =====

fn note_json(n: &Note) -> String {
    format!(
        r#"{{"note_id":"{}","text":"{}","visibility":"{}","owner":"{}"}}"#,
        escape_json_string(&n.note_id),
        escape_json_string(&n.text),
        escape_json_string(&n.visibility),
        escape_json_string(&n.owner)
    )
}

fn whisper_json(w: &Whisper) -> String {
    format!(
        r#"{{"whisper_id":"{}","from_character_id":"{}","to_character_id":"{}","text":"{}"}}"#,
        escape_json_string(&w.whisper_id),
        escape_json_string(&w.from_character_id),
        escape_json_string(&w.to_character_id),
        escape_json_string(&w.text)
    )
}

fn valid_visibility(v: &str) -> bool {
    v == "private" || v == "party"
}

pub(crate) fn handle_create_note(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let note_id = require_str!(stream, json, "note_id", "invalid note_id");
    let text = require_str!(stream, json, "text", "invalid text");
    let visibility = require_str!(stream, json, "visibility", "invalid visibility");
    if !valid_visibility(&visibility) {
        return bad_request(stream, "invalid visibility");
    }

    if campaign.notes.iter().any(|n| n.note_id == note_id) {
        return respond(stream, 409, r#"{"error":"note already exists"}"#);
    }

    let note = Note {
        note_id,
        text,
        visibility,
        owner: username,
    };
    let out = note_json(&note);
    campaign.notes.push(note);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_notes(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let notes: Vec<String> = campaign
        .notes
        .iter()
        .filter(|n| is_dm || n.visibility == "party" || n.owner == username)
        .map(note_json)
        .collect();

    let out = format!(r#"{{"notes":[{}]}}"#, notes.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_note(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    note_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let note = match campaign.notes.iter().find(|n| n.note_id == note_id) {
        Some(n) => n,
        None => return respond(stream, 404, r#"{"error":"note not found"}"#),
    };

    if !is_dm && note.visibility == "private" && note.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = note_json(note);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_put_note(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    note_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let text = require_str!(stream, json, "text", "invalid text");
    let visibility = require_str!(stream, json, "visibility", "invalid visibility");
    if !valid_visibility(&visibility) {
        return bad_request(stream, "invalid visibility");
    }

    let note = match campaign.notes.iter_mut().find(|n| n.note_id == note_id) {
        Some(n) => n,
        None => return respond(stream, 404, r#"{"error":"note not found"}"#),
    };

    if note.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    note.text = text;
    note.visibility = visibility;
    let out = note_json(note);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_create_whisper(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let from_character_id = match campaign
        .members
        .iter()
        .find(|m| m.owner.as_deref() == Some(username.as_str()))
    {
        Some(m) => m.character_id.clone(),
        None => return respond(stream, 403, r#"{"error":"forbidden"}"#),
    };

    let json = parsed_json!(stream, body);

    let whisper_id = require_str!(stream, json, "whisper_id", "invalid whisper_id");
    let to_character_id = require_str!(stream, json, "to_character_id", "invalid to_character_id");
    let text = require_str!(stream, json, "text", "invalid text");

    if !campaign
        .members
        .iter()
        .any(|m| m.character_id == to_character_id)
    {
        return bad_request(stream, "invalid to_character_id");
    }

    if campaign.whispers.iter().any(|w| w.whisper_id == whisper_id) {
        return respond(stream, 409, r#"{"error":"whisper already exists"}"#);
    }

    let whisper = Whisper {
        whisper_id,
        from_character_id,
        to_character_id,
        text,
    };
    let out = whisper_json(&whisper);
    campaign.whispers.push(whisper);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_whispers(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let own_character_id = campaign
        .members
        .iter()
        .find(|m| m.owner.as_deref() == Some(username.as_str()))
        .map(|m| m.character_id.clone());

    let whispers: Vec<String> = campaign
        .whispers
        .iter()
        .filter(|w| {
            if is_dm {
                return true;
            }
            match &own_character_id {
                Some(cid) => &w.from_character_id == cid || &w.to_character_id == cid,
                None => false,
            }
        })
        .map(whisper_json)
        .collect();

    let out = format!(r#"{{"whispers":[{}]}}"#, whispers.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_character_sheet(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    char_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let member = match campaign.members.iter().find(|m| m.character_id == char_id) {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"character not found"}"#),
    };

    if !is_dm && member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = format!(
        r#"{{"character_id":"{}","owner":"{}","name":"{}","class":"{}","level":1,"proficiency_bonus":2,"hp_max":10,"armor_class":10}}"#,
        escape_json_string(char_id),
        escape_json_string(member.owner.as_deref().unwrap_or("")),
        escape_json_string(&member.name),
        escape_json_string(&member.class),
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Campaign invitations =====

fn invitation_json(inv: &Invitation) -> String {
    format!(
        r#"{{"invitation_id":"{}","username":"{}","character_id":"{}","status":"{}"}}"#,
        escape_json_string(&inv.invitation_id),
        escape_json_string(&inv.username),
        escape_json_string(&inv.character_id),
        escape_json_string(&inv.status)
    )
}

pub(crate) fn handle_create_invitation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let invitation_id = require_str!(stream, json, "invitation_id", "invalid invitation_id");
    let target_username = require_str!(stream, json, "username", "invalid username");
    let character_id = require_str!(stream, json, "character_id", "invalid character_id");

    match auth::lookup_role(&target_username) {
        Some(role) if role == "player" => {}
        _ => return bad_request(stream, "invalid target username"),
    }

    if campaign
        .invitations
        .iter()
        .any(|i| i.invitation_id == invitation_id)
    {
        return respond(stream, 409, r#"{"error":"invitation already exists"}"#);
    }
    if campaign
        .invitations
        .iter()
        .any(|i| i.username == target_username && i.status == "pending")
    {
        return respond(
            stream,
            409,
            r#"{"error":"active invitation already exists for user"}"#,
        );
    }

    let invitation = Invitation {
        invitation_id,
        username: target_username,
        character_id,
        status: "pending".to_string(),
    };
    let out = invitation_json(&invitation);
    campaign.invitations.push(invitation);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_accept_invitation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    invitation_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let invitation = match campaign
        .invitations
        .iter_mut()
        .find(|i| i.invitation_id == invitation_id)
    {
        Some(i) => i,
        None => return respond(stream, 404, r#"{"error":"invitation not found"}"#),
    };

    if invitation.username != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if invitation.status != "pending" {
        return respond(stream, 409, r#"{"error":"invitation already resolved"}"#);
    }

    invitation.status = "accepted".to_string();
    let character_id = invitation.character_id.clone();
    let out = invitation_json(invitation);

    campaign.members.push(Member {
        username: username.clone(),
        character_id,
        name: String::new(),
        class: String::new(),
        hp_current: 20,
        hp_max: 20,
        status: "alive".to_string(),
        death_save_successes: 0,
        death_save_failures: 0,
        owner: Some(username),
        race: None,
        background: None,
        level: 1,
        proficiency_bonus: 2,
        con_modifier: 0,
        ability_scores: HashMap::new(),
        spells: Vec::new(),
        prepared_spells: Vec::new(),
        spell_slots_used: HashMap::new(),
        casts: Vec::new(),
        concentration: None,
        items: Vec::new(),
        equipped_armor: None,
        equipped_accessory: None,
        accessory_attuned: false,
        gold: 10,
        quest_reward_xp: 0,
        quest_reward_items: Vec::new(),
    });
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_list_invitations(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let invitations: Vec<String> = campaign
        .invitations
        .iter()
        .filter(|i| is_dm || i.username == username)
        .map(invitation_json)
        .collect();

    let out = format!(r#"{{"invitations":[{}]}}"#, invitations.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== GM delegation =====

const VALID_DELEGATION_POWERS: &[&str] = &["narrate"];

fn powers_json(powers: &[String]) -> String {
    let items: Vec<String> = powers
        .iter()
        .map(|p| format!(r#""{}""#, escape_json_string(p)))
        .collect();
    format!("[{}]", items.join(","))
}

fn delegation_json(d: &Delegation) -> String {
    format!(
        r#"{{"username":"{}","powers":{},"active":{}}}"#,
        escape_json_string(&d.username),
        powers_json(&d.powers),
        d.active
    )
}

fn delegation_audit_entry_json(e: &DelegationAuditEntry) -> String {
    format!(
        r#"{{"username":"{}","action":"{}","powers":{}}}"#,
        escape_json_string(&e.username),
        escape_json_string(&e.action),
        powers_json(&e.powers)
    )
}

pub(crate) fn handle_grant_delegation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let target_username = require_str!(stream, json, "username", "invalid username");
    let powers_value = match json.get("powers").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return bad_request(stream, "invalid powers"),
    };
    if powers_value.is_empty() {
        return bad_request(stream, "invalid powers");
    }
    let mut powers: Vec<String> = Vec::with_capacity(powers_value.len());
    for p in powers_value {
        let s = match p.as_str() {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => return bad_request(stream, "invalid powers"),
        };
        if !VALID_DELEGATION_POWERS.contains(&s.as_str()) {
            return bad_request(stream, "invalid powers");
        }
        if powers.contains(&s) {
            return bad_request(stream, "invalid powers");
        }
        powers.push(s);
    }

    if !campaign.members.iter().any(|m| m.username == target_username) {
        return bad_request(stream, "invalid username");
    }

    if campaign
        .delegations
        .iter()
        .any(|d| d.username == target_username && d.active)
    {
        return respond(stream, 409, r#"{"error":"delegation already active"}"#);
    }

    if let Some(existing) = campaign
        .delegations
        .iter_mut()
        .find(|d| d.username == target_username)
    {
        existing.active = true;
        existing.powers = powers.clone();
    } else {
        campaign.delegations.push(Delegation {
            username: target_username.clone(),
            powers: powers.clone(),
            active: true,
        });
    }
    campaign.delegation_audit.push(DelegationAuditEntry {
        username: target_username.clone(),
        action: "granted".to_string(),
        powers: powers.clone(),
    });

    let out = delegation_json(&Delegation {
        username: target_username,
        powers,
        active: true,
    });
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_revoke_delegation(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    target_username: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let delegation = match campaign
        .delegations
        .iter_mut()
        .find(|d| d.username == target_username && d.active)
    {
        Some(d) => d,
        None => return respond(stream, 404, r#"{"error":"delegation not found"}"#),
    };

    delegation.active = false;
    let out = delegation_json(delegation);
    let powers = delegation.powers.clone();
    campaign.delegation_audit.push(DelegationAuditEntry {
        username: target_username.to_string(),
        action: "revoked".to_string(),
        powers,
    });
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_delegation_audit(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let entries: Vec<String> = campaign
        .delegation_audit
        .iter()
        .map(delegation_audit_entry_json)
        .collect();
    let out = format!(r#"{{"entries":[{}]}}"#, entries.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Actor audit trail =====

fn audit_entry_json(e: &AuditEntry) -> String {
    format!(
        r#"{{"kind":"{}","actor":"{}","role":"{}","timestamp":{},"correlation_id":"{}"}}"#,
        escape_json_string(&e.kind),
        escape_json_string(&e.actor),
        escape_json_string(&e.role),
        e.timestamp,
        escape_json_string(&e.correlation_id)
    )
}

pub(crate) fn handle_create_audit_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let kind = require_str!(stream, json, "kind", "invalid kind");
    let correlation_id = require_str!(stream, json, "correlation_id", "invalid correlation_id");

    if campaign
        .audit_log
        .iter()
        .any(|e| e.correlation_id == correlation_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate correlation_id"}"#);
    }

    campaign.audit_sequence += 1;
    let timestamp = campaign.audit_sequence;
    let role = if is_owner { "DM" } else { "player" }.to_string();

    let entry = AuditEntry {
        kind,
        actor: username,
        role,
        timestamp,
        correlation_id,
    };
    let out = audit_entry_json(&entry);
    campaign.audit_log.push(entry);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_audit_events(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let entries: Vec<String> = campaign.audit_log.iter().map(audit_entry_json).collect();
    let out = format!(r#"{{"entries":[{}]}}"#, entries.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Event projections =====

fn projection_event_json(e: &ProjectionEvent) -> String {
    match &e.value {
        Some(v) => format!(
            r#"{{"sequence":{},"event_id":"{}","kind":"{}","value":"{}"}}"#,
            e.sequence,
            escape_json_string(&e.event_id),
            escape_json_string(&e.kind),
            escape_json_string(v)
        ),
        None => format!(
            r#"{{"sequence":{},"event_id":"{}","kind":"{}"}}"#,
            e.sequence,
            escape_json_string(&e.event_id),
            escape_json_string(&e.kind)
        ),
    }
}

fn build_projection_json(events: &[ProjectionEvent]) -> String {
    let mut story = String::new();
    let mut danger: i64 = 0;
    let mut applied_event_ids: Vec<String> = Vec::new();
    for e in events {
        match e.kind.as_str() {
            "set-story" => {
                story = e.value.clone().unwrap_or_default();
            }
            "increment-danger" => {
                danger += 1;
            }
            _ => {}
        }
        applied_event_ids.push(e.event_id.clone());
    }
    let ids: Vec<String> = applied_event_ids
        .iter()
        .map(|id| format!(r#""{}""#, escape_json_string(id)))
        .collect();
    format!(
        r#"{{"story":"{}","danger":{},"applied_event_ids":[{}]}}"#,
        escape_json_string(&story),
        danger,
        ids.join(",")
    )
}

pub(crate) fn handle_create_projection_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if is_owner || !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let kind = require_str!(stream, json, "kind", "invalid kind");
    if kind != "set-story" && kind != "increment-danger" {
        return bad_request(stream, "invalid kind");
    }

    let value = match kind.as_str() {
        "set-story" => match json.get("value").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => Some(s.to_string()),
            _ => return bad_request(stream, "invalid value"),
        },
        _ => {
            if json.get("value").is_some() {
                return bad_request(stream, "value must be omitted");
            }
            None
        }
    };

    if campaign
        .projection_events
        .iter()
        .any(|e| e.event_id == event_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate event_id"}"#);
    }

    campaign.projection_sequence += 1;
    let sequence = campaign.projection_sequence;

    let event = ProjectionEvent {
        sequence,
        event_id,
        kind,
        value,
    };
    let out = projection_event_json(&event);
    campaign.projection_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_projection(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_owner && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = build_projection_json(&campaign.projection_events);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_rebuild_projection(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_owner && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = build_projection_json(&campaign.projection_events);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Idempotency keys =====

fn idempotent_event_json(e: &IdempotentEvent) -> String {
    format!(
        r#"{{"event_id":"{}","value":"{}","sequence":{},"idempotency_key":"{}"}}"#,
        escape_json_string(&e.event_id),
        escape_json_string(&e.value),
        e.sequence,
        escape_json_string(&e.idempotency_key)
    )
}

pub(crate) fn handle_create_idempotent_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
    idempotency_key: Option<&str>,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let idempotency_key = match idempotency_key {
        Some(k) if !k.trim().is_empty() => k.trim().to_string(),
        _ => return bad_request(stream, "missing idempotency key"),
    };

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let value = require_str!(stream, json, "value", "invalid value");

    if let Some(existing) = campaign
        .idempotent_events
        .iter()
        .find(|e| e.idempotency_key == idempotency_key)
    {
        if existing.event_id == event_id && existing.value == value {
            let out = idempotent_event_json(existing);
            drop(store);
            return respond(stream, 200, &out);
        }
        return respond(stream, 409, r#"{"error":"idempotency key conflict"}"#);
    }

    if campaign
        .idempotent_events
        .iter()
        .any(|e| e.event_id == event_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate event_id"}"#);
    }

    campaign.idempotent_sequence += 1;
    let sequence = campaign.idempotent_sequence;

    let event = IdempotentEvent {
        event_id,
        value,
        sequence,
        idempotency_key,
    };
    let out = idempotent_event_json(&event);
    campaign.idempotent_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_idempotent_events(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let mut events: Vec<&IdempotentEvent> = campaign.idempotent_events.iter().collect();
    events.sort_by_key(|e| e.sequence);
    let items: Vec<String> = events.iter().map(|e| idempotent_event_json(e)).collect();
    let out = format!(r#"{{"events":[{}]}}"#, items.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Concurrent turn safety =====

fn safe_turn_accept_json(a: &SafeTurnAcceptance) -> String {
    format!(
        r#"{{"submission_id":"{}","action":"{}","accepted_turn":{},"next_turn":{}}}"#,
        escape_json_string(&a.submission_id),
        escape_json_string(&a.action),
        a.accepted_turn,
        a.next_turn
    )
}

pub(crate) fn handle_submit_safe_turn(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let submission_id = require_str!(stream, json, "submission_id", "invalid submission_id");
    let action = require_str!(stream, json, "action", "invalid action");
    let expected_turn = match json.get("expected_turn").and_then(as_int) {
        Some(n) if n >= 1 => n,
        _ => return bad_request(stream, "invalid expected_turn"),
    };

    if campaign
        .safe_turn_accepted
        .iter()
        .any(|a| a.submission_id == submission_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate submission_id"}"#);
    }

    if expected_turn != campaign.safe_turn_current {
        let out = format!(r#"{{"current_turn":{}}}"#, campaign.safe_turn_current);
        drop(store);
        return respond(stream, 409, &out);
    }

    let accepted_turn = campaign.safe_turn_current;
    let next_turn = accepted_turn + 1;
    campaign.safe_turn_current = next_turn;

    let acceptance = SafeTurnAcceptance {
        submission_id,
        action,
        accepted_turn,
        next_turn,
    };
    let out = safe_turn_accept_json(&acceptance);
    campaign.safe_turn_accepted.push(acceptance);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_safe_turns(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let items: Vec<String> = campaign
        .safe_turn_accepted
        .iter()
        .map(safe_turn_accept_json)
        .collect();
    let out = format!(
        r#"{{"current_turn":{},"accepted":[{}]}}"#,
        campaign.safe_turn_current,
        items.join(",")
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== Transaction recovery =====

fn transactional_transfer_json(t: &TransactionalTransfer) -> String {
    format!(
        r#"{{"from_character_id":"{}","to_character_id":"{}","amount":{},"from_gold":{},"to_gold":{},"sequence":{}}}"#,
        escape_json_string(&t.from_character_id),
        escape_json_string(&t.to_character_id),
        t.amount,
        t.from_gold,
        t.to_gold,
        t.sequence
    )
}

pub(crate) fn handle_create_transactional_transfer(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let from_character_id = require_str!(stream, json, "from_character_id", "invalid from_character_id");
    let to_character_id = require_str!(stream, json, "to_character_id", "invalid to_character_id");
    let amount = match json.get("amount").and_then(as_int) {
        Some(n) if n > 0 => n,
        _ => return bad_request(stream, "invalid amount"),
    };
    let simulate_failure = match json.get("simulate_failure") {
        Some(crate::json::Json::Bool(b)) => *b,
        _ => false,
    };

    if from_character_id == to_character_id {
        return bad_request(stream, "invalid to_character_id");
    }

    let from_member = match campaign
        .members
        .iter()
        .find(|m| m.character_id == from_character_id)
    {
        Some(m) => m,
        None => return bad_request(stream, "invalid from_character_id"),
    };

    if from_member.owner.as_deref() != Some(username.as_str()) {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign
        .members
        .iter()
        .any(|m| m.character_id == to_character_id)
    {
        return bad_request(stream, "invalid to_character_id");
    }

    let from_member = campaign
        .members
        .iter()
        .find(|m| m.character_id == from_character_id)
        .unwrap();
    if from_member.gold < amount {
        return respond(stream, 409, r#"{"error":"insufficient gold"}"#);
    }

    if simulate_failure {
        drop(store);
        return respond(stream, 500, r#"{"error":"simulated failure"}"#);
    }

    let from_member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == from_character_id)
        .unwrap();
    from_member.gold -= amount;
    let from_gold = from_member.gold;

    let to_member = campaign
        .members
        .iter_mut()
        .find(|m| m.character_id == to_character_id)
        .unwrap();
    to_member.gold += amount;
    let to_gold = to_member.gold;

    campaign.transactional_transfer_sequence += 1;
    let sequence = campaign.transactional_transfer_sequence;

    let transfer = TransactionalTransfer {
        from_character_id,
        to_character_id,
        amount,
        from_gold,
        to_gold,
        sequence,
    };
    let out = transactional_transfer_json(&transfer);
    campaign.transactional_transfers.push(transfer);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_transactional_transfers(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_owner = campaign.owner == username;
    let is_member = is_owner || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let mut transfers: Vec<&TransactionalTransfer> = campaign.transactional_transfers.iter().collect();
    transfers.sort_by_key(|t| t.sequence);
    let items: Vec<String> = transfers
        .iter()
        .map(|t| transactional_transfer_json(t))
        .collect();
    let out = format!(r#"{{"transfers":[{}]}}"#, items.join(","));
    drop(store);

    respond(stream, 200, &out)
}

// ===== Versioned campaign exports =====

fn campaign_export_json(e: &CampaignExport) -> String {
    format!(
        r#"{{"version":{},"story":"{}","status":"{}"}}"#,
        e.version,
        escape_json_string(&e.story),
        escape_json_string(&e.status)
    )
}

pub(crate) fn handle_create_export(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let version = campaign.exports.len() as i64 + 1;
    let export = CampaignExport {
        version,
        story: campaign.document.story.clone(),
        status: campaign.status.clone(),
    };
    let out = campaign_export_json(&export);
    campaign.exports.push(export);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_exports(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let items: Vec<String> = campaign.exports.iter().map(campaign_export_json).collect();
    let out = format!(r#"{{"exports":[{}]}}"#, items.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_export(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    version: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let version_num: i64 = match version.parse() {
        Ok(n) => n,
        Err(_) => return respond(stream, 404, r#"{"error":"export not found"}"#),
    };

    let export = match campaign.exports.iter().find(|e| e.version == version_num) {
        Some(e) => e,
        None => return respond(stream, 404, r#"{"error":"export not found"}"#),
    };
    let out = campaign_export_json(export);
    drop(store);

    respond(stream, 200, &out)
}

// ===== DM-only campaign imports =====

pub(crate) fn handle_create_import(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let version = match json.get("version").and_then(as_int) {
        Some(1) => 1,
        _ => return bad_request(stream, "invalid version"),
    };
    let story = require_str!(stream, json, "story", "invalid story");
    let status = require_str!(stream, json, "status", "invalid status");
    if status != "lobby" && status != "started" {
        return bad_request(stream, "invalid status");
    }

    let import = CampaignExport {
        version,
        story,
        status,
    };
    let out = campaign_export_json(&import);

    campaign.document.story = import.story.clone();
    campaign.status = import.status.clone();
    campaign.imported_state = Some(import);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_import_state(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let import = match &campaign.imported_state {
        Some(i) => i,
        None => return respond(stream, 404, r#"{"error":"import not found"}"#),
    };
    let out = campaign_export_json(import);
    drop(store);

    respond(stream, 200, &out)
}

// ===== DM-only campaign schema migrations =====

pub(crate) struct MigratedState {
    schema_version: i64,
    story: String,
    campaign_name: String,
}

fn migrated_state_json(m: &MigratedState) -> String {
    format!(
        r#"{{"schema_version":{},"story":"{}","campaign_name":"{}"}}"#,
        m.schema_version,
        escape_json_string(&m.story),
        escape_json_string(&m.campaign_name)
    )
}

pub(crate) fn handle_create_migration(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let schema_version = match json.get("schema_version").and_then(as_int) {
        Some(1) => 1,
        _ => return bad_request(stream, "invalid schema_version"),
    };
    let story = require_str!(stream, json, "story", "invalid story");

    if let Some((prev_version, prev_story)) = &campaign.migration_source {
        if *prev_version == schema_version && *prev_story == story {
            let out = migrated_state_json(campaign.migrated_state.as_ref().unwrap());
            drop(store);
            return respond(stream, 200, &out);
        }
    }

    let migrated = MigratedState {
        schema_version: 2,
        story: story.clone(),
        campaign_name: campaign.name.clone(),
    };
    let out = migrated_state_json(&migrated);

    campaign.migration_source = Some((schema_version, story));
    campaign.migrated_state = Some(migrated);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_migration_state(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let migrated = match &campaign.migrated_state {
        Some(m) => m,
        None => return respond(stream, 404, r#"{"error":"migration not found"}"#),
    };
    let out = migrated_state_json(migrated);
    drop(store);

    respond(stream, 200, &out)
}

fn search_record_json(r: &SearchRecord) -> String {
    format!(
        r#"{{"record_id":"{}","text":"{}"}}"#,
        escape_json_string(&r.record_id),
        escape_json_string(&r.text)
    )
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
                match hex.and_then(|h| u8::from_str_radix(h, 16).ok()) {
                    Some(byte) => {
                        out.push(byte);
                        i += 3;
                    }
                    None => {
                        out.push(bytes[i]);
                        i += 1;
                    }
                }
            }
            b'+' => {
                out.push(b' ');
                i += 1;
            }
            b => {
                out.push(b);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

pub(crate) fn handle_create_search_record(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);

    let record_id = require_str!(stream, json, "record_id", "invalid record_id");
    let text = require_str!(stream, json, "text", "invalid text");

    if campaign.search_records.iter().any(|r| r.record_id == record_id) {
        return bad_request(stream, "record_id already exists");
    }

    if campaign.search_records.iter().any(|r| r.text == text) {
        return bad_request(stream, "text already exists");
    }

    let record = SearchRecord { record_id, text };
    let out = search_record_json(&record);
    campaign.search_records.push(record);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_search_records(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    q: Option<&str>,
    limit: Option<&str>,
    cursor: Option<&str>,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let limit_val: i64 = match limit {
        Some(v) => match v.parse::<i64>() {
            Ok(n) if (1..=3).contains(&n) => n,
            _ => return bad_request(stream, "invalid limit"),
        },
        None => 2,
    };
    let cursor_val: i64 = match cursor {
        Some(v) => match v.parse::<i64>() {
            Ok(n) if n >= 0 => n,
            _ => return bad_request(stream, "invalid cursor"),
        },
        None => 0,
    };

    let query = q.map(percent_decode).map(|s| s.to_lowercase());

    let filtered: Vec<&SearchRecord> = campaign
        .search_records
        .iter()
        .filter(|r| match &query {
            Some(needle) => r.text.to_lowercase().contains(needle.as_str()),
            None => true,
        })
        .collect();

    let start = cursor_val as usize;
    let end = filtered.len();
    let page: Vec<String> = filtered
        .iter()
        .skip(start)
        .take(limit_val as usize)
        .map(|r| search_record_json(r))
        .collect();

    let next_cursor = start + page.len();
    let next_cursor_str = if next_cursor < end {
        next_cursor.to_string()
    } else {
        "null".to_string()
    };

    let out = format!(
        r#"{{"records":[{}],"next_cursor":{}}}"#,
        page.join(","),
        next_cursor_str
    );
    drop(store);

    respond(stream, 200, &out)
}

const RATE_EVENT_LIMIT: i64 = 2;

fn rate_event_json(r: &RateEvent) -> String {
    format!(
        r#"{{"event_id":"{}","actor":"{}"}}"#,
        escape_json_string(&r.event_id),
        escape_json_string(&r.actor)
    )
}

pub(crate) fn handle_create_rate_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");

    if campaign.rate_events.iter().any(|r| r.event_id == event_id) {
        return bad_request(stream, "event_id already exists");
    }

    let accepted_count = campaign
        .rate_events
        .iter()
        .filter(|r| r.actor == username)
        .count() as i64;

    if accepted_count >= RATE_EVENT_LIMIT {
        campaign.rejected_rate_events += 1;
        let out = format!(
            r#"{{"limit":{},"remaining":0}}"#,
            RATE_EVENT_LIMIT
        );
        drop(store);
        return respond(stream, 429, &out);
    }

    let remaining = RATE_EVENT_LIMIT - (accepted_count + 1);
    let event = RateEvent {
        event_id,
        actor: username,
    };
    let out = format!(
        r#"{{"event_id":"{}","actor":"{}","remaining":{}}}"#,
        escape_json_string(&event.event_id),
        escape_json_string(&event.actor),
        remaining
    );
    campaign.rate_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_rate_events(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let accepted_count = campaign
        .rate_events
        .iter()
        .filter(|r| r.actor == username)
        .count() as i64;
    let remaining = (RATE_EVENT_LIMIT - accepted_count).max(0);

    let events: Vec<String> = campaign.rate_events.iter().map(rate_event_json).collect();
    let out = format!(
        r#"{{"events":[{}],"remaining":{}}}"#,
        events.join(","),
        remaining
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_service_metrics(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let accepted_rate_events = campaign.rate_events.len() as i64;
    let rejected_rate_events = campaign.rejected_rate_events;
    let projection_events = campaign.projection_events.len() as i64;

    let out = format!(
        r#"{{"accepted_rate_events":{},"rejected_rate_events":{},"projection_events":{},"uptime_ticks":1}}"#,
        accepted_rate_events, rejected_rate_events, projection_events
    );
    drop(store);

    respond(stream, 200, &out)
}

// ===== DM-only campaign backups =====

fn campaign_backup_json(b: &CampaignBackup) -> String {
    format!(
        r#"{{"backup_id":"{}","story":"{}","status":"{}"}}"#,
        escape_json_string(&b.backup_id),
        escape_json_string(&b.story),
        escape_json_string(&b.status)
    )
}

pub(crate) fn handle_create_backup(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let backup_id = format!("backup-{}", campaign.backups.len() + 1);
    let backup = CampaignBackup {
        backup_id,
        story: campaign.document.story.clone(),
        status: campaign.status.clone(),
    };
    let out = campaign_backup_json(&backup);
    campaign.backups.push(backup);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_backups(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let items: Vec<String> = campaign.backups.iter().map(campaign_backup_json).collect();
    let out = format!(r#"{{"backups":[{}]}}"#, items.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_restore_backup(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    backup_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let (story, status) = match campaign.backups.iter().find(|b| b.backup_id == backup_id) {
        Some(b) => (b.story.clone(), b.status.clone()),
        None => return respond(stream, 404, r#"{"error":"backup not found"}"#),
    };

    campaign.document.story = story.clone();
    campaign.status = status.clone();

    let out = campaign_backup_json(&CampaignBackup {
        backup_id: backup_id.to_string(),
        story,
        status,
    });
    drop(store);

    respond(stream, 200, &out)
}

// ===== Deterministic replay =====

fn replay_event_json(e: &ReplayEvent) -> String {
    format!(
        r#"{{"event_id":"{}","kind":"{}","text":"{}","sequence":{}}}"#,
        escape_json_string(&e.event_id),
        escape_json_string(&e.kind),
        escape_json_string(&e.text),
        e.sequence
    )
}

fn build_replay_json(events: &[ReplayEvent]) -> String {
    let mut story = String::new();
    let mut event_ids: Vec<String> = Vec::new();
    for e in events {
        story.push_str(&e.text);
        event_ids.push(e.event_id.clone());
    }
    let digest = format!("{}|{}", event_ids.join(","), story);
    let ids: Vec<String> = event_ids
        .iter()
        .map(|id| format!(r#""{}""#, escape_json_string(id)))
        .collect();
    format!(
        r#"{{"story":"{}","event_ids":[{}],"digest":"{}"}}"#,
        escape_json_string(&story),
        ids.join(","),
        escape_json_string(&digest)
    )
}

pub(crate) fn handle_append_replay_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let kind = require_str!(stream, json, "kind", "invalid kind");
    let text = require_str!(stream, json, "text", "invalid text");
    if kind != "append" {
        return bad_request(stream, "invalid kind");
    }

    if campaign.replay_events.iter().any(|e| e.event_id == event_id) {
        return respond(stream, 409, r#"{"error":"duplicate event_id"}"#);
    }

    campaign.replay_sequence += 1;
    let sequence = campaign.replay_sequence;

    let event = ReplayEvent {
        sequence,
        event_id,
        kind,
        text,
    };
    let out = replay_event_json(&event);
    campaign.replay_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_replay(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = build_replay_json(&campaign.replay_events);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_check_replay(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = build_replay_json(&campaign.replay_events);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Deterministic RNG ledger =====

fn rng_roll_json(r: &RngRoll) -> String {
    format!(
        r#"{{"roll_id":"{}","sides":{},"result":{},"sequence":{}}}"#,
        escape_json_string(&r.roll_id),
        r.sides,
        r.result,
        r.sequence
    )
}

fn build_rng_ledger_json(seed: &Option<String>, rolls: &[RngRoll]) -> String {
    let seed_json = match seed {
        Some(s) => format!(r#""{}""#, escape_json_string(s)),
        None => "null".to_string(),
    };
    let rolls_json: Vec<String> = rolls.iter().map(rng_roll_json).collect();
    format!(
        r#"{{"seed":{},"rolls":[{}]}}"#,
        seed_json,
        rolls_json.join(",")
    )
}

fn compute_rng_roll(seed: &str, sequence: i64, roll_id: &str, sides: i64) -> i64 {
    let bytes = format!("{}|{}|{}|{}", seed, sequence, roll_id, sides);
    let mut acc: u32 = 0;
    for b in bytes.as_bytes() {
        acc = acc.wrapping_mul(31).wrapping_add(*b as u32);
    }
    (acc % sides as u32) as i64 + 1
}

pub(crate) fn handle_put_rng_seed(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let seed = require_str!(stream, json, "seed", "invalid seed");

    if campaign.rng_seed.is_some() {
        return respond(stream, 409, r#"{"error":"seed already configured"}"#);
    }

    campaign.rng_seed = Some(seed);
    let out = build_rng_ledger_json(&campaign.rng_seed, &campaign.rng_rolls);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_append_rng_roll(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let seed = match &campaign.rng_seed {
        Some(s) => s.clone(),
        None => return respond(stream, 409, r#"{"error":"seed not configured"}"#),
    };

    let json = parsed_json!(stream, body);
    let roll_id = require_str!(stream, json, "roll_id", "invalid roll_id");
    let sides = match json.get("sides").and_then(as_int) {
        Some(s) if (2..=100).contains(&s) => s,
        _ => return bad_request(stream, "invalid sides"),
    };

    if campaign.rng_rolls.iter().any(|r| r.roll_id == roll_id) {
        return respond(stream, 409, r#"{"error":"duplicate roll_id"}"#);
    }

    let sequence = campaign.rng_sequence + 1;
    let result = compute_rng_roll(&seed, sequence, &roll_id, sides);

    let roll = RngRoll {
        roll_id,
        sides,
        result,
        sequence,
    };
    let out = rng_roll_json(&roll);
    campaign.rng_sequence = sequence;
    campaign.rng_rolls.push(roll);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_rng_ledger(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = build_rng_ledger_json(&campaign.rng_seed, &campaign.rng_rolls);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Moderation workflow =====

fn moderation_report_json(r: &ModerationReport) -> String {
    let mut fields = format!(
        r#""report_id":"{}","target_id":"{}","reason":"{}","status":"{}","reporter":"{}","sequence":{}"#,
        escape_json_string(&r.report_id),
        escape_json_string(&r.target_id),
        escape_json_string(&r.reason),
        escape_json_string(&r.status),
        escape_json_string(&r.reporter),
        r.sequence
    );
    if let Some(action) = &r.action {
        fields.push_str(&format!(r#","action":"{}""#, escape_json_string(action)));
    }
    if let Some(note) = &r.note {
        fields.push_str(&format!(r#","note":"{}""#, escape_json_string(note)));
    }
    if let Some(resolver) = &r.resolver {
        fields.push_str(&format!(r#","resolver":"{}""#, escape_json_string(resolver)));
    }
    format!("{{{}}}", fields)
}

pub(crate) fn handle_create_moderation_report(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let report_id = require_str!(stream, json, "report_id", "invalid report_id");
    let target_id = require_str!(stream, json, "target_id", "invalid target_id");
    let reason = require_str!(stream, json, "reason", "invalid reason");

    if campaign
        .moderation_reports
        .iter()
        .any(|r| r.report_id == report_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate report_id"}"#);
    }

    let sequence = campaign.moderation_sequence + 1;
    let report = ModerationReport {
        report_id,
        target_id,
        reason,
        status: "open".to_string(),
        reporter: username,
        sequence,
        action: None,
        note: None,
        resolver: None,
    };
    let out = moderation_report_json(&report);
    campaign.moderation_sequence = sequence;
    campaign.moderation_reports.push(report);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_moderation_reports(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let reports_json: Vec<String> = campaign
        .moderation_reports
        .iter()
        .map(moderation_report_json)
        .collect();
    let out = format!(r#"{{"reports":[{}]}}"#, reports_json.join(","));
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_resolve_moderation_report(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    report_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let action = require_str!(stream, json, "action", "invalid action");
    if action != "allow" && action != "remove" {
        return bad_request(stream, "invalid action");
    }
    let note = require_str!(stream, json, "note", "invalid note");

    let report = match campaign
        .moderation_reports
        .iter_mut()
        .find(|r| r.report_id == report_id)
    {
        Some(r) => r,
        None => return respond(stream, 404, r#"{"error":"report not found"}"#),
    };

    if report.status != "open" {
        return respond(stream, 409, r#"{"error":"report already resolved"}"#);
    }

    report.status = "resolved".to_string();
    report.action = Some(action);
    report.note = Some(note);
    report.resolver = Some("dm".to_string());

    let out = moderation_report_json(report);
    drop(store);

    respond(stream, 200, &out)
}

// ===== Safety boundaries =====

fn safety_boundaries_json(tags: &[String]) -> String {
    let mut sorted: Vec<&String> = tags.iter().collect();
    sorted.sort();
    let tags_json = sorted
        .iter()
        .map(|t| format!(r#""{}""#, escape_json_string(t)))
        .collect::<Vec<_>>()
        .join(",");
    format!(r#"{{"blocked_tags":[{}]}}"#, tags_json)
}

fn safety_event_json(e: &SafetyEvent) -> String {
    let tags_json = e
        .tags
        .iter()
        .map(|t| format!(r#""{}""#, escape_json_string(t)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"event_id":"{}","kind":"{}","text":"{}","tags":[{}],"sequence":{}}}"#,
        escape_json_string(&e.event_id),
        escape_json_string(&e.kind),
        escape_json_string(&e.text),
        tags_json,
        e.sequence
    )
}

pub(crate) fn handle_put_safety_boundaries(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let tags = match parse_tags_field(&json, "blocked_tags") {
        Ok(t) => t,
        Err(e) => return bad_request(stream, e),
    };

    campaign.safety_blocked_tags = tags;
    let out = safety_boundaries_json(&campaign.safety_blocked_tags);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_get_safety_boundaries(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username
        || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let out = safety_boundaries_json(&campaign.safety_blocked_tags);
    drop(store);

    respond(stream, 200, &out)
}

fn parse_tags_field(json: &crate::json::Json, field: &str) -> Result<Vec<String>, &'static str> {
    let arr = match json.get(field).and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return Err("invalid tags"),
    };
    if arr.is_empty() {
        return Err("invalid tags");
    }
    let mut tags = Vec::new();
    for item in arr {
        match item.as_str() {
            Some(s) if !s.is_empty() => tags.push(s.to_string()),
            _ => return Err("invalid tags"),
        }
    }
    let mut seen = std::collections::HashSet::new();
    for t in &tags {
        if !seen.insert(t.as_str()) {
            return Err("invalid tags");
        }
    }
    Ok(tags)
}

pub(crate) fn handle_create_safety_check(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_member = campaign.owner == username
        || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let text = require_str!(stream, json, "text", "invalid text");
    let kind = require_str!(stream, json, "kind", "invalid kind");
    if kind != "narration" && kind != "chat" {
        return bad_request(stream, "invalid kind");
    }
    let tags = match parse_tags_field(&json, "tags") {
        Ok(t) => t,
        Err(e) => return bad_request(stream, e),
    };

    if campaign
        .safety_events
        .iter()
        .any(|e| e.event_id == event_id)
    {
        return respond(stream, 409, r#"{"error":"duplicate event_id"}"#);
    }

    if tags
        .iter()
        .any(|t| campaign.safety_blocked_tags.iter().any(|b| b == t))
    {
        return respond(stream, 409, r#"{"error":"blocked tag"}"#);
    }

    let sequence = campaign.safety_sequence + 1;
    let event = SafetyEvent {
        event_id,
        kind,
        text,
        tags,
        sequence,
    };
    let out = safety_event_json(&event);
    campaign.safety_sequence = sequence;
    campaign.safety_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_list_safety_events(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username
        || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let events_json: Vec<String> = campaign
        .safety_events
        .iter()
        .map(safety_event_json)
        .collect();
    let out = format!(r#"{{"events":[{}]}}"#, events_json.join(","));
    drop(store);

    respond(stream, 200, &out)
}

const CANONICAL_FIXTURE_JSON: &str = concat!(
    r#"{"fixture_id":"canonical-v1","status":"seeded","characters":["#,
    r#"{"character_id":"fixture-hero","name":"Ari","class":"fighter"},"#,
    r#"{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"#,
    r#""story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}"#,
);

pub(crate) fn handle_seed_fixture(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let fixture_id = require_str!(stream, json, "fixture_id", "invalid fixture_id");
    if fixture_id != "canonical-v1" {
        return bad_request(stream, "invalid fixture_id");
    }

    if campaign.fixture_seeded {
        drop(store);
        return respond(stream, 200, CANONICAL_FIXTURE_JSON);
    }

    campaign.fixture_seeded = true;
    drop(store);

    respond(stream, 201, CANONICAL_FIXTURE_JSON)
}

pub(crate) fn handle_get_fixture_state(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_member = campaign.owner == username
        || campaign.members.iter().any(|m| m.username == username);
    if !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    if !campaign.fixture_seeded {
        return respond(stream, 404, r#"{"error":"fixture not seeded"}"#);
    }
    drop(store);

    respond(stream, 200, CANONICAL_FIXTURE_JSON)
}

// ===== Spectator view (098-spectator-view) =====

pub(crate) fn handle_create_spectator_ticket(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    if campaign.owner != username {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let spectator_id = require_str!(stream, json, "spectator_id", "invalid spectator_id");

    let duplicate = store
        .values()
        .any(|c| c.spectators.iter().any(|s| s.spectator_id == spectator_id));
    if duplicate {
        return respond(stream, 409, r#"{"error":"spectator id already exists"}"#);
    }

    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));
    campaign.spectators.push(SpectatorTicket {
        spectator_id: spectator_id.clone(),
    });
    drop(store);

    let out = format!(
        r#"{{"spectator_id":"{}","token":"spectator-{}"}}"#,
        escape_json_string(&spectator_id),
        escape_json_string(&spectator_id)
    );
    respond(stream, 201, &out)
}

pub(crate) fn handle_get_spectator_view(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
) -> std::io::Result<()> {
    let header = match auth_header {
        Some(h) => h,
        None => return respond(stream, 401, r#"{"error":"unauthorized"}"#),
    };
    let token = match header.strip_prefix("Bearer ") {
        Some(t) => t.trim(),
        None => return respond(stream, 401, r#"{"error":"unauthorized"}"#),
    };
    if let Some(rest) = token.strip_prefix("session-") {
        if rest.is_empty() {
            return respond(stream, 401, r#"{"error":"unauthorized"}"#);
        }
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }
    let spectator_id = match token.strip_prefix("spectator-") {
        Some(id) if !id.is_empty() => id,
        _ => return respond(stream, 401, r#"{"error":"unauthorized"}"#),
    };

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    if !campaign
        .spectators
        .iter()
        .any(|s| s.spectator_id == spectator_id)
    {
        let belongs_elsewhere = store
            .values()
            .any(|c| c.spectators.iter().any(|s| s.spectator_id == spectator_id));
        if belongs_elsewhere {
            return respond(stream, 403, r#"{"error":"forbidden"}"#);
        }
        return respond(stream, 401, r#"{"error":"unauthorized"}"#);
    }

    let out = format!(
        r#"{{"campaign_id":"{}","name":"{}","status":"{}","party_size":{},"story":"{}"}}"#,
        escape_json_string(&campaign.id),
        escape_json_string(&campaign.name),
        escape_json_string(&campaign.status),
        campaign.members.len(),
        escape_json_string(&campaign.document.story)
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_create_message(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let text = require_str!(stream, json, "text", "invalid text");

    let message = ChatMessage {
        actor: username,
        text,
    };
    let out = format!(
        r#"{{"kind":"chat","actor":"{}","text":"{}"}}"#,
        escape_json_string(&message.actor),
        escape_json_string(&message.text)
    );
    campaign.messages.push(message);
    drop(store);

    respond(stream, 201, &out)
}

// ===== Load-safe event feed (099-load-safe-event-feed) =====

fn feed_event_json(e: &FeedEvent) -> String {
    format!(
        r#"{{"event_id":"{}","text":"{}","sequence":{}}}"#,
        escape_json_string(&e.event_id),
        escape_json_string(&e.text),
        e.sequence
    )
}

pub(crate) fn handle_append_feed_event(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let mut store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get_mut(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let json = parsed_json!(stream, body);
    let event_id = require_str!(stream, json, "event_id", "invalid event_id");
    let text = require_str!(stream, json, "text", "invalid text");

    if campaign.feed_events.iter().any(|e| e.event_id == event_id) {
        return respond(stream, 409, r#"{"error":"event_id already exists"}"#);
    }

    let sequence = campaign.feed_events.len() as i64 + 1;
    let event = FeedEvent {
        event_id,
        text,
        sequence,
    };
    let out = feed_event_json(&event);
    campaign.feed_events.push(event);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_event_feed(
    stream: &mut TcpStream,
    auth_header: Option<&str>,
    campaign_id: &str,
    cursor: Option<&str>,
    limit: Option<&str>,
) -> std::io::Result<()> {
    let (username, _role) = authenticated!(stream, auth_header);

    let store = play_campaigns().lock().unwrap();
    let campaign = campaign_or_404!(stream, store.get(campaign_id));

    let is_dm = campaign.owner == username;
    let is_member = campaign.members.iter().any(|m| m.username == username);
    if !is_dm && !is_member {
        return respond(stream, 403, r#"{"error":"forbidden"}"#);
    }

    let cursor_val: i64 = match cursor {
        Some(v) => match v.parse::<i64>() {
            Ok(n) if n >= 0 => n,
            _ => return bad_request(stream, "invalid cursor"),
        },
        None => 0,
    };
    let limit_val: i64 = match limit {
        Some(v) => match v.parse::<i64>() {
            Ok(n) if (1..=3).contains(&n) => n,
            _ => return bad_request(stream, "invalid limit"),
        },
        None => 2,
    };

    let start = cursor_val as usize;
    let page: Vec<String> = campaign
        .feed_events
        .iter()
        .skip(start)
        .take(limit_val as usize)
        .map(feed_event_json)
        .collect();

    let next_cursor = cursor_val + page.len() as i64;
    let out = format!(
        r#"{{"events":[{}],"next_cursor":{}}}"#,
        page.join(","),
        next_cursor
    );
    drop(store);

    respond(stream, 200, &out)
}
