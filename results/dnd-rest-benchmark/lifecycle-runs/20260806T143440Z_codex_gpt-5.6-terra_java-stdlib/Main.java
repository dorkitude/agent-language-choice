import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class Main {
    private static final Pattern DICE = Pattern.compile("^(\\d+)d(\\d+)([+-]\\d+)?$");
    private static final Map<String, Integer> XP = Map.of(
        "0", 10, "1/8", 25, "1/4", 50, "1/2", 100,
        "1", 200, "2", 450, "3", 700, "4", 1100, "5", 1800
    );
    // These insertion-ordered maps are the live domain cache.  Mutators synchronize,
    // then persist the complete snapshot so response and reload ordering stay stable.
    private static final Map<String, CombatSession> SESSIONS = new LinkedHashMap<>();
    private static final Map<String, User> USERS = new LinkedHashMap<>();
    private static final Map<String, Monster> MONSTERS = new LinkedHashMap<>();
    private static final Map<String, Item> ITEMS = new LinkedHashMap<>();
    private static final Map<String, Campaign> CAMPAIGNS = new LinkedHashMap<>();
    private static final Map<String, PlayCampaign> PLAY_CAMPAIGNS = new LinkedHashMap<>();
    // Spectator bearer tokens contain only this ID, so the index is deliberately
    // global rather than scoped to a campaign.
    private static final Map<String, String> SPECTATOR_CAMPAIGNS = new LinkedHashMap<>();
    private static final Map<String, Encounter> ENCOUNTERS = new LinkedHashMap<>();
    // This is deliberately process-local service state, rather than campaign data.
    private static volatile boolean maintenanceMode;
    private static final Map<String, Spell> WIZARD_SPELLS = Map.ofEntries(
        Map.entry("fire-bolt", new Spell("fire-bolt", "Fire Bolt", 0)),
        Map.entry("mage-hand", new Spell("mage-hand", "Mage Hand", 0)),
        Map.entry("minor-illusion", new Spell("minor-illusion", "Minor Illusion", 0)),
        Map.entry("prestidigitation", new Spell("prestidigitation", "Prestidigitation", 0)),
        Map.entry("ray-of-frost", new Spell("ray-of-frost", "Ray of Frost", 0)),
        Map.entry("burning-hands", new Spell("burning-hands", "Burning Hands", 1)),
        Map.entry("detect-magic", new Spell("detect-magic", "Detect Magic", 1)),
        Map.entry("find-familiar", new Spell("find-familiar", "Find Familiar", 1)),
        Map.entry("identify", new Spell("identify", "Identify", 1)),
        Map.entry("magic-missile", new Spell("magic-missile", "Magic Missile", 1)),
        Map.entry("shield", new Spell("shield", "Shield", 1)),
        Map.entry("sleep", new Spell("sleep", "Sleep", 1)),
        Map.entry("invisibility", new Spell("invisibility", "Invisibility", 2)),
        Map.entry("misty-step", new Spell("misty-step", "Misty Step", 2)),
        Map.entry("scorching-ray", new Spell("scorching-ray", "Scorching Ray", 2)),
        Map.entry("counterspell", new Spell("counterspell", "Counterspell", 3)),
        Map.entry("fireball", new Spell("fireball", "Fireball", 3)),
        Map.entry("fly", new Spell("fly", "Fly", 3))
    );
    private static final Pattern USERNAME = Pattern.compile("^[a-z0-9_-]{2,32}$");
    private static final String API_SCHEMA_JSON = "{\"version\":\"2026-07-29\",\"endpoints\":["
        + "{\"method\":\"GET\",\"path\":\"/v1/play/campaigns/{id}/rng-ledger\",\"auth\":\"member\"},"
        + "{\"method\":\"GET\",\"path\":\"/v1/schema\",\"auth\":\"public\"},"
        + "{\"method\":\"POST\",\"path\":\"/v1/play/campaigns\",\"auth\":\"dm\"},"
        + "{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/fixture-seeds\",\"auth\":\"dm\"},"
        + "{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/members\",\"auth\":\"member\"},"
        + "{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/moderation/reports\",\"auth\":\"member\"},"
        + "{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/rng-rolls\",\"auth\":\"member\"},"
        + "{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution\",\"auth\":\"dm\"},"
        + "{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/rng-seed\",\"auth\":\"dm\"},"
        + "{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/safety-boundaries\",\"auth\":\"dm\"}]}";
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Path DATABASE = Path.of("game.db");
    // Child tables must be cleared before their owners. Both reset and snapshot
    // replacement use this exact order so they cannot drift apart over time.
    private static final String CLEAR_STORAGE_TABLES = "DELETE FROM users; DELETE FROM combat_sessions; DELETE FROM monster_tags; DELETE FROM monsters; DELETE FROM items; DELETE FROM campaign_characters; DELETE FROM campaign_events; DELETE FROM quest_milestones; DELETE FROM campaign_quests; DELETE FROM campaign_factions; DELETE FROM campaign_npcs; DELETE FROM campaign_inventory; DELETE FROM character_equipment; DELETE FROM crafting_projects; DELETE FROM scheduled_session_agenda; DELETE FROM scheduled_session_attendance; DELETE FROM campaign_scheduled_sessions; DELETE FROM campaigns; DELETE FROM play_campaign_rate_events; DELETE FROM play_campaign_search_records; DELETE FROM play_campaign_notes; DELETE FROM play_campaign_whispers; DELETE FROM play_campaign_moderation_reports; DELETE FROM play_character_downtime_allocations; DELETE FROM play_campaign_downtime_activities; DELETE FROM play_campaign_recipe_ingredients; DELETE FROM play_campaign_recipes; DELETE FROM play_campaign_shop_stock; DELETE FROM play_campaign_shops; DELETE FROM play_campaign_settlement_discoveries; DELETE FROM play_campaign_settlement_services; DELETE FROM play_campaign_settlements; DELETE FROM play_campaign_reputation_history; DELETE FROM play_campaign_factions; DELETE FROM play_campaign_world_events; DELETE FROM play_campaign_calendars; DELETE FROM play_campaign_relationships; DELETE FROM play_campaign_clues; DELETE FROM play_campaign_quest_reward_grants; DELETE FROM play_campaign_quest_reward_items; DELETE FROM play_campaign_quest_rewards; DELETE FROM play_campaign_quest_dependencies; DELETE FROM play_campaign_quests; DELETE FROM play_campaign_loot_votes; DELETE FROM play_campaign_loot; DELETE FROM play_campaign_npc_dialogue; DELETE FROM play_campaign_npcs; DELETE FROM play_campaign_safe_turns; DELETE FROM play_campaign_safe_turn_state; DELETE FROM play_campaign_idempotent_events; DELETE FROM play_campaign_projection_events; DELETE FROM play_campaign_events; DELETE FROM play_campaign_narrations; DELETE FROM play_campaign_feed_events; DELETE FROM play_character_casts; DELETE FROM play_character_concentrations; DELETE FROM play_character_prepared_spells; DELETE FROM play_character_spells; DELETE FROM play_character_inventory; DELETE FROM play_character_equipment; DELETE FROM play_campaign_transactional_transfers; DELETE FROM play_campaign_currency; DELETE FROM play_campaign_delegation_audit; DELETE FROM play_campaign_delegations; DELETE FROM play_campaign_audit_events; DELETE FROM play_campaign_invitations; DELETE FROM play_campaign_members; DELETE FROM play_campaign_spectators; DELETE FROM play_campaign_nudges; DELETE FROM play_campaign_location_connections; DELETE FROM play_campaign_locations; DELETE FROM play_campaign_scene_state; DELETE FROM play_campaign_scenes; DELETE FROM play_campaign_encounter_reward_loot; DELETE FROM play_campaign_encounter_rewards; DELETE FROM play_campaign_encounter_conditions; DELETE FROM play_campaign_encounter_combatants; DELETE FROM play_campaign_encounter_monsters; DELETE FROM play_campaign_encounter_order; DELETE FROM play_campaign_encounter_turns; DELETE FROM play_campaign_encounters; DELETE FROM play_campaign_exploration_queue; DELETE FROM play_campaign_state; DELETE FROM play_campaign_documents; DELETE FROM play_campaign_imports; DELETE FROM play_campaign_exports; DELETE FROM play_campaign_backups; DELETE FROM play_campaign_session_zero_consent; DELETE FROM play_campaign_session_zero; DELETE FROM play_campaign_content_tags; DELETE FROM play_campaign_content; DELETE FROM play_campaign_fixture_seeds; DELETE FROM play_campaigns;";

    public static void main(String[] args) throws IOException {
        int port;
        try { port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080")); }
        catch (NumberFormatException e) { throw new IllegalArgumentException("PORT must be an integer"); }
        initializeStorage();
        HttpServer server = HttpServer.create(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 0);
        server.createContext("/", Main::handle);
        server.start();
    }

    private static void handle(HttpExchange exchange) throws IOException {
        try {
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();
            // Spectator tickets are deliberately not session credentials.  Reject
            // them before route dispatch so they cannot turn an unsupported
            // mutation route into a misleading 404 response.
            String authorization = exchange.getRequestHeaders().getFirst("Authorization");
            if (authorization != null && authorization.startsWith("Bearer spectator-")
                && !(method.equals("GET") && path.matches("^/v1/play/campaigns/[^/]+/spectator-view$"))) {
                throw new Unauthorized();
            }
            // Exact and read-only routes precede the POST dispatcher; route order is
            // part of the compatibility contract for overlapping path prefixes.
            if (path.equals("/health") && method.equals("GET")) {
                reply(exchange, 200, "{\"ok\":true}");
                return;
            }
            if (path.equals("/healthz") && method.equals("GET")) {
                reply(exchange, 200, "{\"status\":\"ok\"}");
                return;
            }
            if (path.equals("/v1/schema") && method.equals("GET")) {
                reply(exchange, 200, API_SCHEMA_JSON);
                return;
            }
            if (path.equals("/readyz") && method.equals("GET")) {
                reply(exchange, maintenanceMode ? 503 : 200, maintenanceMode
                    ? "{\"status\":\"maintenance\",\"schema_version\":2}"
                    : "{\"status\":\"ready\",\"schema_version\":2}");
                return;
            }
            if (path.equals("/v1/storage/status") && method.equals("GET")) {
                reply(exchange, 200, "{\"driver\":\"sqlite\",\"schema_version\":1,\"initialized\":true}");
                return;
            }
            if (path.equals("/v1/storage/reset") && method.equals("POST")) {
                resetStorage();
                reply(exchange, 200, "{\"ok\":true,\"schema_version\":1}");
                return;
            }
            if (path.matches("^/v1/compendium/monsters/[^/]+$") && method.equals("GET")) {
                reply(exchange, 200, readMonster(path.substring("/v1/compendium/monsters/".length())));
                return;
            }
            if (path.matches("^/v1/compendium/items/[^/]+$") && method.equals("GET")) {
                reply(exchange, 200, readItem(path.substring("/v1/compendium/items/".length())));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/state$") && method.equals("GET")) {
                reply(exchange, 200, campaignState(campaignId(path, "/state")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/audit$") && method.equals("GET")) {
                reply(exchange, 200, campaignAudit(campaignId(path, "/audit")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/export$") && method.equals("GET")) {
                reply(exchange, 200, campaignExport(campaignId(path, "/export")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/quests/summary$") && method.equals("GET")) {
                reply(exchange, 200, questSummary(campaignId(path, "/quests/summary")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/relationships$") && method.equals("GET")) {
                reply(exchange, 200, relationshipSummary(campaignId(path, "/relationships")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/inventory/summary$") && method.equals("GET")) {
                reply(exchange, 200, inventorySummary(campaignId(path, "/inventory/summary")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/sessions/next$") && method.equals("GET")) {
                reply(exchange, 200, nextScheduledSession(campaignId(path, "/sessions/next")));
                return;
            }
            if (path.matches("^/v1/campaigns/[^/]+/analytics/summary$") && method.equals("GET")) {
                reply(exchange, 200, campaignAnalyticsSummary(campaignId(path, "/analytics/summary")));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/turn$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, encounterTurn(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/onboarding$") && method.equals("GET")) {
                reply(exchange, 200, campaignOnboarding(playCampaignId(path, "/onboarding"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/spectator-view$") && method.equals("GET")) {
                reply(exchange, 200, spectatorView(playCampaignId(path, "/spectator-view"), exchange));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/event-feed$") && method.equals("GET")) {
                reply(exchange, 200, eventFeed(playCampaignId(path, "/event-feed"), actor(exchange), feedPagination(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/session-zero$") && method.equals("GET")) {
                reply(exchange, 200, sessionZeroSettings(playCampaignId(path, "/session-zero"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/invitations$") && method.equals("GET")) {
                reply(exchange, 200, listInvitations(playCampaignId(path, "/invitations"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/delegations/audit$") && method.equals("GET")) {
                reply(exchange, 200, delegationAudit(playCampaignId(path, "/delegations/audit"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/audit-events$") && method.equals("GET")) {
                reply(exchange, 200, auditEvents(playCampaignId(path, "/audit-events"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/projection$") && method.equals("GET")) {
                reply(exchange, 200, projection(playCampaignId(path, "/projection"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/projection/rebuild$") && method.equals("GET")) {
                reply(exchange, 200, rebuildProjection(playCampaignId(path, "/projection/rebuild"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/idempotent-events$") && method.equals("GET")) {
                reply(exchange, 200, idempotentEvents(playCampaignId(path, "/idempotent-events"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/safe-turns$") && method.equals("GET")) {
                reply(exchange, 200, safeTurns(playCampaignId(path, "/safe-turns"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/transactional-transfers$") && method.equals("GET")) {
                reply(exchange, 200, transactionalTransfers(playCampaignId(path, "/transactional-transfers"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/exports/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readCampaignExport(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/exports$") && method.equals("GET")) {
                reply(exchange, 200, listCampaignExports(playCampaignId(path, "/exports"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/import-state$") && method.equals("GET")) {
                reply(exchange, 200, importedState(playCampaignId(path, "/import-state"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/migration-state$") && method.equals("GET")) {
                reply(exchange, 200, migrationState(playCampaignId(path, "/migration-state"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/search-records$") && method.equals("GET")) {
                reply(exchange, 200, listSearchRecords(playCampaignId(path, "/search-records"), actor(exchange), searchParameters(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/rate-events$") && method.equals("GET")) {
                reply(exchange, 200, listRateEvents(playCampaignId(path, "/rate-events"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/metrics$") && method.equals("GET")) {
                reply(exchange, 200, serviceMetrics(playCampaignId(path, "/metrics"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/replay$") && method.equals("GET")) {
                reply(exchange, 200, replay(playCampaignId(path, "/replay"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/replay/check$") && method.equals("GET")) {
                reply(exchange, 200, replay(playCampaignId(path, "/replay/check"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/rng-ledger$") && method.equals("GET")) {
                reply(exchange, 200, rngLedger(playCampaignId(path, "/rng-ledger"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/moderation/reports$") && method.equals("GET")) {
                reply(exchange, 200, moderationReports(playCampaignId(path, "/moderation/reports"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/safety-boundaries$") && method.equals("GET")) {
                reply(exchange, 200, safetyBoundaries(playCampaignId(path, "/safety-boundaries"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/safety-events$") && method.equals("GET")) {
                reply(exchange, 200, safetyEvents(playCampaignId(path, "/safety-events"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/fixture-state$") && method.equals("GET")) {
                reply(exchange, 200, fixtureState(playCampaignId(path, "/fixture-state"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/service-mode$") && method.equals("POST")) {
                reply(exchange, 200, updateServiceMode(playCampaignId(path, "/service-mode"), actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/session-zero$") && method.equals("PUT")) {
                reply(exchange, 200, updateSessionZeroSettings(playCampaignId(path, "/session-zero"), actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/rng-seed$") && method.equals("PUT")) {
                reply(exchange, 200, configureRngSeed(playCampaignId(path, "/rng-seed"), actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/safety-boundaries$") && method.equals("PUT")) {
                reply(exchange, 200, replaceSafetyBoundaries(playCampaignId(path, "/safety-boundaries"), actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/moderation/reports/[^/]+/resolution$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, resolveModerationReport(parts[0], parts[3], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/content/[^/]+/tags$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, replaceContentTags(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/notes/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readNote(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/notes/[^/]+$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updateNote(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/notes$") && method.equals("GET")) {
                reply(exchange, 200, listNotes(playCampaignId(path, "/notes"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/whispers$") && method.equals("GET")) {
                reply(exchange, 200, listWhispers(playCampaignId(path, "/whispers"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/sheet$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterSheet(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/content$") && method.equals("GET")) {
                reply(exchange, 200, listContent(playCampaignId(path, "/content"), actor(exchange), contentExcludeTag(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/status$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, encounterStatus(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/turn$") && method.equals("GET")) {
                reply(exchange, 200, playCampaignTurn(playCampaignId(path, "/turn"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/my-turn$") && method.equals("GET")) {
                reply(exchange, 200, playerTurnContext(playCampaignId(path, "/my-turn"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/gm/status$") && method.equals("GET")) {
                reply(exchange, 200, gmTurnStatus(playCampaignId(path, "/gm/status"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/status$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterStatus(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/owner$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterOwner(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/currency$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterCurrency(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/spells$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterSpells(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterInventory(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/downtime/allocations/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readDowntimeAllocation(parts[0], parts[2], parts[5], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/recipes$") && method.equals("GET")) {
                reply(exchange, 200, listRecipes(playCampaignId(path, "/recipes"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/rewards$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterQuestRewards(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/loot/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readLoot(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/relationships$") && method.equals("GET")) {
                reply(exchange, 200, relationships(playCampaignId(path, "/relationships"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/clues$") && method.equals("GET")) {
                reply(exchange, 200, clues(playCampaignId(path, "/clues"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/quests$") && method.equals("GET")) {
                reply(exchange, 200, playQuests(playCampaignId(path, "/quests"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/world-events$") && method.equals("GET")) {
                reply(exchange, 200, worldEvents(playCampaignId(path, "/world-events"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/calendar$") && method.equals("GET")) {
                reply(exchange, 200, calendar(playCampaignId(path, "/calendar"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/settlements$") && method.equals("GET")) {
                reply(exchange, 200, settlements(playCampaignId(path, "/settlements"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/settlements/[^/]+/shops/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readShop(parts[0], parts[2], parts[4], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/settlements/[^/]+$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updateSettlement(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/quests/[^/]+/state$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, changePlayQuestState(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/quests/[^/]+/rewards$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, configurePlayQuestRewards(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, npcDialogue(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/npcs/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, readPlayNpc(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/npcs/[^/]+/agenda$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updatePlayNpcAgenda(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/relationships/[^/]+/[^/]+/[^/]+$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updateRelationship(parts[0], parts[2], parts[3], parts[4], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, factionReputation(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterEquipment(parts[0], parts[2], parts[4], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items/[^/]+$") && method.equals("DELETE")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, removeCharacterInventoryItem(parts[0], parts[2], parts[5], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/casts$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterCasts(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/prepared-spells$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterPreparedSpells(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/prepared-spells$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updateCharacterPreparedSpells(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, equipCharacterItem(parts[0], parts[2], parts[4], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, characterConcentration(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration$") && method.equals("PUT")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, updateCharacterConcentration(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration$") && method.equals("DELETE")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, clearCharacterConcentration(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/document$") && method.equals("GET")) {
                reply(exchange, 200, campaignDocument(playCampaignId(path, "/document"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/document$") && method.equals("PUT")) {
                reply(exchange, 200, updateCampaignDocument(playCampaignId(path, "/document"), actor(exchange), object(readBody(exchange))));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/backups$") && method.equals("GET")) {
                reply(exchange, 200, listCampaignBackups(playCampaignId(path, "/backups"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/scenes/current$") && method.equals("GET")) {
                reply(exchange, 200, currentScene(playCampaignId(path, "/scenes/current"), actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/locations/[^/]+/travel$") && method.equals("GET")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, travelLocations(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/monsters/[^/]+$") && method.equals("DELETE")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, removeEncounterMonster(parts[0], parts[2], parts[4], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/combatants/[^/]+$") && method.equals("DELETE")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, removeEncounterCombatant(parts[0], parts[2], parts[4], actor(exchange)));
                return;
            }
            if (path.matches("^/v1/play/campaigns/[^/]+/delegations/[^/]+$") && method.equals("DELETE")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, revokeDelegation(parts[0], parts[2], actor(exchange)));
                return;
            }
            if (!method.equals("POST")) { reply(exchange, 404, "{\"error\":\"not found\"}"); return; }
            String result;
            if (path.equals("/v1/auth/register")) {
                reply(exchange, 201, register(object(readBody(exchange))));
                return;
            } else if (path.equals("/v1/auth/login")) {
                result = login(object(readBody(exchange)));
            } else if (path.equals("/v1/combat/sessions")) {
                result = createSession(object(readBody(exchange)));
            } else if (path.equals("/v1/compendium/monsters")) {
                reply(exchange, 201, createMonster(object(readBody(exchange))));
                return;
            } else if (path.equals("/v1/compendium/items")) {
                reply(exchange, 201, createItem(object(readBody(exchange))));
                return;
            } else if (path.equals("/v1/campaigns")) {
                reply(exchange, 201, createCampaign(object(readBody(exchange))));
                return;
            } else if (path.equals("/v1/play/campaigns")) {
                reply(exchange, 201, createPlayCampaign(actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/members$")) {
                reply(exchange, 201, joinPlayCampaign(playCampaignId(path, "/members"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/spectators$")) {
                reply(exchange, 201, createSpectator(playCampaignId(path, "/spectators"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/feed-events$")) {
                reply(exchange, 201, appendFeedEvent(playCampaignId(path, "/feed-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/safety-checks$")) {
                reply(exchange, 201, submitSafetyCheck(playCampaignId(path, "/safety-checks"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/fixture-seeds$")) {
                FixtureSeedResult seed = seedFixture(playCampaignId(path, "/fixture-seeds"), actor(exchange), object(readBody(exchange)));
                reply(exchange, seed.created ? 201 : 200, fixtureJson());
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/invitations$")) {
                reply(exchange, 201, createInvitation(playCampaignId(path, "/invitations"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/delegations$")) {
                reply(exchange, 201, grantDelegation(playCampaignId(path, "/delegations"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/audit-events$")) {
                reply(exchange, 201, createAuditEvent(playCampaignId(path, "/audit-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/projection-events$")) {
                reply(exchange, 201, appendProjectionEvent(playCampaignId(path, "/projection-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/replay-events$")) {
                reply(exchange, 201, appendReplayEvent(playCampaignId(path, "/replay-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/rng-rolls$")) {
                reply(exchange, 201, appendRngRoll(playCampaignId(path, "/rng-rolls"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/moderation/reports$")) {
                reply(exchange, 201, createModerationReport(playCampaignId(path, "/moderation/reports"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/idempotent-events$")) {
                IdempotentEventResult event = createIdempotentEvent(playCampaignId(path, "/idempotent-events"), actor(exchange), exchange.getRequestHeaders().getFirst("Idempotency-Key"), object(readBody(exchange)));
                reply(exchange, event.created ? 201 : 200, idempotentEventJson(event.event));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/safe-turns$")) {
                SafeTurnResult turn = submitSafeTurn(playCampaignId(path, "/safe-turns"), actor(exchange), object(readBody(exchange)));
                reply(exchange, turn.accepted ? 201 : 409, turn.json);
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/transactional-transfers$")) {
                reply(exchange, 201, createTransactionalTransfer(playCampaignId(path, "/transactional-transfers"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/exports$")) {
                reply(exchange, 201, createCampaignExport(playCampaignId(path, "/exports"), actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/backups$")) {
                reply(exchange, 201, createCampaignBackup(playCampaignId(path, "/backups"), actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/backups/[^/]+/restore$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, restoreCampaignBackup(parts[0], parts[2], actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/imports$")) {
                reply(exchange, 200, importCampaignSnapshot(playCampaignId(path, "/imports"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/migrations$")) {
                MigrationResult migration = migrateCampaignSnapshot(playCampaignId(path, "/migrations"), actor(exchange), object(readBody(exchange)));
                reply(exchange, migration.created ? 201 : 200, migrationJson(migration.state));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/invitations/[^/]+/accept$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, acceptInvitation(parts[0], parts[2], actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/content$")) {
                reply(exchange, 201, createContent(playCampaignId(path, "/content"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/search-records$")) {
                reply(exchange, 201, createSearchRecord(playCampaignId(path, "/search-records"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/rate-events$")) {
                reply(exchange, 201, createRateEvent(playCampaignId(path, "/rate-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/notes$")) {
                reply(exchange, 201, createNote(playCampaignId(path, "/notes"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/whispers$")) {
                reply(exchange, 201, createWhisper(playCampaignId(path, "/whispers"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/recipes$")) {
                reply(exchange, 201, createRecipe(playCampaignId(path, "/recipes"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/downtime/activities$")) {
                reply(exchange, 201, createDowntimeActivity(playCampaignId(path, "/downtime/activities"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/downtime/allocations$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, createDowntimeAllocation(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/downtime/allocations/[^/]+/progress$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = progressDowntimeAllocation(parts[0], parts[2], parts[5], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/recipes/[^/]+/craft$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, craftRecipe(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/npcs$")) {
                reply(exchange, 201, createPlayNpc(playCampaignId(path, "/npcs"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/settlements$")) {
                reply(exchange, 201, createSettlement(playCampaignId(path, "/settlements"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/settlements/[^/]+/shops$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, createShop(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/settlements/[^/]+/shops/[^/]+/(buy|sell)$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = tradeShop(parts[0], parts[2], parts[4], parts[5].equals("buy"), actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/settlements/[^/]+/discover$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                DiscoveryResult discovery = discoverSettlement(parts[0], parts[2], actor(exchange));
                reply(exchange, discovery.created ? 201 : 200, discovery.json);
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, appendNpcDialogue(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/relationships$")) {
                reply(exchange, 201, createRelationship(playCampaignId(path, "/relationships"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/clues$")) {
                reply(exchange, 201, createClue(playCampaignId(path, "/clues"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/quests$")) {
                reply(exchange, 201, createPlayQuest(playCampaignId(path, "/quests"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/quests/[^/]+/rewards/award$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, awardPlayQuestRewards(parts[0], parts[2], actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/world-events$")) {
                reply(exchange, 201, scheduleWorldEvent(playCampaignId(path, "/world-events"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/world-events/[^/]+/resolve$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, resolveWorldEvent(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/calendar$")) {
                reply(exchange, 201, initializeCalendar(playCampaignId(path, "/calendar"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/calendar/advance$")) {
                result = advanceCalendar(playCampaignId(path, "/calendar/advance"), actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/factions$")) {
                reply(exchange, 201, createPlayFaction(playCampaignId(path, "/factions"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, changeFactionReputation(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/start$")) {
                result = startPlayCampaign(playCampaignId(path, "/start"), actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/narrations$")) {
                reply(exchange, 201, addNarration(playCampaignId(path, "/narrations"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/messages$")) {
                reply(exchange, 201, addMessage(playCampaignId(path, "/messages"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/resolutions$")) {
                reply(exchange, 201, addResolution(playCampaignId(path, "/resolutions"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/turn/nudge$")) {
                reply(exchange, 201, nudgePlayCampaignTurn(playCampaignId(path, "/turn/nudge"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/turn/travel$")) {
                reply(exchange, 201, travelTurn(playCampaignId(path, "/turn/travel"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/turn/rest$")) {
                reply(exchange, 201, restTurn(playCampaignId(path, "/turn/rest"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration/advance-turn$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = advanceCharacterConcentration(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/damage$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = damageCharacter(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/death-saves$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, deathSave(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/claim$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, claimCharacter(parts[0], parts[2], actor(exchange)));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/transfer$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = transferCharacter(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/build$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = buildCharacter(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/level-up$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = levelUpCharacter(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/skill-check$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = skillCheck(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/spells$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addCharacterSpell(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addCharacterInventoryItem(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items/[^/]+/consume$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = consumeCharacterInventoryItem(parts[0], parts[2], parts[5], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/currency/transfers$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, transferCurrency(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/loot$")) {
                reply(exchange, 201, createLoot(playCampaignId(path, "/loot"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/loot/[^/]+/votes$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, voteLoot(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/loot/[^/]+/assign$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = assignLoot(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+/attune$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = attuneCharacterEquipment(parts[0], parts[2], parts[4], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/characters/[^/]+/casts$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, castSpell(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters$")) {
                reply(exchange, 201, createEncounter(playCampaignId(path, "/encounters"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/monsters$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addEncounterMonster(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/combatants$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addEncounterCombatant(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/turn/delay$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 200, delayEncounterTurn(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/turn/ready$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, readyEncounterTurn(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/turn/advance$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = advanceEncounterTurn(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/conditions$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addEncounterCondition(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/rewards$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = awardEncounterRewards(parts[0], parts[2], actor(exchange), object(readBody(exchange)));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/end$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = endEncounter(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/close$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = closeEncounter(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/damage$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = changeEncounterHitPoints(parts[0], parts[2], actor(exchange), object(readBody(exchange)), false);
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/heal$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = changeEncounterHitPoints(parts[0], parts[2], actor(exchange), object(readBody(exchange)), true);
            } else if (path.matches("^/v1/play/campaigns/[^/]+/encounters/[^/]+/actions$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, addCombatAction(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/actions$")) {
                reply(exchange, 201, addAction(playCampaignId(path, "/actions"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/scenes$")) {
                reply(exchange, 201, createScene(playCampaignId(path, "/scenes"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/locations$")) {
                reply(exchange, 201, createLocation(playCampaignId(path, "/locations"), actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/locations/[^/]+/connections$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                reply(exchange, 201, createLocationConnection(parts[0], parts[2], actor(exchange), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/play/campaigns/[^/]+/scenes/[^/]+/enter$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = enterScene(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/play/campaigns/[^/]+/scenes/[^/]+/close$")) {
                String[] parts = path.substring("/v1/play/campaigns/".length()).split("/");
                result = closeScene(parts[0], parts[2], actor(exchange));
            } else if (path.matches("^/v1/campaigns/[^/]+/characters$")) {
                reply(exchange, 201, addCampaignCharacter(campaignId(path, "/characters"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/sessions$")) {
                reply(exchange, 201, scheduleSession(campaignId(path, "/sessions"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/sessions/[^/]+/attendance$")) {
                String[] parts = path.substring("/v1/campaigns/".length()).split("/");
                result = recordAttendance(parts[0], parts[2], object(readBody(exchange)));
            } else if (path.matches("^/v1/campaigns/[^/]+/inventory$")) {
                reply(exchange, 201, addInventory(campaignId(path, "/inventory"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/downtime/crafting$")) {
                reply(exchange, 201, createCraftingProject(campaignId(path, "/downtime/crafting"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/downtime/crafting/[^/]+/advance$")) {
                String[] parts = path.substring("/v1/campaigns/".length()).split("/");
                result = advanceCraftingProject(parts[0], parts[3], object(readBody(exchange)));
            } else if (path.matches("^/v1/campaigns/[^/]+/characters/[^/]+/equipment$")) {
                String[] parts = path.substring("/v1/campaigns/".length()).split("/");
                reply(exchange, 200, assignEquipment(parts[0], parts[2], object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/events$")) {
                reply(exchange, 201, addCampaignEvent(campaignId(path, "/events"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/factions$")) {
                reply(exchange, 201, createFaction(campaignId(path, "/factions"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/npcs$")) {
                reply(exchange, 201, createNpc(campaignId(path, "/npcs"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/quests$")) {
                reply(exchange, 201, createQuest(campaignId(path, "/quests"), object(readBody(exchange))));
                return;
            } else if (path.matches("^/v1/campaigns/[^/]+/quests/[^/]+/progress$")) {
                String prefix = "/v1/campaigns/";
                String[] parts = path.substring(prefix.length()).split("/");
                result = updateQuestProgress(parts[0], parts[2], object(readBody(exchange)));
            } else if (path.matches("^/v1/campaigns/[^/]+/analytics/risk-report$")) {
                result = campaignRiskReport(campaignId(path, "/analytics/risk-report"), object(readBody(exchange)));
            } else if (path.matches("^/v1/combat/sessions/[^/]+/conditions$")) {
                result = addCondition(sessionId(path, "/conditions"), object(readBody(exchange)));
            } else if (path.matches("^/v1/combat/sessions/[^/]+/advance$")) {
                result = advance(sessionId(path, "/advance"));
            } else {
                Map<String, Object> body = object(readBody(exchange));
                result = switch (path) {
                    case "/v1/dice/stats" -> dice(body);
                    case "/v1/checks/ability" -> ability(body);
                    case "/v1/encounters/adjusted-xp" -> encounter(body);
                    case "/v1/initiative/order" -> initiative(body);
                    case "/v1/characters/ability-modifier" -> abilityModifier(body);
                    case "/v1/characters/proficiency" -> proficiency(body);
                    case "/v1/characters/derived-stats" -> derivedStats(body);
                    case "/v1/phb/spell-slots" -> spellSlots(body);
                    case "/v1/phb/rests/long" -> longRest(body);
                    case "/v1/phb/equipment-load" -> equipmentLoad(body);
                    case "/v1/dm/encounter-builder" -> encounterBuilder(body);
                    case "/v1/dm/loot-parcel" -> lootParcel(body);
                    case "/v1/dm/session-recap" -> sessionRecap(body);
                    default -> null;
                };
            }
            if (result == null) reply(exchange, 404, "{\"error\":\"not found\"}");
            else reply(exchange, 200, result);
        } catch (UnknownSession e) {
            reply(exchange, 404, "{\"error\":\"unknown session\"}");
        } catch (DuplicateUser e) {
            reply(exchange, 409, "{\"error\":\"duplicate username\"}");
        } catch (DuplicateSlug e) {
            reply(exchange, 409, "{\"error\":\"duplicate slug\"}");
        } catch (DuplicateId e) {
            reply(exchange, 409, "{\"error\":\"duplicate id\"}");
        } catch (DuplicateSpectator e) {
            reply(exchange, 409, "{\"error\":\"duplicate spectator_id\"}");
        } catch (CampaignStartConflict e) {
            reply(exchange, 409, "{\"error\":\"campaign cannot be started\"}");
        } catch (SessionZeroConflict e) {
            reply(exchange, 409, "{\"error\":\"session-zero settings are locked\"}");
        } catch (TurnConflict e) {
            reply(exchange, 409, "{\"error\":\"not your turn\"}");
        } catch (TravelConflict e) {
            reply(exchange, 409, "{\"error\":\"invalid travel\"}");
        } catch (SceneConflict e) {
            reply(exchange, 409, "{\"error\":\"scene is closed\"}");
        } catch (DeathSaveConflict e) {
            reply(exchange, 409, "{\"error\":\"death saves unavailable\"}");
        } catch (OwnershipConflict e) {
            reply(exchange, 409, "{\"error\":\"character already owned\"}");
        } catch (InventoryConflict e) {
            reply(exchange, 409, "{\"error\":\"insufficient inventory\"}");
        } catch (CurrencyConflict e) {
            reply(exchange, 409, "{\"error\":\"insufficient gold\"}");
        } catch (ShopStockConflict e) {
            reply(exchange, 409, "{\"error\":\"insufficient stock\"}");
        } catch (LootConflict e) {
            reply(exchange, 409, "{\"error\":\"loot conflict\"}");
        } catch (AttunementConflict e) {
            reply(exchange, 409, "{\"error\":\"attunement limit reached\"}");
        } catch (SpellConflict e) {
            reply(exchange, 409, "{\"error\":\"spell already known\"}");
        } catch (SpellSlotConflict e) {
            reply(exchange, 409, "{\"error\":\"no spell slots remaining\"}");
        } catch (EncounterTransitionConflict e) {
            reply(exchange, 409, "{\"error\":\"campaign is not in combat\"}");
        } catch (QuestTransitionConflict e) {
            reply(exchange, 409, "{\"error\":\"invalid quest transition\"}");
        } catch (QuestRewardConflict e) {
            reply(exchange, 409, "{\"error\":\"quest rewards unavailable\"}");
        } catch (WorldEventConflict e) {
            reply(exchange, 409, "{\"error\":\"world event conflict\"}");
        } catch (CalendarConflict e) {
            reply(exchange, 409, "{\"error\":\"calendar already initialized\"}");
        } catch (InvitationConflict e) {
            reply(exchange, 409, "{\"error\":\"invitation already accepted\"}");
        } catch (ProjectionEventConflict e) {
            reply(exchange, 409, "{\"error\":\"duplicate event_id\"}");
        } catch (ReplayEventConflict e) {
            reply(exchange, 409, "{\"error\":\"duplicate event_id\"}");
        } catch (FeedEventConflict e) {
            reply(exchange, 409, "{\"error\":\"duplicate event_id\"}");
        } catch (RngConflict e) {
            reply(exchange, 409, "{\"error\":\"rng conflict\"}");
        } catch (ModerationReportConflict e) {
            reply(exchange, 409, "{\"error\":\"moderation report conflict\"}");
        } catch (SafetyCheckConflict e) {
            reply(exchange, 409, "{\"error\":\"safety check conflict\"}");
        } catch (IdempotentEventConflict e) {
            reply(exchange, 409, "{\"error\":\"idempotency conflict\"}");
        } catch (SafeTurnConflict e) {
            reply(exchange, 409, "{\"error\":\"duplicate submission_id\"}");
        } catch (RateLimitExceeded e) {
            reply(exchange, 429, "{\"limit\":2,\"remaining\":0}");
        } catch (SimulatedFailure e) {
            reply(exchange, 500, "{\"error\":\"simulated failure\"}");
        } catch (UnknownRecord e) {
            reply(exchange, 404, "{\"error\":\"not found\"}");
        } catch (BadCredentials e) {
            reply(exchange, 401, "{\"error\":\"bad credentials\"}");
        } catch (Unauthorized e) {
            reply(exchange, 401, "{\"error\":\"unauthorized\"}");
        } catch (Forbidden e) {
            reply(exchange, 403, "{\"error\":\"forbidden\"}");
        } catch (IllegalArgumentException e) {
            reply(exchange, 400, "{\"error\":\"invalid request\"}");
        } catch (Exception e) {
            reply(exchange, 500, "{\"error\":\"internal server error\"}");
        }
    }

    private static synchronized String register(Map<String, Object> b) {
        String username = string(b, "username");
        String password = string(b, "password");
        String role = string(b, "role");
        if (!USERNAME.matcher(username).matches() || password.length() < 8 || !(role.equals("dm") || role.equals("player"))) {
            throw new IllegalArgumentException();
        }
        if (USERS.containsKey(username)) throw new DuplicateUser();
        USERS.put(username, new User(username, role, hashPassword(password)));
        saveStorage();
        return "{\"username\":\"" + escape(username) + "\",\"role\":\"" + role + "\"}";
    }

    private static synchronized String login(Map<String, Object> b) {
        String username = string(b, "username");
        String password = string(b, "password");
        User user = USERS.get(username);
        if (user == null || !verifyPassword(password, user.passwordHash)) throw new BadCredentials();
        return "{\"username\":\"" + escape(username) + "\",\"token\":\"session-" + escape(username) + "\"}";
    }

    private static synchronized String createMonster(Map<String, Object> b) {
        String slug = requiredText(b, "slug");
        String name = requiredText(b, "name");
        String cr = requiredText(b, "cr");
        long armorClass = positive(integer(b, "armor_class"));
        long hitPoints = positive(integer(b, "hit_points"));
        List<String> tags = strings(array(b, "tags"));
        if (MONSTERS.containsKey(slug)) throw new DuplicateSlug();
        Monster monster = new Monster(slug, name, cr, armorClass, hitPoints, tags);
        MONSTERS.put(slug, monster);
        saveStorage();
        return monsterJson(monster, false);
    }

    private static synchronized String readMonster(String slug) {
        Monster monster = MONSTERS.get(slug);
        if (monster == null) throw new UnknownRecord();
        return monsterJson(monster, true);
    }

    private static synchronized String createItem(Map<String, Object> b) {
        String slug = requiredText(b, "slug");
        String name = requiredText(b, "name");
        String type = requiredText(b, "type");
        String rarity = requiredText(b, "rarity");
        long costGp = integer(b, "cost_gp");
        if (costGp < 0 || ITEMS.containsKey(slug)) {
            if (ITEMS.containsKey(slug)) throw new DuplicateSlug();
            throw new IllegalArgumentException();
        }
        Item item = new Item(slug, name, type, rarity, costGp);
        ITEMS.put(slug, item);
        saveStorage();
        return itemJson(item);
    }

    private static synchronized String readItem(String slug) {
        Item item = ITEMS.get(slug);
        if (item == null) throw new UnknownRecord();
        return itemJson(item);
    }

    private static synchronized String createCampaign(Map<String, Object> b) {
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        String dm = requiredText(b, "dm");
        if (CAMPAIGNS.containsKey(id)) throw new DuplicateId();
        Campaign campaign = new Campaign(id, name, dm);
        CAMPAIGNS.put(id, campaign);
        saveStorage();
        return campaignJson(campaign);
    }

    private static synchronized String createPlayCampaign(User actor, Map<String, Object> b) {
        if (!actor.role.equals("dm")) throw new Forbidden();
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        long maxPlayers = positive(integer(b, "max_players"));
        if (PLAY_CAMPAIGNS.containsKey(id)) throw new DuplicateId();
        PlayCampaign campaign = new PlayCampaign(id, name, actor.username, maxPlayers);
        PLAY_CAMPAIGNS.put(id, campaign);
        saveStorage();
        return playCampaignJson(campaign);
    }

    private static synchronized String joinPlayCampaign(String campaignId, User actor, Map<String, Object> b) {
        if (!actor.role.equals("player")) throw new Forbidden();
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        String characterId = requiredText(b, "character_id");
        String name = requiredText(b, "name");
        String characterClass = requiredText(b, "class");
        if (campaign.members.containsKey(actor.username) || playCharacterExists(campaign, characterId)
            || campaign.members.size() >= campaign.maxPlayers) throw new DuplicateId();
        PartyMember member = new PartyMember(actor.username, characterId, name, characterClass);
        campaign.members.put(actor.username, member);
        saveStorage();
        return partyMemberJson(member);
    }

    private static synchronized String createSpectator(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 1 || !body.containsKey("spectator_id")) throw new IllegalArgumentException();
        String spectatorId = requiredText(body, "spectator_id");
        if (SPECTATOR_CAMPAIGNS.containsKey(spectatorId)) throw new DuplicateSpectator();
        SPECTATOR_CAMPAIGNS.put(spectatorId, campaign.id);
        saveStorage();
        return "{\"spectator_id\":\"" + escape(spectatorId) + "\",\"token\":\"spectator-" + escape(spectatorId) + "\"}";
    }

    private static synchronized String spectatorView(String campaignId, HttpExchange exchange) {
        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (authorization != null && authorization.startsWith("Bearer session-")) throw new Forbidden();
        if (authorization == null || !authorization.startsWith("Bearer spectator-")) throw new Unauthorized();
        String spectatorId = authorization.substring("Bearer spectator-".length());
        if (spectatorId.isEmpty()) throw new Unauthorized();
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        // Resolve a shaped spectator credential before the ticket lookup so an
        // absent resource cannot be used as a ticket-validity oracle.
        if (campaign == null) throw new UnknownRecord();
        String ticketCampaignId = SPECTATOR_CAMPAIGNS.get(spectatorId);
        if (ticketCampaignId == null) throw new Unauthorized();
        if (!ticketCampaignId.equals(campaign.id)) throw new Forbidden();
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"name\":\"" + escape(campaign.name)
            + "\",\"status\":\"" + escape(campaign.status) + "\",\"party_size\":" + campaign.members.size()
            + ",\"story\":\"" + escape(campaign.story) + "\"}";
    }

    private static synchronized String campaignOnboarding(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (isCampaignDm(campaign, actor)) {
            return "{\"role\":\"dm\",\"next_steps\":[\"configure-safety\",\"invite-players\",\"start-campaign\"],\"can_mutate\":true}";
        }
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        return "{\"role\":\"player\",\"next_steps\":[\"review-party\",\"take-turn\",\"submit-action\"],\"can_mutate\":true}";
    }

    private static synchronized String createInvitation(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 3 || !body.containsKey("invitation_id") || !body.containsKey("username") || !body.containsKey("character_id")) throw new IllegalArgumentException();
        String invitationId = requiredText(body, "invitation_id");
        String username = requiredText(body, "username");
        String characterId = requiredText(body, "character_id");
        User target = USERS.get(username);
        if (target == null || !target.role.equals("player")) throw new IllegalArgumentException();
        if (campaign.invitations.containsKey(invitationId)) throw new DuplicateId();
        for (Invitation invitation : campaign.invitations.values()) {
            if (invitation.status.equals("pending") && invitation.username.equals(username)) throw new DuplicateId();
        }
        Invitation invitation = new Invitation(invitationId, username, characterId);
        campaign.invitations.put(invitationId, invitation);
        saveStorage();
        return invitationJson(invitation);
    }

    private static synchronized String acceptInvitation(String campaignId, String invitationId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Invitation invitation = campaign.invitations.get(invitationId);
        if (invitation == null) throw new UnknownRecord();
        if (!invitation.username.equals(actor.username)) throw new Forbidden();
        if (!invitation.status.equals("pending")) throw new InvitationConflict();
        if (campaign.members.containsKey(actor.username) || playCharacterExists(campaign, invitation.characterId)
            || campaign.members.size() >= campaign.maxPlayers) throw new DuplicateId();
        PartyMember member = new PartyMember(actor.username, invitation.characterId, invitation.characterId, "unknown");
        campaign.members.put(actor.username, member);
        invitation.status = "accepted";
        saveStorage();
        return invitationJson(invitation);
    }

    private static synchronized String listInvitations(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = isCampaignDm(campaign, actor);
        StringBuilder out = new StringBuilder("{\"invitations\":[");
        boolean first = true;
        for (Invitation invitation : campaign.invitations.values()) {
            if (!dm && !invitation.username.equals(actor.username)) continue;
            if (!first) out.append(',');
            out.append(invitationJson(invitation));
            first = false;
        }
        return out.append("]}").toString();
    }

    private static synchronized String startPlayCampaign(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        if (!campaign.status.equals("lobby") || campaign.members.size() < 2) throw new CampaignStartConflict();
        campaign.status = "active";
        campaign.currentActor = campaign.members.values().iterator().next().username;
        campaign.turnNumber = 1;
        saveStorage();
        return playCampaignStartJson(campaign);
    }

    private static synchronized FixtureSeedResult seedFixture(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 1 || !body.containsKey("fixture_id") || !"canonical-v1".equals(requiredText(body, "fixture_id"))) throw new IllegalArgumentException();
        if (campaign.fixtureSeeded) return new FixtureSeedResult(false);
        campaign.fixtureSeeded = true;
        saveStorage();
        return new FixtureSeedResult(true);
    }

    private static synchronized String fixtureState(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        if (!campaign.fixtureSeeded) throw new UnknownRecord();
        return fixtureJson();
    }

    private static String fixtureJson() {
        return "{\"fixture_id\":\"canonical-v1\",\"status\":\"seeded\",\"characters\":[{\"character_id\":\"fixture-hero\",\"name\":\"Ari\",\"class\":\"fighter\"},{\"character_id\":\"fixture-mage\",\"name\":\"Bea\",\"class\":\"wizard\"}],\"story\":\"The lantern is lit.\",\"event_ids\":[\"fixture-event-1\",\"fixture-event-2\"]}";
    }

    private static synchronized String updateSessionZeroSettings(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        if (!campaign.status.equals("lobby")) throw new SessionZeroConflict();
        if (body.size() != 3 || !body.containsKey("rules") || !body.containsKey("tone") || !body.containsKey("consent")) throw new IllegalArgumentException();
        String rules = requiredText(body, "rules");
        String tone = requiredText(body, "tone");
        List<Object> consentValues = array(body, "consent");
        if (consentValues.isEmpty()) throw new IllegalArgumentException();
        List<String> consent = new ArrayList<>();
        for (Object value : consentValues) {
            if (!(value instanceof String item) || item.isEmpty() || consent.contains(item)) throw new IllegalArgumentException();
            consent.add(item);
        }
        campaign.sessionZero = new SessionZero(rules, tone, consent);
        saveStorage();
        return sessionZeroJson(campaign.sessionZero);
    }

    private static synchronized String sessionZeroSettings(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        if (campaign.sessionZero == null) throw new UnknownRecord();
        return sessionZeroJson(campaign.sessionZero);
    }

    private static synchronized String createContent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 4 || !body.containsKey("content_id") || !body.containsKey("kind") || !body.containsKey("text") || !body.containsKey("tags")) throw new IllegalArgumentException();
        String contentId = requiredText(body, "content_id");
        String kind = requiredText(body, "kind");
        String text = requiredText(body, "text");
        List<String> tags = uniqueTags(array(body, "tags"), false);
        if (campaign.content.containsKey(contentId)) throw new DuplicateId();
        Content content = new Content(contentId, kind, text, tags);
        campaign.content.put(contentId, content);
        saveStorage();
        return contentJson(content);
    }

    private static synchronized String replaceContentTags(String campaignId, String contentId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 1 || !body.containsKey("tags")) throw new IllegalArgumentException();
        Content content = campaign.content.get(contentId);
        if (content == null) throw new UnknownRecord();
        List<String> tags = uniqueTags(array(body, "tags"), true);
        content.tags.clear();
        content.tags.addAll(tags);
        saveStorage();
        return contentJson(content);
    }

    private static synchronized String listContent(String campaignId, User actor, String excludeTag) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        StringBuilder out = new StringBuilder("{\"content\":[");
        boolean first = true;
        for (Content content : campaign.content.values()) {
            if (!dm && excludeTag != null && content.tags.contains(excludeTag)) continue;
            if (!first) out.append(',');
            out.append(contentJson(content));
            first = false;
        }
        return out.append("]}").toString();
    }

    private static synchronized String createSearchRecord(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 2 || !body.containsKey("record_id") || !body.containsKey("text")) throw new IllegalArgumentException();
        String recordId = requiredText(body, "record_id");
        String text = requiredText(body, "text");
        if (campaign.searchRecords.containsKey(recordId)) throw new IllegalArgumentException();
        for (SearchRecord existing : campaign.searchRecords.values()) {
            if (existing.text.equals(text)) throw new IllegalArgumentException();
        }
        SearchRecord record = new SearchRecord(recordId, text);
        campaign.searchRecords.put(recordId, record);
        saveStorage();
        return searchRecordJson(record);
    }

    private static synchronized String listSearchRecords(String campaignId, User actor, SearchParameters parameters) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        List<SearchRecord> filtered = new ArrayList<>();
        String query = parameters.query.toLowerCase(java.util.Locale.ROOT);
        for (SearchRecord record : campaign.searchRecords.values()) {
            if (record.text.toLowerCase(java.util.Locale.ROOT).contains(query)) filtered.add(record);
        }
        int from = (int) Math.min(parameters.cursor, filtered.size());
        int to = (int) Math.min((long) from + parameters.limit, filtered.size());
        StringBuilder out = new StringBuilder("{\"records\":[");
        for (int i = from; i < to; i++) {
            if (i > from) out.append(',');
            out.append(searchRecordJson(filtered.get(i)));
        }
        out.append("],\"next_cursor\":");
        if (to < filtered.size()) out.append(to); else out.append("null");
        return out.append('}').toString();
    }

    private static synchronized String createRateEvent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        String eventId = requiredText(body, "event_id");
        if (campaign.rateEvents.containsKey(eventId)) throw new IllegalArgumentException();
        long acceptedByActor = campaign.rateEvents.values().stream().filter(event -> event.actor.equals(actor.username)).count();
        if (acceptedByActor >= 2) {
            campaign.rejectedRateEvents++;
            throw new RateLimitExceeded();
        }
        RateEvent event = new RateEvent(eventId, actor.username);
        campaign.rateEvents.put(eventId, event);
        saveStorage();
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"actor\":\"" + escape(event.actor) + "\",\"remaining\":" + (1 - acceptedByActor) + "}";
    }

    private static synchronized String listRateEvents(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        long acceptedByActor = campaign.rateEvents.values().stream().filter(event -> event.actor.equals(actor.username)).count();
        StringBuilder out = new StringBuilder("{\"events\":[");
        boolean first = true;
        for (RateEvent event : campaign.rateEvents.values()) {
            if (!first) out.append(',');
            out.append("{\"event_id\":\"").append(escape(event.eventId)).append("\",\"actor\":\"").append(escape(event.actor)).append("\"}");
            first = false;
        }
        return out.append("],\"remaining\":").append(2 - acceptedByActor).append('}').toString();
    }

    private static synchronized String serviceMetrics(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username)) throw new Forbidden();
        return "{\"accepted_rate_events\":" + campaign.rateEvents.size()
            + ",\"rejected_rate_events\":" + campaign.rejectedRateEvents
            + ",\"projection_events\":" + campaign.projectionEvents.size()
            + ",\"uptime_ticks\":1}";
    }

    private static synchronized String updateServiceMode(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 1 || !body.containsKey("maintenance")) throw new IllegalArgumentException();
        maintenanceMode = bool(body, "maintenance");
        return "{\"maintenance\":" + maintenanceMode + "}";
    }

    private static SearchParameters searchParameters(HttpExchange exchange) {
        String rawQuery = exchange.getRequestURI().getRawQuery();
        String query = "";
        long limit = 2, cursor = 0;
        if (rawQuery == null || rawQuery.isEmpty()) return new SearchParameters(query, limit, cursor);
        Map<String, String> values = new LinkedHashMap<>();
        for (String pair : rawQuery.split("&", -1)) {
            int separator = pair.indexOf('=');
            String key = decodeQuery(separator < 0 ? pair : pair.substring(0, separator));
            String value = decodeQuery(separator < 0 ? "" : pair.substring(separator + 1));
            if (!(key.equals("q") || key.equals("limit") || key.equals("cursor")) || values.put(key, value) != null) throw new IllegalArgumentException();
        }
        if (values.containsKey("q")) query = values.get("q");
        if (values.containsKey("limit")) {
            limit = number(values.get("limit"));
            if (limit < 1 || limit > 3) throw new IllegalArgumentException();
        }
        if (values.containsKey("cursor")) {
            cursor = number(values.get("cursor"));
            if (cursor < 0) throw new IllegalArgumentException();
        }
        return new SearchParameters(query, limit, cursor);
    }

    private static String decodeQuery(String value) {
        return URLDecoder.decode(value, StandardCharsets.UTF_8);
    }

    private static FeedPagination feedPagination(HttpExchange exchange) {
        String rawQuery = exchange.getRequestURI().getRawQuery();
        long cursor = 0, limit = 2;
        if (rawQuery == null || rawQuery.isEmpty()) return new FeedPagination(cursor, limit);
        Map<String, String> values = new LinkedHashMap<>();
        for (String pair : rawQuery.split("&", -1)) {
            int separator = pair.indexOf('=');
            String key = decodeQuery(separator < 0 ? pair : pair.substring(0, separator));
            String value = decodeQuery(separator < 0 ? "" : pair.substring(separator + 1));
            if (!(key.equals("cursor") || key.equals("limit")) || values.put(key, value) != null) throw new IllegalArgumentException();
        }
        if (values.containsKey("cursor")) {
            cursor = number(values.get("cursor"));
            if (cursor < 0) throw new IllegalArgumentException();
        }
        if (values.containsKey("limit")) {
            limit = number(values.get("limit"));
            if (limit < 1 || limit > 3) throw new IllegalArgumentException();
        }
        return new FeedPagination(cursor, limit);
    }

    private static synchronized String appendFeedEvent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        if (body.size() != 2 || !body.containsKey("event_id") || !body.containsKey("text")) throw new IllegalArgumentException();
        String eventId = requiredText(body, "event_id");
        String text = requiredText(body, "text");
        if (campaign.feedEventsById.containsKey(eventId)) throw new FeedEventConflict();
        FeedEvent event = new FeedEvent(eventId, text, campaign.feedEvents.size() + 1L);
        campaign.feedEvents.add(event);
        campaign.feedEventsById.put(eventId, event);
        saveStorage();
        return feedEventJson(event);
    }

    private static synchronized String eventFeed(String campaignId, User actor, FeedPagination pagination) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        int from = (int) Math.min(pagination.cursor, campaign.feedEvents.size());
        int to = (int) Math.min((long) from + pagination.limit, campaign.feedEvents.size());
        StringBuilder out = new StringBuilder("{\"events\":[");
        for (int i = from; i < to; i++) {
            if (i > from) out.append(',');
            out.append(feedEventJson(campaign.feedEvents.get(i)));
        }
        // A cursor represents the caller's consumed count.  Past-end reads
        // must retain it rather than clamping it to the current feed length.
        long nextCursor = pagination.cursor >= campaign.feedEvents.size() ? pagination.cursor : to;
        return out.append("],\"next_cursor\":").append(nextCursor).append('}').toString();
    }

    private static String feedEventJson(FeedEvent event) {
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"text\":\"" + escape(event.text)
            + "\",\"sequence\":" + event.sequence + "}";
    }

    private static String searchRecordJson(SearchRecord record) {
        return "{\"record_id\":\"" + escape(record.recordId) + "\",\"text\":\"" + escape(record.text) + "\"}";
    }

    private static boolean isCampaignDm(PlayCampaign campaign, User actor) {
        return actor.role.equals("dm") && campaign.owner.equals(actor.username);
    }

    private static void requireCampaignReader(PlayCampaign campaign, User actor) {
        if (!isCampaignDm(campaign, actor) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
    }

    private static synchronized String createNote(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        if (body.size() != 3 || !body.containsKey("note_id") || !body.containsKey("text") || !body.containsKey("visibility")) throw new IllegalArgumentException();
        String id = requiredText(body, "note_id"), text = requiredText(body, "text"), visibility = requiredText(body, "visibility");
        if (!visibility.equals("private") && !visibility.equals("party")) throw new IllegalArgumentException();
        if (campaign.notes.containsKey(id)) throw new DuplicateId();
        Note note = new Note(id, text, visibility, actor.username);
        campaign.notes.put(id, note);
        saveStorage();
        return noteJson(note);
    }

    private static synchronized String listNotes(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        boolean dm = isCampaignDm(campaign, actor);
        StringBuilder out = new StringBuilder("{\"notes\":["); boolean first = true;
        for (Note note : campaign.notes.values()) if (dm || note.visibility.equals("party") || note.owner.equals(actor.username)) {
            if (!first) out.append(','); out.append(noteJson(note)); first = false;
        }
        return out.append("]}").toString();
    }

    private static synchronized String readNote(String campaignId, String noteId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        Note note = campaign.notes.get(noteId);
        if (note == null) throw new UnknownRecord();
        if (note.visibility.equals("private") && !isCampaignDm(campaign, actor) && !note.owner.equals(actor.username)) throw new Forbidden();
        return noteJson(note);
    }

    private static synchronized String updateNote(String campaignId, String noteId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        Note note = campaign.notes.get(noteId);
        if (note == null) throw new UnknownRecord();
        if (!note.owner.equals(actor.username)) throw new Forbidden();
        if (body.size() != 2 || !body.containsKey("text") || !body.containsKey("visibility")) throw new IllegalArgumentException();
        String text = requiredText(body, "text"), visibility = requiredText(body, "visibility");
        if (!visibility.equals("private") && !visibility.equals("party")) throw new IllegalArgumentException();
        note.text = text; note.visibility = visibility;
        saveStorage(); return noteJson(note);
    }

    private static synchronized String createWhisper(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !campaign.members.containsKey(actor.username)) throw new Forbidden();
        if (body.size() != 3 || !body.containsKey("whisper_id") || !body.containsKey("to_character_id") || !body.containsKey("text")) throw new IllegalArgumentException();
        String id = requiredText(body, "whisper_id"), target = requiredText(body, "to_character_id"), text = requiredText(body, "text");
        if (campaign.whispers.containsKey(id)) throw new DuplicateId();
        if (!playCharacterExists(campaign, target)) throw new IllegalArgumentException();
        Whisper whisper = new Whisper(id, campaign.members.get(actor.username).characterId, target, text);
        campaign.whispers.put(id, whisper); saveStorage(); return whisperJson(whisper);
    }

    private static synchronized String listWhispers(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor); boolean dm = isCampaignDm(campaign, actor);
        PartyMember member = campaign.members.get(actor.username);
        StringBuilder out = new StringBuilder("{\"whispers\":["); boolean first = true;
        for (Whisper whisper : campaign.whispers.values()) if (dm || (member != null && (whisper.fromCharacterId.equals(member.characterId) || whisper.toCharacterId.equals(member.characterId)))) {
            if (!first) out.append(','); out.append(whisperJson(whisper)); first = false;
        }
        return out.append("]}").toString();
    }

    private static synchronized String characterSheet(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor); PartyMember member = memberByCharacterId(campaign, characterId);
        if (!isCampaignDm(campaign, actor) && !member.owner.equals(actor.username)) throw new Forbidden();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"owner\":\"" + escape(member.owner) + "\",\"name\":\"" + escape(member.name) + "\",\"class\":\"" + escape(member.characterClass) + "\",\"level\":1,\"proficiency_bonus\":2,\"hp_max\":10,\"armor_class\":10}";
    }

    private static String noteJson(Note note) { return "{\"note_id\":\"" + escape(note.noteId) + "\",\"text\":\"" + escape(note.text) + "\",\"visibility\":\"" + note.visibility + "\",\"owner\":\"" + escape(note.owner) + "\"}"; }
    private static String whisperJson(Whisper whisper) { return "{\"whisper_id\":\"" + escape(whisper.whisperId) + "\",\"from_character_id\":\"" + escape(whisper.fromCharacterId) + "\",\"to_character_id\":\"" + escape(whisper.toCharacterId) + "\",\"text\":\"" + escape(whisper.text) + "\"}"; }
    private static String invitationJson(Invitation invitation) { return "{\"invitation_id\":\"" + escape(invitation.invitationId) + "\",\"username\":\"" + escape(invitation.username) + "\",\"character_id\":\"" + escape(invitation.characterId) + "\",\"status\":\"" + invitation.status + "\"}"; }

    private static void requireCampaignDm(PlayCampaign campaign, User actor) {
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
    }

    private static List<String> uniqueTags(List<Object> values, boolean mayBeEmpty) {
        if (!mayBeEmpty && values.isEmpty()) throw new IllegalArgumentException();
        List<String> tags = new ArrayList<>();
        for (Object value : values) {
            if (!(value instanceof String tag) || tag.isEmpty() || tags.contains(tag)) throw new IllegalArgumentException();
            tags.add(tag);
        }
        return tags;
    }

    private static String contentExcludeTag(HttpExchange exchange) {
        String query = exchange.getRequestURI().getRawQuery();
        if (query == null) return null;
        if (!query.startsWith("exclude_tag=") || query.indexOf('&') >= 0) throw new IllegalArgumentException();
        String tag;
        try { tag = java.net.URLDecoder.decode(query.substring("exclude_tag=".length()), StandardCharsets.UTF_8); }
        catch (IllegalArgumentException e) { throw new IllegalArgumentException(); }
        if (tag.isEmpty()) throw new IllegalArgumentException();
        return tag;
    }

    private static synchronized String addNarration(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Delegation delegation = campaign.delegations.get(actor.username);
        if (!isCampaignDm(campaign, actor) && (delegation == null || !delegation.active || !delegation.powers.contains("narrate"))) throw new Forbidden();
        PlayEvent narration = new PlayEvent(nextPlayEventSequence(campaign), "narration", actor.username, null, requiredText(b, "text"), null);
        campaign.events.add(narration);
        saveStorage();
        return narrationJson(narration);
    }

    private static synchronized String addMessage(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        if (body.size() != 1 || !body.containsKey("text")) throw new IllegalArgumentException();
        PlayEvent message = new PlayEvent(nextPlayEventSequence(campaign), "chat", actor.username, null, requiredText(body, "text"), null);
        campaign.events.add(message);
        saveStorage();
        String response = messageJson(message);
        return response.substring(0, response.length() - 1) + ",\"current_actor\":"
            + jsonNullableString(campaign.currentActor) + "}";
    }

    private static synchronized String grantDelegation(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 2 || !body.containsKey("username") || !body.containsKey("powers")) throw new IllegalArgumentException();
        String username = requiredText(body, "username");
        List<Object> values = array(body, "powers");
        if (values.isEmpty()) throw new IllegalArgumentException();
        List<String> powers = new ArrayList<>();
        for (Object value : values) {
            if (!(value instanceof String power) || !power.equals("narrate") || powers.contains(power)) throw new IllegalArgumentException();
            powers.add(power);
        }
        if (!campaign.members.containsKey(username)) throw new IllegalArgumentException();
        Delegation delegation = campaign.delegations.get(username);
        if (delegation != null && delegation.active) throw new DuplicateId();
        if (delegation == null) {
            delegation = new Delegation(username, powers, true);
            campaign.delegations.put(username, delegation);
        } else {
            delegation.powers.clear();
            delegation.powers.addAll(powers);
            delegation.active = true;
        }
        campaign.delegationAudit.add(new DelegationAuditEntry(username, "granted", powers));
        saveStorage();
        return delegationJson(delegation);
    }

    private static synchronized String revokeDelegation(String campaignId, String username, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        Delegation delegation = campaign.delegations.get(username);
        if (delegation == null || !delegation.active) throw new UnknownRecord();
        delegation.active = false;
        campaign.delegationAudit.add(new DelegationAuditEntry(username, "revoked", delegation.powers));
        saveStorage();
        return delegationJson(delegation);
    }

    private static synchronized String delegationAudit(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        StringBuilder out = new StringBuilder("{\"entries\":[");
        for (int i = 0; i < campaign.delegationAudit.size(); i++) {
            if (i > 0) out.append(',');
            out.append(delegationAuditJson(campaign.delegationAudit.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String delegationJson(Delegation delegation) {
        return "{\"username\":\"" + escape(delegation.username) + "\",\"powers\":[\"narrate\"],\"active\":" + delegation.active + "}";
    }

    private static String delegationAuditJson(DelegationAuditEntry entry) {
        return "{\"username\":\"" + escape(entry.username) + "\",\"action\":\"" + entry.action + "\",\"powers\":[\"narrate\"]}";
    }

    private static synchronized String createAuditEvent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        if (body.size() != 2 || !body.containsKey("kind") || !body.containsKey("correlation_id")) throw new IllegalArgumentException();
        String kind = requiredText(body, "kind");
        String correlationId = requiredText(body, "correlation_id");
        if (campaign.auditCorrelationIds.containsKey(correlationId)) throw new DuplicateId();
        AuditEvent entry = new AuditEvent(kind, actor.username, campaign.owner.equals(actor.username) ? "DM" : "player",
            campaign.auditEvents.size() + 1L, correlationId);
        campaign.auditEvents.add(entry);
        campaign.auditCorrelationIds.put(correlationId, entry);
        saveStorage();
        return auditEventJson(entry);
    }

    private static synchronized String auditEvents(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        StringBuilder out = new StringBuilder("{\"entries\":[");
        for (int i = 0; i < campaign.auditEvents.size(); i++) {
            if (i > 0) out.append(',');
            out.append(auditEventJson(campaign.auditEvents.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String auditEventJson(AuditEvent entry) {
        return "{\"kind\":\"" + escape(entry.kind) + "\",\"actor\":\"" + escape(entry.actor)
            + "\",\"role\":\"" + entry.role + "\",\"timestamp\":" + entry.timestamp
            + ",\"correlation_id\":\"" + escape(entry.correlationId) + "\"}";
    }

    private static synchronized String addAction(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !actor.username.equals(campaign.currentActor)) throw new TurnConflict();
        PlayEvent action = new PlayEvent(nextPlayEventSequence(campaign), "action", actor.username,
            requiredText(b, "type"), requiredText(b, "text"), null);
        campaign.events.add(action);
        campaign.currentActor = campaign.owner;
        saveStorage();
        return actionJson(action, campaign.owner);
    }

    private static synchronized String addResolution(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)
            || !campaign.owner.equals(campaign.currentActor)) throw new TurnConflict();
        String nextActor = nextPlayer(campaign);
        PlayEvent resolution = new PlayEvent(nextPlayEventSequence(campaign), "resolution", "dm", null, requiredText(b, "text"), null);
        campaign.events.add(resolution);
        campaign.currentActor = nextActor;
        campaign.turnNumber++;
        saveStorage();
        return resolutionJson(resolution, nextActor, campaign.turnNumber);
    }

    private static synchronized String nudgePlayCampaignTurn(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        String message = requiredText(b, "message");
        campaign.nudgeCount++;
        saveStorage();
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"actor\":\"" + escape(actor.username)
            + "\",\"target\":" + jsonNullableString(campaign.currentActor) + ",\"message\":\""
            + escape(message) + "\",\"nudge_count\":" + campaign.nudgeCount + "}";
    }

    /** The ordered graph's first location is the party's established origin. */
    private static synchronized String travelTurn(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !actor.username.equals(campaign.currentActor)) throw new TurnConflict();
        String destinationId = requiredText(b, "destination_id");
        if (campaign.locations.isEmpty()) throw new TravelConflict();
        Location origin = campaign.locations.values().iterator().next();
        Long travelTurns = origin.connections.get(destinationId);
        if (travelTurns == null) throw new TravelConflict();
        // Existing event columns persist destination and duration without a schema change.
        PlayEvent travel = new PlayEvent(nextPlayEventSequence(campaign), "travel", actor.username,
            destinationId, Long.toString(travelTurns), null);
        campaign.events.add(travel);
        campaign.currentActor = campaign.owner;
        saveStorage();
        return travelJson(travel, campaign.owner);
    }

    private static synchronized String restTurn(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !actor.username.equals(campaign.currentActor)) throw new TurnConflict();
        String type = string(b, "type");
        if (!type.equals("short") && !type.equals("long")) throw new IllegalArgumentException();
        PartyMember member = campaign.members.get(actor.username);
        if (type.equals("long")) restoreMember(member, member.hpMax);
        PlayEvent rest = new PlayEvent(nextPlayEventSequence(campaign), "rest", actor.username, type, "", null);
        campaign.events.add(rest);
        campaign.currentActor = campaign.owner;
        saveStorage();
        return restJson(rest, member, campaign.owner);
    }

    private static synchronized String createEncounter(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        if (ENCOUNTERS.containsKey(id) || campaign.activeEncounterId != null) throw new DuplicateId();
        Encounter encounter = new Encounter(id, campaign.id, name);
        ENCOUNTERS.put(id, encounter);
        campaign.activeEncounterId = id;
        saveStorage();
        return encounterJson(encounter);
    }

    private static synchronized String addEncounterMonster(String campaignId, String encounterId, User actor, Map<String, Object> b) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        String monsterId = requiredText(b, "monster_id");
        String name = requiredText(b, "name");
        long hpMax = positive(integer(b, "hp_max"));
        long initiative = integer(b, "initiative");
        if (encounter.monsters.containsKey(monsterId)) throw new DuplicateId();
        EncounterMonster monster = new EncounterMonster(monsterId, name, hpMax, initiative);
        encounter.monsters.put(monsterId, monster);
        encounter.conditions.put(monsterId, new ArrayList<>());
        saveStorage();
        return encounterMonsterJson(monster);
    }

    private static synchronized String removeEncounterMonster(String campaignId, String encounterId, String monsterId, User actor) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        if (encounter.monsters.remove(monsterId) == null) throw new UnknownRecord();
        encounter.conditions.remove(monsterId);
        saveStorage();
        return "{\"removed\":\"" + escape(monsterId) + "\"}";
    }

    private static synchronized String addEncounterCombatant(String campaignId, String encounterId, User actor, Map<String, Object> b) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        String username = requiredText(b, "member");
        long initiative = integer(b, "initiative");
        PartyMember member = campaign.members.get(username);
        if (member == null) throw new IllegalArgumentException();
        if (encounter.combatants.containsKey(username)) throw new DuplicateId();
        EncounterCombatant combatant = new EncounterCombatant(username, member.characterId, member.name, initiative);
        encounter.combatants.put(username, combatant);
        encounter.conditions.put(username, new ArrayList<>());
        saveStorage();
        return encounterCombatantJson(combatant);
    }

    private static synchronized String removeEncounterCombatant(String campaignId, String encounterId, String username, User actor) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        if (encounter.combatants.remove(username) == null) throw new UnknownRecord();
        encounter.conditions.remove(username);
        saveStorage();
        return "{\"removed\":\"" + escape(username) + "\"}";
    }

    private static synchronized String encounterTurn(String campaignId, String encounterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        Encounter encounter = encounter(campaignId, encounterId);
        return encounterTurnJson(encounter);
    }

    private static synchronized String advanceEncounterTurn(String campaignId, String encounterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Encounter encounter = encounter(campaignId, encounterId);
        CombatTurnEntry active = activeCombatant(encounter);
        if (!campaign.owner.equals(actor.username) && !actor.username.equals(active.username)) throw new TurnConflict();
        List<CombatTurnEntry> order = encounterOrder(encounter);
        encounter.turnIndex++;
        if (encounter.turnIndex == order.size()) {
            encounter.turnIndex = 0;
            encounter.round++;
        }
        expireEncounterConditions(encounter, activeCombatant(encounter).id);
        saveStorage();
        return encounterTurnJson(encounter);
    }

    private static synchronized String delayEncounterTurn(String campaignId, String encounterId, User actor,
                                                           Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Encounter encounter = encounter(campaignId, encounterId);
        CombatTurnEntry active = activeCombatant(encounter);
        if (!campaign.owner.equals(actor.username) && !actor.username.equals(active.username)) throw new TurnConflict();
        List<CombatTurnEntry> order = encounterOrder(encounter);
        int destination = delayDestination(b);
        if (destination <= encounter.turnIndex || destination >= order.size()) throw new IllegalArgumentException();
        CombatTurnEntry delayed = order.remove((int) encounter.turnIndex);
        order.add(destination, delayed);
        // Reordering initiative does not end the active combatant's turn.  Keep
        // the cursor with that combatant at its new position so it can still
        // take its (possibly readied) action exactly once.
        encounter.turnIndex = destination;
        encounter.turnOrder = new ArrayList<>();
        for (CombatTurnEntry entry : order) encounter.turnOrder.add(turnEntryKey(entry));
        saveStorage();
        return encounterOrderJson(order);
    }

    private static synchronized String readyEncounterTurn(String campaignId, String encounterId, User actor,
                                                           Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        CombatTurnEntry active = activeCombatant(encounter(campaignId, encounterId));
        if (active.username == null || !actor.username.equals(active.username)) throw new TurnConflict();
        return "{\"actor\":\"" + escape(actor.username) + "\",\"trigger\":\""
            + escape(requiredText(b, "trigger")) + "\"}";
    }

    private static int delayDestination(Map<String, Object> b) {
        for (String key : List.of("index", "position", "to_index", "target_index", "new_index", "destination")) {
            Object value = b.get(key);
            if (value instanceof Long number) return Math.toIntExact(number);
        }
        if (b.size() == 1) {
            Object value = b.values().iterator().next();
            if (value instanceof Long number) return Math.toIntExact(number);
        }
        throw new IllegalArgumentException();
    }

    private static synchronized String addEncounterCondition(String campaignId, String encounterId, User actor,
                                                              Map<String, Object> b) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        String target = requiredText(b, "target");
        if (!encounter.conditions.containsKey(target)) throw new UnknownRecord();
        String condition = requiredText(b, "condition");
        long duration = positive(integer(b, "duration_rounds"));
        List<Condition> attached = encounter.conditions.get(target);
        attached.add(new Condition(condition, duration));
        saveStorage();
        return "{\"target\":\"" + escape(target) + "\",\"conditions\":" + conditionsArray(attached) + "}";
    }

    private static synchronized String encounterStatus(String campaignId, String encounterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        return encounterStatusJson(encounter(campaignId, encounterId));
    }

    private static synchronized String awardEncounterRewards(String campaignId, String encounterId, User actor,
                                                              Map<String, Object> b) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        if (!encounter.status.equals("active") || encounter.reward != null) throw new DuplicateId();
        long xp = integer(b, "xp");
        if (xp < 0) throw new IllegalArgumentException();
        List<Loot> loot = new ArrayList<>();
        List<Object> requestedLoot = b.containsKey("loot") ? array(b, "loot") : List.of();
        for (Object value : requestedLoot) {
            Map<String, Object> item = asObject(value);
            String slug = requiredText(item, "slug");
            loot.add(new Loot(slug, positive(integer(item, "quantity"))));
        }
        encounter.reward = new EncounterReward(xp, loot);
        saveStorage();
        return encounterRewardJson(encounter.id, encounter.reward);
    }

    private static synchronized String closeEncounter(String campaignId, String encounterId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Encounter encounter = encounter(campaignId, encounterId);
        encounter.status = "closed";
        // Closing records the encounter result, but the campaign remains in its
        // combat transition until /end restores the exploration queue.  Keeping
        // this reference also lets /end finalize a previously closed encounter.
        saveStorage();
        long xp = encounter.reward == null ? 0 : encounter.reward.xp;
        return "{\"id\":\"" + escape(encounter.id) + "\",\"status\":\"closed\",\"xp_awarded\":" + xp + "}";
    }

    private static synchronized String endEncounter(String campaignId, String encounterId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Encounter encounter = encounter(campaignId, encounterId);
        if (!encounter.id.equals(campaign.activeEncounterId)) {
            throw new EncounterTransitionConflict();
        }
        encounter.status = "closed";
        campaign.activeEncounterId = null;
        // Combat is a distinct turn system.  Returning to exploration starts a
        // fresh party rotation rather than inheriting the last exploration
        // actor from before combat began.
        campaign.nextResolutionStartsParty = true;
        // Encounter setup is DM-controlled.  Once its separate turn system is
        // closed, authority returns to the DM for the exploration transition.
        campaign.currentActor = campaign.owner;
        saveStorage();
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"status\":\""
            + campaign.status + "\",\"phase\":\"exploration\",\"current_actor\":"
            + jsonNullableString(campaign.currentActor) + "}";
    }

    private static synchronized String changeEncounterHitPoints(String campaignId, String encounterId, User actor,
                                                                  Map<String, Object> b, boolean healing) {
        Encounter encounter = ownedEncounter(campaignId, encounterId, actor);
        String target = requiredText(b, "target");
        long amount = positive(integer(b, "amount"));
        long before;
        long after;
        EncounterMonster monster = encounter.monsters.get(target);
        if (monster != null) {
            before = monster.hpCurrent;
            after = healing ? cappedHealing(before, monster.hpMax, amount) : flooredDamage(before, amount);
            monster.hpCurrent = after;
        } else {
            EncounterCombatant combatant = encounter.combatants.get(target);
            PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
            PartyMember member = combatant == null ? null : campaign.members.get(combatant.username);
            if (member == null) throw new UnknownRecord();
            before = member.hpCurrent;
            after = healing ? cappedHealing(before, member.hpMax, amount) : flooredDamage(before, amount);
            if (healing) restoreMember(member, after); else setMemberHitPoints(member, after);
        }
        saveStorage();
        return "{\"target\":\"" + escape(target) + "\",\"hp_before\":" + before + ",\"hp_after\":" + after
            + ",\"" + (healing ? "healing" : "damage") + "\":" + amount + "}";
    }

    private static long flooredDamage(long hp, long amount) {
        return amount >= hp ? 0 : hp - amount;
    }

    private static long cappedHealing(long hp, long hpMax, long amount) {
        return amount >= hpMax - hp ? hpMax : hp + amount;
    }

    private static synchronized String damageCharacter(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!campaign.owner.equals(actor.username)) throw new Forbidden();
        long amount = positive(integer(b, "amount"));
        long before = member.hpCurrent;
        setMemberHitPoints(member, flooredDamage(before, amount));
        saveStorage();
        return "{\"target\":\"" + escape(member.characterId) + "\",\"character_id\":\""
            + escape(member.characterId) + "\",\"hp_before\":" + before + ",\"hp_after\":"
            + member.hpCurrent + ",\"damage\":" + amount + "}";
    }

    private static synchronized String deathSave(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!member.username.equals(actor.username)) throw new Forbidden();
        if (!member.status.equals("unconscious")) throw new DeathSaveConflict();
        String outcome = string(b, "outcome");
        if (outcome.equals("success")) member.deathSaveSuccesses++;
        else if (outcome.equals("failure")) member.deathSaveFailures++;
        else throw new IllegalArgumentException();
        if (member.deathSaveSuccesses >= 3) member.status = "stable";
        else if (member.deathSaveFailures >= 3) member.status = "dead";
        saveStorage();
        return deathSaveJson(member);
    }

    private static synchronized String characterStatus(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"hp_current\":" + member.hpCurrent
            + ",\"hp_max\":" + member.hpMax + ",\"status\":\"" + member.status + "\"}";
    }

    private static synchronized String characterOwner(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        return characterOwnerJson(member);
    }

    private static synchronized String characterSpells(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        StringBuilder out = new StringBuilder("{\"spells\":[");
        boolean first = true;
        for (Spell spell : member.spells.values()) {
            if (!first) out.append(',');
            first = false;
            out.append(spellJson(spell));
        }
        return out.append("]}").toString();
    }

    private static synchronized String characterInventory(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        return characterInventoryJson(memberByCharacterId(campaign, characterId));
    }

    private static synchronized String createRecipe(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        String recipeId = requiredText(b, "recipe_id");
        String name = requiredText(b, "name");
        Map<String, Object> requestedIngredients = asObject(b.get("ingredients"));
        if (requestedIngredients.isEmpty()) throw new IllegalArgumentException();
        Map<String, Long> ingredients = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : requestedIngredients.entrySet()) {
            if (!isInventoryItem(entry.getKey()) || !(entry.getValue() instanceof Long quantity)) throw new IllegalArgumentException();
            ingredients.put(entry.getKey(), positive(quantity));
        }
        String outputItem = requiredText(b, "output_item");
        long outputQuantity = positive(integer(b, "output_quantity"));
        if (!isInventoryItem(outputItem)) throw new IllegalArgumentException();
        if (campaign.recipes.containsKey(recipeId)) throw new DuplicateId();
        Recipe recipe = new Recipe(recipeId, name, ingredients, outputItem, outputQuantity);
        campaign.recipes.put(recipeId, recipe);
        saveStorage();
        return recipeJson(recipe);
    }

    private static synchronized String createDowntimeActivity(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        String activityId = requiredText(b, "activity_id");
        String name = requiredText(b, "name");
        long cyclesRequired = integer(b, "cycles_required");
        if (cyclesRequired < 1 || cyclesRequired > 10) throw new IllegalArgumentException();
        if (campaign.downtimeActivities.containsKey(activityId)) throw new DuplicateId();
        DowntimeActivity activity = new DowntimeActivity(activityId, name, cyclesRequired);
        campaign.downtimeActivities.put(activityId, activity);
        saveStorage();
        return downtimeActivityJson(activity);
    }

    private static synchronized String createDowntimeAllocation(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.role.equals("player") || !actor.username.equals(member.owner)) throw new Forbidden();
        String activityId = requiredText(b, "activity_id");
        if (!campaign.downtimeActivities.containsKey(activityId)) throw new UnknownRecord();
        if (member.downtimeAllocations.containsKey(activityId)) throw new DuplicateId();
        DowntimeAllocation allocation = new DowntimeAllocation(member.characterId, activityId);
        member.downtimeAllocations.put(activityId, allocation);
        saveStorage();
        return downtimeAllocationJson(allocation);
    }

    private static synchronized String progressDowntimeAllocation(String campaignId, String characterId, String activityId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.role.equals("player") || !actor.username.equals(member.owner)) throw new Forbidden();
        DowntimeActivity activity = campaign.downtimeActivities.get(activityId);
        if (activity == null) throw new UnknownRecord();
        DowntimeAllocation allocation = member.downtimeAllocations.get(activityId);
        if (allocation == null) throw new UnknownRecord();
        allocation.cyclesCompleted++;
        if (allocation.cyclesCompleted == activity.cyclesRequired) {
            allocation.cyclesCompleted = 0;
            allocation.completions++;
        }
        saveStorage();
        return downtimeAllocationJson(allocation);
    }

    private static synchronized String readDowntimeAllocation(String campaignId, String characterId, String activityId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!campaign.downtimeActivities.containsKey(activityId)) throw new UnknownRecord();
        DowntimeAllocation allocation = member.downtimeAllocations.get(activityId);
        if (allocation == null) throw new UnknownRecord();
        return downtimeAllocationJson(allocation);
    }

    private static String downtimeActivityJson(DowntimeActivity activity) {
        return "{\"activity_id\":\"" + escape(activity.activityId) + "\",\"name\":\"" + escape(activity.name)
            + "\",\"cycles_required\":" + activity.cyclesRequired + "}";
    }

    private static String downtimeAllocationJson(DowntimeAllocation allocation) {
        return "{\"character_id\":\"" + escape(allocation.characterId) + "\",\"activity_id\":\""
            + escape(allocation.activityId) + "\",\"cycles_completed\":" + allocation.cyclesCompleted
            + ",\"completions\":" + allocation.completions + "}";
    }

    private static synchronized String listRecipes(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        StringBuilder out = new StringBuilder("{\"recipes\":[");
        boolean first = true;
        for (Recipe recipe : campaign.recipes.values()) {
            if (!first) out.append(',');
            first = false;
            out.append(recipeJson(recipe));
        }
        return out.append("]}").toString();
    }

    private static synchronized String craftRecipe(String campaignId, String recipeId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || campaign.owner.equals(actor.username)) throw new Forbidden();
        Recipe recipe = campaign.recipes.get(recipeId);
        if (recipe == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, requiredText(b, "character_id"));
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        for (Map.Entry<String, Long> ingredient : recipe.ingredients.entrySet()) {
            if (member.inventory.getOrDefault(ingredient.getKey(), 0L) < ingredient.getValue()) throw new InventoryConflict();
        }
        long outputTotal;
        try {
            long outputBase = member.inventory.getOrDefault(recipe.outputItem, 0L)
                - recipe.ingredients.getOrDefault(recipe.outputItem, 0L);
            outputTotal = Math.addExact(outputBase, recipe.outputQuantity);
        }
        catch (ArithmeticException e) { throw new IllegalArgumentException(); }
        for (Map.Entry<String, Long> ingredient : recipe.ingredients.entrySet()) {
            long remaining = member.inventory.get(ingredient.getKey()) - ingredient.getValue();
            if (remaining == 0) member.inventory.remove(ingredient.getKey()); else member.inventory.put(ingredient.getKey(), remaining);
        }
        member.inventory.put(recipe.outputItem, outputTotal);
        saveStorage();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"recipe_id\":\"" + escape(recipe.recipeId)
            + "\",\"output_item\":\"" + escape(recipe.outputItem) + "\",\"output_quantity\":" + recipe.outputQuantity + "}";
    }

    private static String recipeJson(Recipe recipe) {
        StringBuilder ingredients = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Long> entry : recipe.ingredients.entrySet()) {
            if (!first) ingredients.append(',');
            first = false;
            ingredients.append("\"").append(escape(entry.getKey())).append("\":").append(entry.getValue());
        }
        return "{\"recipe_id\":\"" + escape(recipe.recipeId) + "\",\"name\":\"" + escape(recipe.name)
            + "\",\"ingredients\":" + ingredients.append('}') + ",\"output_item\":\"" + escape(recipe.outputItem)
            + "\",\"output_quantity\":" + recipe.outputQuantity + "}";
    }

    private static synchronized String characterCurrency(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"gold\":" + member.gold + "}";
    }

    private static synchronized String transferCurrency(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember source = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(source.owner)) throw new Forbidden();
        String destinationId = string(b, "to_character_id");
        long gold = positive(integer(b, "gold"));
        if (characterId.equals(destinationId)) throw new IllegalArgumentException();
        PartyMember destination;
        try { destination = memberByCharacterId(campaign, destinationId); }
        catch (UnknownRecord e) { throw new IllegalArgumentException(); }
        if (source.gold < gold) throw new CurrencyConflict();
        long destinationGold;
        try { destinationGold = Math.addExact(destination.gold, gold); }
        catch (ArithmeticException e) { throw new IllegalArgumentException(); }
        source.gold -= gold;
        destination.gold = destinationGold;
        long transferId = ++campaign.currencyTransferId;
        saveStorage();
        return "{\"from_character_id\":\"" + escape(source.characterId) + "\",\"to_character_id\":\""
            + escape(destination.characterId) + "\",\"gold\":" + gold + ",\"from_gold\":" + source.gold
            + ",\"to_gold\":" + destination.gold + ",\"transfer_id\":" + transferId + "}";
    }

    private static synchronized String createTransactionalTransfer(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !campaign.members.containsKey(actor.username)) throw new Forbidden();
        if (body.size() != 4 || !body.containsKey("from_character_id") || !body.containsKey("to_character_id")
            || !body.containsKey("amount") || !body.containsKey("simulate_failure")) throw new IllegalArgumentException();

        String fromId = requiredText(body, "from_character_id");
        String toId = requiredText(body, "to_character_id");
        long amount = positive(integer(body, "amount"));
        boolean simulateFailure = bool(body, "simulate_failure");
        if (fromId.equals(toId)) throw new IllegalArgumentException();

        PartyMember from;
        PartyMember to;
        try {
            from = memberByCharacterId(campaign, fromId);
            to = memberByCharacterId(campaign, toId);
        } catch (UnknownRecord e) {
            throw new IllegalArgumentException();
        }
        if (!actor.username.equals(from.owner)) throw new Forbidden();
        if (from.gold < amount) throw new CurrencyConflict();

        final long fromGold;
        final long toGold;
        try {
            fromGold = Math.subtractExact(from.gold, amount);
            toGold = Math.addExact(to.gold, amount);
        } catch (ArithmeticException e) {
            throw new IllegalArgumentException();
        }
        if (simulateFailure) throw new SimulatedFailure();

        long sequence = Math.addExact(campaign.transactionalTransferSequence, 1);
        TransactionalTransfer transfer = new TransactionalTransfer(from.characterId, to.characterId, amount, fromGold, toGold, sequence);
        from.gold = fromGold;
        to.gold = toGold;
        campaign.transactionalTransfers.add(transfer);
        campaign.transactionalTransferSequence = sequence;
        saveStorage();
        return transactionalTransferJson(transfer);
    }

    private static synchronized String transactionalTransfers(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignReader(campaign, actor);
        StringBuilder out = new StringBuilder("{\"transfers\":[");
        for (int i = 0; i < campaign.transactionalTransfers.size(); i++) {
            if (i > 0) out.append(',');
            out.append(transactionalTransferJson(campaign.transactionalTransfers.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String transactionalTransferJson(TransactionalTransfer transfer) {
        return "{\"from_character_id\":\"" + escape(transfer.fromCharacterId) + "\",\"to_character_id\":\""
            + escape(transfer.toCharacterId) + "\",\"amount\":" + transfer.amount + ",\"from_gold\":" + transfer.fromGold
            + ",\"to_gold\":" + transfer.toGold + ",\"sequence\":" + transfer.sequence + "}";
    }

    private static synchronized String addCharacterInventoryItem(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String itemId = string(b, "item_id");
        long quantity = positive(integer(b, "quantity"));
        if (!isInventoryItem(itemId)) throw new IllegalArgumentException();
        long total = Math.addExact(member.inventory.getOrDefault(itemId, 0L), quantity);
        member.inventory.put(itemId, total);
        saveStorage();
        return characterInventoryItemJson(member.characterId, itemId, quantity, total);
    }

    private static synchronized String removeCharacterInventoryItem(String campaignId, String characterId, String itemId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        long quantity = positive(integer(b, "quantity"));
        if (!isInventoryItem(itemId)) throw new IllegalArgumentException();
        long held = member.inventory.getOrDefault(itemId, 0L);
        if (quantity > held) throw new InventoryConflict();
        long total = held - quantity;
        if (total == 0) member.inventory.remove(itemId);
        else member.inventory.put(itemId, total);
        saveStorage();
        return characterInventoryItemJson(member.characterId, itemId, quantity, total);
    }

    private static synchronized String consumeCharacterInventoryItem(String campaignId, String characterId, String itemId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        if (!itemId.equals("healing-potion")) throw new IllegalArgumentException();
        long held = member.inventory.getOrDefault(itemId, 0L);
        if (held <= 0) throw new InventoryConflict();
        long total = held - 1;
        if (total == 0) member.inventory.remove(itemId);
        else member.inventory.put(itemId, total);
        saveStorage();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"item_id\":\"healing-potion\",\"quantity_consumed\":1,\"total_quantity\":" + total
            + ",\"effect\":{\"type\":\"healing\",\"hp_restored\":5}}";
    }

    private static synchronized String createLoot(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username)) throw new Forbidden();
        String lootId = string(b, "loot_id");
        String itemId = string(b, "item_id");
        long quantity = positive(integer(b, "quantity"));
        if (!isInventoryItem(itemId)) throw new IllegalArgumentException();
        if (campaign.loot.containsKey(lootId)) throw new LootConflict();
        LootRecord loot = new LootRecord(lootId, itemId, quantity);
        campaign.loot.put(lootId, loot);
        saveStorage();
        return "{\"loot_id\":\"" + escape(lootId) + "\",\"item_id\":\"" + escape(itemId)
            + "\",\"quantity\":" + quantity + ",\"status\":\"open\"}";
    }

    private static synchronized String voteLoot(String campaignId, String lootId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        LootRecord loot = lootById(campaign, lootId);
        if (!loot.status.equals("open") || loot.votes.containsKey(actor.username)) throw new LootConflict();
        String recipientId = string(b, "recipient_character_id");
        try { memberByCharacterId(campaign, recipientId); }
        catch (UnknownRecord e) { throw new IllegalArgumentException(); }
        loot.votes.put(actor.username, recipientId);
        long count = voteCount(loot, recipientId);
        saveStorage();
        return "{\"loot_id\":\"" + escape(lootId) + "\",\"voter\":\"" + escape(actor.username)
            + "\",\"recipient_character_id\":\"" + escape(recipientId) + "\",\"votes_for_recipient\":" + count + "}";
    }

    private static synchronized String assignLoot(String campaignId, String lootId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username)) throw new Forbidden();
        LootRecord loot = lootById(campaign, lootId);
        if (!loot.status.equals("open") || loot.votes.isEmpty()) throw new LootConflict();
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String recipient : loot.votes.values()) counts.put(recipient, counts.getOrDefault(recipient, 0L) + 1);
        String winner = null;
        long high = 0;
        boolean tied = false;
        for (Map.Entry<String, Long> entry : counts.entrySet()) {
            if (entry.getValue() > high) { winner = entry.getKey(); high = entry.getValue(); tied = false; }
            else if (entry.getValue() == high) tied = true;
        }
        if (tied) throw new LootConflict();
        PartyMember recipient = memberByCharacterId(campaign, winner);
        long total;
        try { total = Math.addExact(recipient.inventory.getOrDefault(loot.itemId, 0L), loot.quantity); }
        catch (ArithmeticException e) { throw new IllegalArgumentException(); }
        recipient.inventory.put(loot.itemId, total);
        loot.status = "assigned";
        loot.recipientCharacterId = winner;
        loot.assignedVotes = high;
        saveStorage();
        return lootAssignmentJson(loot);
    }

    private static synchronized String readLoot(String campaignId, String lootId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        return lootJson(lootById(campaign, lootId));
    }

    private static synchronized String createSettlement(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String settlementId = requiredText(b, "settlement_id");
        SettlementFields fields = settlementFields(b);
        if (campaign.settlements.containsKey(settlementId)) throw new DuplicateId();
        Settlement settlement = new Settlement(settlementId, fields.name, fields.services, fields.availability);
        campaign.settlements.put(settlementId, settlement);
        saveStorage();
        return settlementJson(settlement, null);
    }

    private static synchronized String updateSettlement(String campaignId, String settlementId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Settlement settlement = campaign.settlements.get(settlementId);
        if (settlement == null) throw new UnknownRecord();
        SettlementFields fields = settlementFields(b);
        settlement.name = fields.name;
        settlement.services.clear();
        settlement.services.addAll(fields.services);
        settlement.availability = fields.availability;
        saveStorage();
        return settlementJson(settlement, null);
    }

    private static synchronized DiscoveryResult discoverSettlement(String campaignId, String settlementId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !campaign.members.containsKey(actor.username)) throw new Forbidden();
        Settlement settlement = campaign.settlements.get(settlementId);
        if (settlement == null) throw new UnknownRecord();
        String characterId = campaign.members.get(actor.username).characterId;
        boolean created = !settlement.discoveredBy.contains(characterId);
        if (created) {
            settlement.discoveredBy.add(characterId);
            saveStorage();
        }
        return new DiscoveryResult(created, settlementJson(settlement, characterId));
    }

    private static synchronized String settlements(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        String characterId = dm ? null : campaign.members.get(actor.username).characterId;
        StringBuilder out = new StringBuilder("{\"settlements\":[");
        for (Settlement settlement : campaign.settlements.values()) {
            if (!dm && !settlement.discoveredBy.contains(characterId)) continue;
            if (out.length() > 16) out.append(',');
            out.append(settlementJson(settlement, characterId));
        }
        return out.append("]}").toString();
    }

    private static SettlementFields settlementFields(Map<String, Object> b) {
        String name = requiredText(b, "name");
        List<String> services = new ArrayList<>();
        for (String service : strings(array(b, "services"))) {
            String normalized = service.trim();
            if (normalized.isEmpty() || services.contains(normalized)) throw new IllegalArgumentException();
            services.add(normalized);
        }
        if (services.isEmpty()) throw new IllegalArgumentException();
        String availability = requiredText(b, "availability");
        if (!availability.equals("open") && !availability.equals("limited") && !availability.equals("closed")) throw new IllegalArgumentException();
        return new SettlementFields(name, services, availability);
    }

    private static String settlementJson(Settlement settlement, String characterId) {
        List<String> discoverers = characterId == null ? settlement.discoveredBy
            : settlement.discoveredBy.contains(characterId) ? List.of(characterId) : List.of();
        return "{\"settlement_id\":\"" + escape(settlement.settlementId) + "\",\"name\":\"" + escape(settlement.name)
            + "\",\"services\":" + jsonStrings(settlement.services) + ",\"availability\":\"" + settlement.availability
            + "\",\"discovered_by\":" + jsonStrings(discoverers) + "}";
    }

    private static synchronized String createShop(String campaignId, String settlementId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Settlement settlement = campaign.settlements.get(settlementId);
        if (settlement == null) throw new UnknownRecord();
        String shopId = requiredText(b, "shop_id");
        String name = requiredText(b, "name");
        Map<String, Object> suppliedStock = asObject(b.get("stock"));
        Map<String, Long> stock = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : suppliedStock.entrySet()) {
            if (!isInventoryItem(entry.getKey()) || !(entry.getValue() instanceof Long quantity)) throw new IllegalArgumentException();
            stock.put(entry.getKey(), positive(quantity));
        }
        if (stock.isEmpty()) throw new IllegalArgumentException();
        long buyPrice = positive(integer(b, "buy_price"));
        long sellPrice = integer(b, "sell_price");
        if (sellPrice < 0) throw new IllegalArgumentException();
        if (settlement.shops.containsKey(shopId)) throw new DuplicateId();
        Shop shop = new Shop(shopId, name, stock, buyPrice, sellPrice);
        settlement.shops.put(shopId, shop);
        saveStorage();
        return shopJson(shop);
    }

    private static synchronized String readShop(String campaignId, String settlementId, String shopId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Settlement settlement = campaign.settlements.get(settlementId);
        if (settlement == null) throw new UnknownRecord();
        Shop shop = settlement.shops.get(shopId);
        if (shop == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm) {
            if (!actor.role.equals("player") || !campaign.members.containsKey(actor.username)) throw new Forbidden();
            if (!settlement.discoveredBy.contains(campaign.members.get(actor.username).characterId)) throw new UnknownRecord();
        }
        return shopJson(shop);
    }

    private static synchronized String tradeShop(String campaignId, String settlementId, String shopId, boolean buying, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Settlement settlement = campaign.settlements.get(settlementId);
        if (settlement == null) throw new UnknownRecord();
        Shop shop = settlement.shops.get(shopId);
        if (shop == null) throw new UnknownRecord();
        String characterId = string(b, "character_id");
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.role.equals("player") || !actor.username.equals(member.owner)) throw new Forbidden();
        String itemId = string(b, "item_id");
        long quantity = positive(integer(b, "quantity"));
        if (!isInventoryItem(itemId)) throw new IllegalArgumentException();
        long stock = shop.stock.getOrDefault(itemId, 0L);
        long held = member.inventory.getOrDefault(itemId, 0L);
        if (buying) {
            if (stock < quantity) throw new ShopStockConflict();
            long cost;
            long inventoryTotal;
            try { cost = Math.multiplyExact(shop.buyPrice, quantity); inventoryTotal = Math.addExact(held, quantity); }
            catch (ArithmeticException e) { throw new IllegalArgumentException(); }
            if (member.gold < cost) throw new CurrencyConflict();
            shop.stock.put(itemId, stock - quantity);
            member.gold -= cost;
            member.inventory.put(itemId, inventoryTotal);
        } else {
            if (held < quantity) throw new InventoryConflict();
            long proceeds;
            long stockTotal;
            long goldTotal;
            try { proceeds = Math.multiplyExact(shop.sellPrice, quantity); stockTotal = Math.addExact(stock, quantity); goldTotal = Math.addExact(member.gold, proceeds); }
            catch (ArithmeticException e) { throw new IllegalArgumentException(); }
            if (held == quantity) member.inventory.remove(itemId); else member.inventory.put(itemId, held - quantity);
            member.gold = goldTotal;
            shop.stock.put(itemId, stockTotal);
        }
        saveStorage();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"item_id\":\"" + escape(itemId)
            + "\",\"quantity\":" + quantity + ",\"gold\":" + member.gold + ",\"stock\":" + shop.stock.get(itemId) + "}";
    }

    private static String shopJson(Shop shop) {
        StringBuilder stock = new StringBuilder("{");
        for (Map.Entry<String, Long> item : shop.stock.entrySet()) {
            if (stock.length() > 1) stock.append(',');
            stock.append('"').append(escape(item.getKey())).append("\":").append(item.getValue());
        }
        return "{\"shop_id\":\"" + escape(shop.shopId) + "\",\"name\":\"" + escape(shop.name)
            + "\",\"stock\":" + stock.append('}') + ",\"buy_price\":" + shop.buyPrice + ",\"sell_price\":" + shop.sellPrice + "}";
    }

    private static synchronized String createPlayNpc(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        String npcId = requiredText(b, "npc_id");
        String name = requiredText(b, "name");
        String agenda = requiredText(b, "agenda");
        String publicStatus = requiredText(b, "public_status");
        if (campaign.npcs.containsKey(npcId)) throw new DuplicateId();
        PlayNpc npc = new PlayNpc(npcId, name, agenda, publicStatus);
        campaign.npcs.put(npcId, npc);
        saveStorage();
        return playNpcJson(npc, true);
    }

    private static synchronized String updatePlayNpcAgenda(String campaignId, String npcId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        PlayNpc npc = playNpcById(campaign, npcId);
        npc.agenda = requiredText(b, "agenda");
        npc.publicStatus = requiredText(b, "public_status");
        saveStorage();
        return playNpcJson(npc, true);
    }

    private static synchronized String readPlayNpc(String campaignId, String npcId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        return playNpcJson(playNpcById(campaign, npcId), dm);
    }

    private static synchronized String appendNpcDialogue(String campaignId, String npcId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        PlayNpc npc = playNpcById(campaign, npcId);
        String dialogueId = requiredText(b, "dialogue_id");
        String speaker = requiredText(b, "speaker");
        String text = requiredText(b, "text");
        String visibility = requiredText(b, "visibility");
        if (!visibility.equals("public") && !visibility.equals("private")) throw new IllegalArgumentException();
        for (DialogueEntry entry : npc.dialogue) if (entry.dialogueId.equals(dialogueId)) throw new DuplicateId();
        DialogueEntry entry = new DialogueEntry(dialogueId, speaker, text, visibility);
        npc.dialogue.add(entry);
        saveStorage();
        return dialogueJson(entry);
    }

    private static synchronized String npcDialogue(String campaignId, String npcId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        PlayNpc npc = playNpcById(campaign, npcId);
        StringBuilder entries = new StringBuilder("[");
        boolean first = true;
        for (DialogueEntry entry : npc.dialogue) {
            if (!dm && entry.visibility.equals("private")) continue;
            if (!first) entries.append(',');
            first = false;
            entries.append(dialogueJson(entry));
        }
        return "{\"npc_id\":\"" + escape(npcId) + "\",\"entries\":" + entries.append("]}");
    }

    private static synchronized String createRelationship(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String sourceId = requiredText(b, "source_id");
        String targetId = requiredText(b, "target_id");
        String kind = requiredText(b, "kind");
        long score = integer(b, "score");
        if (sourceId.equals(targetId) || score < -100 || score > 100) throw new IllegalArgumentException();
        if (!campaignEntityExists(campaign, sourceId) || !campaignEntityExists(campaign, targetId)) throw new UnknownRecord();
        String key = relationshipKey(sourceId, targetId, kind);
        if (campaign.relationships.containsKey(key)) throw new DuplicateId();
        Relationship relationship = new Relationship(sourceId, targetId, kind, score);
        campaign.relationships.put(key, relationship);
        saveStorage();
        return relationshipJson(relationship);
    }

    private static synchronized String updateRelationship(String campaignId, String sourceId, String targetId, String kind,
                                                          User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Relationship relationship = campaign.relationships.get(relationshipKey(sourceId, targetId, kind));
        if (relationship == null) throw new UnknownRecord();
        long score = integer(b, "score");
        if (score < -100 || score > 100) throw new IllegalArgumentException();
        relationship.score = score;
        saveStorage();
        return relationshipJson(relationship);
    }

    private static synchronized String relationships(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        StringBuilder edges = new StringBuilder("[");
        for (Relationship relationship : campaign.relationships.values()) {
            if (edges.length() > 1) edges.append(',');
            edges.append(relationshipJson(relationship));
        }
        return "{\"edges\":" + edges.append("]}");
    }

    private static synchronized String createClue(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        String clueId = requiredText(b, "clue_id");
        String text = requiredText(b, "text");
        String audience = requiredText(b, "audience");
        if (!audience.equals("character") && !audience.equals("party") && !audience.equals("hidden")) throw new IllegalArgumentException();
        boolean hasCharacterId = b.containsKey("character_id");
        String characterId = null;
        if (audience.equals("character")) {
            if (!hasCharacterId) throw new IllegalArgumentException();
            characterId = requiredText(b, "character_id");
            if (!playCharacterExists(campaign, characterId)) throw new IllegalArgumentException();
        } else if (hasCharacterId) {
            throw new IllegalArgumentException();
        }
        if (campaign.clues.containsKey(clueId)) throw new DuplicateId();
        Clue clue = new Clue(clueId, text, audience, characterId);
        campaign.clues.put(clueId, clue);
        saveStorage();
        return clueJson(clue);
    }

    private static synchronized String clues(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!dm && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        String ownCharacterId = dm ? null : campaign.members.get(actor.username).characterId;
        StringBuilder out = new StringBuilder("{\"clues\":[");
        boolean first = true;
        for (Clue clue : campaign.clues.values()) {
            if (!dm && !clue.audience.equals("party") && !(clue.audience.equals("character") && clue.characterId.equals(ownCharacterId))) continue;
            if (!first) out.append(',');
            first = false;
            out.append(clueJson(clue));
        }
        return out.append("]}").toString();
    }

    private static String clueJson(Clue clue) {
        return "{\"clue_id\":\"" + escape(clue.clueId) + "\",\"text\":\"" + escape(clue.text)
            + "\",\"audience\":\"" + clue.audience + "\""
            + (clue.characterId == null ? "}" : ",\"character_id\":\"" + escape(clue.characterId) + "\"}");
    }

    private static synchronized String createPlayQuest(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String questId = requiredText(b, "quest_id");
        String title = requiredText(b, "title");
        List<String> dependsOn = strings(array(b, "depends_on"));
        if (campaign.quests.containsKey(questId)) throw new DuplicateId();
        for (int i = 0; i < dependsOn.size(); i++) {
            String dependency = dependsOn.get(i);
            if (dependency.equals(questId) || !campaign.quests.containsKey(dependency) || dependsOn.indexOf(dependency) != i) {
                throw new IllegalArgumentException();
            }
        }
        PlayQuest quest = new PlayQuest(questId, title, dependsOn);
        campaign.quests.put(questId, quest);
        saveStorage();
        return playQuestJson(quest);
    }

    private static synchronized String changePlayQuestState(String campaignId, String questId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        PlayQuest quest = campaign.quests.get(questId);
        if (quest == null) throw new UnknownRecord();
        String state = requiredText(b, "state");
        if (!state.equals("active") && !state.equals("completed")) throw new IllegalArgumentException();
        if (quest.state.equals("locked") && state.equals("active")) {
            for (String dependency : quest.dependsOn) if (!campaign.quests.get(dependency).state.equals("completed")) throw new QuestTransitionConflict();
        } else if (!(quest.state.equals("active") && state.equals("completed"))) {
            throw new QuestTransitionConflict();
        }
        quest.state = state;
        saveStorage();
        return playQuestJson(quest);
    }

    private static synchronized String configurePlayQuestRewards(String campaignId, String questId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        PlayQuest quest = campaign.quests.get(questId);
        if (quest == null) throw new UnknownRecord();
        if (quest.state.equals("completed")) throw new QuestRewardConflict();
        long xp = integer(b, "xp");
        if (xp < 0) throw new IllegalArgumentException();
        Map<String, Object> requestedItems = asObject(b.get("items"));
        Map<String, Long> items = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : requestedItems.entrySet()) {
            if (!ITEMS.containsKey(entry.getKey()) || !(entry.getValue() instanceof Long)) throw new IllegalArgumentException();
            long quantity = (Long) entry.getValue();
            if (quantity <= 0) throw new IllegalArgumentException();
            items.put(entry.getKey(), quantity);
        }
        quest.reward = new QuestReward(xp, items);
        saveStorage();
        return playQuestJson(quest);
    }

    private static synchronized String awardPlayQuestRewards(String campaignId, String questId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        PlayQuest quest = campaign.quests.get(questId);
        if (quest == null) throw new UnknownRecord();
        if (!quest.state.equals("completed") || quest.reward == null || quest.reward.awarded) throw new QuestRewardConflict();
        quest.reward.awarded = true;
        for (PartyMember member : campaign.members.values()) {
            QuestRewardGrant grant = new QuestRewardGrant(questId, quest.reward.xp, quest.reward.items);
            member.questRewardGrants.put(questId, grant);
            for (Map.Entry<String, Long> item : quest.reward.items.entrySet()) {
                member.inventory.put(item.getKey(), Math.addExact(member.inventory.getOrDefault(item.getKey(), 0L), item.getValue()));
            }
        }
        saveStorage();
        return questRewardAwardJson(questId, quest.reward);
    }

    private static synchronized String playQuests(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        StringBuilder out = new StringBuilder("{\"quests\":[");
        boolean first = true;
        for (PlayQuest quest : campaign.quests.values()) {
            if (!first) out.append(',');
            first = false;
            out.append(playQuestJson(quest));
        }
        return out.append("]}").toString();
    }

    private static synchronized String scheduleWorldEvent(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String eventId = requiredText(b, "event_id");
        long turnNumber = integer(b, "turn_number");
        String title = requiredText(b, "title");
        String text = requiredText(b, "text");
        if (turnNumber < campaign.turnNumber) throw new IllegalArgumentException();
        if (campaign.worldEvents.containsKey(eventId)) throw new WorldEventConflict();
        WorldEvent event = new WorldEvent(eventId, turnNumber, title, text);
        campaign.worldEvents.put(eventId, event);
        saveStorage();
        return worldEventJson(event);
    }

    private static synchronized String resolveWorldEvent(String campaignId, String eventId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        WorldEvent event = campaign.worldEvents.get(eventId);
        if (event == null) throw new UnknownRecord();
        String text = requiredText(b, "text");
        if (event.resolution != null || campaign.turnNumber != event.turnNumber) throw new WorldEventConflict();
        event.resolution = new WorldEventResolution(campaign.turnNumber, text);
        saveStorage();
        return worldEventJson(event);
    }

    private static synchronized String worldEvents(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        List<WorldEvent> ordered = new ArrayList<>(campaign.worldEvents.values());
        ordered.sort(Comparator.comparingLong(event -> event.turnNumber));
        StringBuilder out = new StringBuilder("{\"events\":[");
        for (WorldEvent event : ordered) {
            if (out.charAt(out.length() - 1) != '[') out.append(',');
            out.append(worldEventJson(event));
        }
        return out.append("]}").toString();
    }

    private static String worldEventJson(WorldEvent event) {
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"turn_number\":" + event.turnNumber
            + ",\"title\":\"" + escape(event.title) + "\",\"text\":\"" + escape(event.text)
            + "\",\"status\":\"" + (event.resolution == null ? "scheduled" : "resolved") + "\""
            + (event.resolution == null ? "}" : ",\"resolution\":{\"turn_number\":" + event.resolution.turnNumber
                + ",\"text\":\"" + escape(event.resolution.text) + "\"}}");
    }

    private static synchronized String initializeCalendar(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        if (campaign.calendar != null) throw new CalendarConflict();
        long day = integer(b, "day");
        String season = string(b, "season");
        if (day < 1 || !season.equals("spring") && !season.equals("summer")
            && !season.equals("autumn") && !season.equals("winter")) throw new IllegalArgumentException();
        campaign.calendar = new Calendar(day, season);
        saveStorage();
        return calendarJson(campaign.calendar);
    }

    private static synchronized String calendar(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        if (campaign.calendar == null) throw new UnknownRecord();
        return calendarJson(campaign.calendar);
    }

    private static synchronized String advanceCalendar(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        if (campaign.calendar == null) throw new UnknownRecord();
        long days = integer(b, "days");
        if (days < 1 || days > 30) throw new IllegalArgumentException();
        campaign.calendar.day = Math.addExact(campaign.calendar.day, days);
        saveStorage();
        return calendarJson(campaign.calendar);
    }

    private static String calendarJson(Calendar calendar) {
        return "{\"day\":" + calendar.day + ",\"season\":\"" + calendar.season
            + "\",\"weather\":\"" + weather(calendar.day, calendar.season) + "\"}";
    }

    private static String weather(long day, String season) {
        long offset = switch (season) {
            case "spring" -> 0;
            case "summer" -> 1;
            case "autumn" -> 2;
            case "winter" -> 3;
            default -> throw new IllegalArgumentException();
        };
        return switch ((int) Math.floorMod(day + offset, 4)) {
            case 0 -> "clear";
            case 1 -> "rain";
            case 2 -> "wind";
            default -> "snow";
        };
    }

    private static String playQuestJson(PlayQuest quest) {
        return "{\"quest_id\":\"" + escape(quest.questId) + "\",\"title\":\"" + escape(quest.title)
            + "\",\"depends_on\":" + jsonStrings(quest.dependsOn) + ",\"state\":\"" + quest.state + "\""
            + (quest.reward == null ? "}" : ",\"rewards\":" + questRewardJson(quest.reward) + "}");
    }

    private static String questRewardJson(QuestReward reward) {
        return "{\"xp\":" + reward.xp + ",\"items\":" + jsonQuantities(reward.items) + "}";
    }

    private static String questRewardAwardJson(String questId, QuestReward reward) {
        return "{\"quest_id\":\"" + escape(questId) + "\",\"awarded\":true,\"xp\":" + reward.xp
            + ",\"items\":" + jsonQuantities(reward.items) + "}";
    }

    private static synchronized String characterQuestRewards(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        long xp = 0;
        Map<String, Long> items = new LinkedHashMap<>();
        for (QuestRewardGrant grant : member.questRewardGrants.values()) {
            xp = Math.addExact(xp, grant.xp);
            for (Map.Entry<String, Long> item : grant.items.entrySet()) items.put(item.getKey(), Math.addExact(items.getOrDefault(item.getKey(), 0L), item.getValue()));
        }
        return "{\"character_id\":\"" + escape(characterId) + "\",\"xp\":" + xp + ",\"items\":" + jsonQuantities(items) + "}";
    }

    private static String jsonQuantities(Map<String, Long> quantities) {
        StringBuilder out = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Long> entry : quantities.entrySet()) {
            if (!first) out.append(',');
            first = false;
            out.append("\"").append(escape(entry.getKey())).append("\":").append(entry.getValue());
        }
        return out.append('}').toString();
    }

    private static boolean campaignEntityExists(PlayCampaign campaign, String id) {
        if (campaign.npcs.containsKey(id)) return true;
        for (PartyMember member : campaign.members.values()) if (member.characterId.equals(id)) return true;
        return false;
    }

    private static String relationshipKey(String sourceId, String targetId, String kind) {
        return sourceId + '\u001f' + targetId + '\u001f' + kind;
    }

    private static synchronized String createPlayFaction(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String factionId = requiredText(b, "faction_id");
        String name = requiredText(b, "name");
        if (campaign.playFactions.containsKey(factionId)) throw new DuplicateId();
        PlayFaction faction = new PlayFaction(factionId, name);
        campaign.playFactions.put(factionId, faction);
        saveStorage();
        return playFactionJson(faction);
    }

    private static synchronized String changeFactionReputation(String campaignId, String factionId, User actor,
                                                                Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        if (!campaign.playFactions.containsKey(factionId)) throw new UnknownRecord();
        String characterId = requiredText(b, "character_id");
        PartyMember member;
        try { member = memberByCharacterId(campaign, characterId); }
        catch (UnknownRecord e) { throw new IllegalArgumentException(); }
        long delta = integer(b, "delta");
        if (delta == 0 || delta < -25 || delta > 25) throw new IllegalArgumentException();
        String reason = requiredText(b, "reason");
        long reputation = Math.max(-100, Math.min(100, factionReputationTotal(campaign, factionId, member.characterId) + delta));
        ReputationRecord record = new ReputationRecord(factionId, member.characterId, reputation, delta, reason);
        campaign.reputationHistory.add(record);
        saveStorage();
        return reputationJson(record);
    }

    private static synchronized String factionReputation(String campaignId, String factionId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean dm = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        PartyMember member = campaign.members.get(actor.username);
        if (!dm && (actor.role.equals("player") ? member == null : true)) throw new Forbidden();
        if (!campaign.playFactions.containsKey(factionId)) throw new UnknownRecord();
        StringBuilder entries = new StringBuilder("[");
        boolean first = true;
        for (ReputationRecord record : campaign.reputationHistory) {
            if (!record.factionId.equals(factionId) || (!dm && !record.characterId.equals(member.characterId))) continue;
            if (!first) entries.append(',');
            first = false;
            entries.append(reputationJson(record));
        }
        return "{\"faction_id\":\"" + escape(factionId) + "\",\"entries\":" + entries.append("]}");
    }

    private static long factionReputationTotal(PlayCampaign campaign, String factionId, String characterId) {
        for (int i = campaign.reputationHistory.size() - 1; i >= 0; i--) {
            ReputationRecord record = campaign.reputationHistory.get(i);
            if (record.factionId.equals(factionId) && record.characterId.equals(characterId)) return record.reputation;
        }
        return 0;
    }

    private static PlayNpc playNpcById(PlayCampaign campaign, String npcId) {
        PlayNpc npc = campaign.npcs.get(npcId);
        if (npc == null) throw new UnknownRecord();
        return npc;
    }

    private static LootRecord lootById(PlayCampaign campaign, String lootId) {
        LootRecord loot = campaign.loot.get(lootId);
        if (loot == null) throw new UnknownRecord();
        return loot;
    }

    private static long voteCount(LootRecord loot, String recipientId) {
        long count = 0;
        for (String recipient : loot.votes.values()) if (recipient.equals(recipientId)) count++;
        return count;
    }

    private static String lootJson(LootRecord loot) {
        return "{\"loot_id\":\"" + escape(loot.lootId) + "\",\"item_id\":\"" + escape(loot.itemId)
            + "\",\"quantity\":" + loot.quantity + ",\"status\":\"" + loot.status
            + "\",\"recipient_character_id\":" + (loot.recipientCharacterId == null ? "null" : "\"" + escape(loot.recipientCharacterId) + "\"")
            + ",\"votes\":" + lootVotesJson(loot) + "}";
    }

    private static String playNpcJson(PlayNpc npc, boolean includeAgenda) {
        return "{\"npc_id\":\"" + escape(npc.npcId) + "\",\"name\":\"" + escape(npc.name) + "\""
            + (includeAgenda ? ",\"agenda\":\"" + escape(npc.agenda) + "\"" : "")
            + ",\"public_status\":\"" + escape(npc.publicStatus) + "\"}";
    }

    private static String dialogueJson(DialogueEntry entry) {
        return "{\"dialogue_id\":\"" + escape(entry.dialogueId) + "\",\"speaker\":\""
            + escape(entry.speaker) + "\",\"text\":\"" + escape(entry.text) + "\",\"visibility\":\""
            + entry.visibility + "\"}";
    }

    private static String relationshipJson(Relationship relationship) {
        return "{\"source_id\":\"" + escape(relationship.sourceId) + "\",\"target_id\":\""
            + escape(relationship.targetId) + "\",\"kind\":\"" + escape(relationship.kind)
            + "\",\"score\":" + relationship.score + "}";
    }

    private static String playFactionJson(PlayFaction faction) {
        return "{\"faction_id\":\"" + escape(faction.factionId) + "\",\"name\":\"" + escape(faction.name) + "\"}";
    }

    private static String reputationJson(ReputationRecord record) {
        return "{\"faction_id\":\"" + escape(record.factionId) + "\",\"character_id\":\""
            + escape(record.characterId) + "\",\"reputation\":" + record.reputation + ",\"delta\":"
            + record.delta + ",\"reason\":\"" + escape(record.reason) + "\"}";
    }

    private static String lootVotesJson(LootRecord loot) {
        Map<String, Long> totals = new LinkedHashMap<>();
        for (String recipientId : loot.votes.values()) {
            totals.put(recipientId, totals.getOrDefault(recipientId, 0L) + 1);
        }
        StringBuilder out = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Long> vote : totals.entrySet()) {
            if (!first) out.append(',');
            out.append("\"").append(escape(vote.getKey())).append("\":")
                .append(vote.getValue());
            first = false;
        }
        return out.append('}').toString();
    }

    private static String lootAssignmentJson(LootRecord loot) {
        return "{\"loot_id\":\"" + escape(loot.lootId) + "\",\"recipient_character_id\":\"" + escape(loot.recipientCharacterId)
            + "\",\"item_id\":\"" + escape(loot.itemId) + "\",\"quantity\":" + loot.quantity
            + ",\"votes\":" + loot.assignedVotes + ",\"status\":\"assigned\"}";
    }

    private static boolean isInventoryItem(String itemId) {
        return itemId.equals("healing-potion") || itemId.equals("torch") || itemId.equals("leather-armor")
            || itemId.equals("ring-of-protection") || itemId.equals("amulet-of-health");
    }

    private static synchronized String characterEquipment(String campaignId, String characterId, String slot, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        if (!isEquipmentSlot(slot)) throw new IllegalArgumentException();
        PartyMember member = memberByCharacterId(campaign, characterId);
        Equipment equipment = member.equipment.get(slot);
        return equipmentJson(member.characterId, slot, equipment == null ? "" : equipment.itemId, equipment != null && equipment.attuned);
    }

    private static synchronized String equipCharacterItem(String campaignId, String characterId, String slot, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        if (!isEquipmentSlot(slot)) throw new IllegalArgumentException();
        String itemId = string(b, "item_id");
        if (!isEquipmentItem(itemId) || !slot.equals(equipmentSlot(itemId)) || member.inventory.getOrDefault(itemId, 0L) <= 0) throw new IllegalArgumentException();
        member.equipment.put(slot, new Equipment(itemId, false));
        saveStorage();
        return equipmentJson(member.characterId, slot, itemId, false);
    }

    private static synchronized String attuneCharacterEquipment(String campaignId, String characterId, String slot, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        if (!isEquipmentSlot(slot)) throw new IllegalArgumentException();
        Equipment equipment = member.equipment.get(slot);
        if (!slot.equals("accessory") || equipment == null || !isAttunable(equipment.itemId)) throw new IllegalArgumentException();
        for (Equipment equipped : member.equipment.values()) if (equipped.attuned) throw new AttunementConflict();
        equipment.attuned = true;
        saveStorage();
        return equipmentJson(member.characterId, slot, equipment.itemId, true)
            .replace("}", ",\"attunement_count\":1,\"max_attunements\":1}");
    }

    private static boolean isEquipmentItem(String itemId) {
        return itemId.equals("leather-armor") || itemId.equals("ring-of-protection") || itemId.equals("amulet-of-health");
    }

    private static boolean isEquipmentSlot(String slot) {
        return slot.equals("armor") || slot.equals("accessory");
    }

    private static String equipmentSlot(String itemId) {
        return switch (itemId) {
            case "leather-armor" -> "armor";
            case "ring-of-protection", "amulet-of-health" -> "accessory";
            default -> throw new IllegalArgumentException();
        };
    }

    private static boolean isAttunable(String itemId) {
        return itemId.equals("ring-of-protection") || itemId.equals("amulet-of-health");
    }

    private static String equipmentJson(String characterId, String slot, String itemId, boolean attuned) {
        return "{\"character_id\":\"" + escape(characterId) + "\",\"slot\":\"" + escape(slot)
            + "\",\"item_id\":\"" + escape(itemId) + "\",\"attuned\":" + attuned + "}";
    }

    private static String characterInventoryJson(PartyMember member) {
        StringBuilder out = new StringBuilder("{\"character_id\":\"").append(escape(member.characterId)).append("\",\"items\":[");
        List<String> itemIds = new ArrayList<>(member.inventory.keySet());
        itemIds.sort(String::compareTo);
        for (int i = 0; i < itemIds.size(); i++) {
            if (i > 0) out.append(',');
            String itemId = itemIds.get(i);
            out.append("{\"item_id\":\"").append(escape(itemId)).append("\",\"quantity\":").append(member.inventory.get(itemId)).append('}');
        }
        return out.append("]}").toString();
    }

    private static String characterInventoryItemJson(String characterId, String itemId, long quantity, long total) {
        return "{\"character_id\":\"" + escape(characterId) + "\",\"item_id\":\"" + escape(itemId)
            + "\",\"quantity\":" + quantity + ",\"total_quantity\":" + total + "}";
    }

    private static synchronized String addCharacterSpell(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String spellId = string(b, "spell_id");
        String name = string(b, "name");
        long level = integer(b, "level");
        Spell knownSpell = WIZARD_SPELLS.get(spellId);
        if (!member.characterClass.equals("wizard") || knownSpell == null
            || !knownSpell.name.equals(name) || knownSpell.level != level) throw new IllegalArgumentException();
        if (member.spells.containsKey(spellId)) throw new SpellConflict();
        member.spells.put(spellId, knownSpell);
        saveStorage();
        return spellJson(knownSpell);
    }

    private static synchronized String characterCasts(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        StringBuilder out = new StringBuilder("{\"casts\":[");
        for (int i = 0; i < member.casts.size(); i++) {
            if (i > 0) out.append(',');
            out.append(castJson(member.casts.get(i), member.characterId));
        }
        return out.append("]}").toString();
    }

    private static synchronized String castSpell(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String spellId = requiredText(b, "spell_id");
        String target = requiredText(b, "target");
        Spell spell = member.spells.get(spellId);
        if (!isSpellcastingClass(member.characterClass) || spell == null || !member.preparedSpellIds.contains(spellId)) {
            throw new IllegalArgumentException();
        }
        long slotsRemaining = spellSlotsRemaining(member, spell.level);
        if (slotsRemaining < 1) throw new SpellSlotConflict();
        CastEvent cast = new CastEvent(spellId, target, spell.level, slotsRemaining - 1, member.casts.size() + 1L);
        member.casts.add(cast);
        saveStorage();
        return castJson(cast, member.characterId);
    }

    private static long spellSlotsRemaining(PartyMember member, long spellLevel) {
        if (spellLevel == 0) return Long.MAX_VALUE;
        long spent = 0;
        for (CastEvent cast : member.casts) if (cast.slotLevel == spellLevel) spent++;
        return Math.max(0, spellSlotCount(member.characterClass, member.level, spellLevel) - spent);
    }

    // The play model starts every first-level wizard with the one slot specified
    // by its character-creation rules. Higher levels follow the ordinary wizard
    // slot progression, while unsupported spell levels have no available slots.
    private static long spellSlotCount(String characterClass, long characterLevel, long spellLevel) {
        if (!characterClass.equals("wizard") || spellLevel < 1 || characterLevel < 1) return 0;
        long[][] wizardSlots = {
            {}, {1}, {2}, {3, 2}, {4, 3}, {4, 3, 2}, {4, 3, 3}, {4, 3, 3, 1}, {4, 3, 3, 2},
            {4, 3, 3, 3, 1}, {4, 3, 3, 3, 2}, {4, 3, 3, 3, 2, 1}, {4, 3, 3, 3, 2, 1},
            {4, 3, 3, 3, 2, 1, 1}, {4, 3, 3, 3, 2, 1, 1}, {4, 3, 3, 3, 2, 1, 1, 1},
            {4, 3, 3, 3, 2, 1, 1, 1}, {4, 3, 3, 3, 2, 1, 1, 1, 1}, {4, 3, 3, 3, 3, 1, 1, 1, 1},
            {4, 3, 3, 3, 3, 2, 1, 1, 1}, {4, 3, 3, 3, 3, 2, 2, 1, 1}, {4, 3, 3, 3, 3, 2, 2, 1, 1}
        };
        long[] slots = wizardSlots[(int) Math.min(characterLevel, 20)];
        return spellLevel <= slots.length ? slots[(int) spellLevel - 1] : 0;
    }

    private static String castJson(CastEvent cast, String characterId) {
        return "{\"character_id\":\"" + escape(characterId) + "\",\"spell_id\":\"" + escape(cast.spellId)
            + "\",\"target\":\"" + escape(cast.target) + "\",\"slot_level\":" + cast.slotLevel
            + ",\"slots_remaining\":" + cast.slotsRemaining + ",\"sequence\":" + cast.sequence + "}";
    }

    private static synchronized String characterPreparedSpells(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        return preparedSpellsJson(member);
    }

    private static synchronized String updateCharacterPreparedSpells(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        List<String> spellIds = strings(array(b, "spell_ids"));
        if (!isSpellcastingClass(member.characterClass) || spellIds.size() > maxPreparedSpells(member)) throw new IllegalArgumentException();
        Map<String, Boolean> seen = new LinkedHashMap<>();
        for (String spellId : spellIds) {
            if (!member.spells.containsKey(spellId) || seen.put(spellId, true) != null) throw new IllegalArgumentException();
        }
        member.preparedSpellIds.clear();
        member.preparedSpellIds.addAll(spellIds);
        saveStorage();
        return preparedSpellsJson(member);
    }

    private static boolean isSpellcastingClass(String characterClass) {
        return characterClass.equals("cleric") || characterClass.equals("wizard");
    }

    private static long maxPreparedSpells(PartyMember member) {
        return isSpellcastingClass(member.characterClass) ? member.level : 0;
    }

    private static String preparedSpellsJson(PartyMember member) {
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"prepared_spells\":"
            + jsonStrings(member.preparedSpellIds) + ",\"max_prepared\":" + maxPreparedSpells(member) + "}";
    }

    private static synchronized String characterConcentration(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        return concentrationJson(memberByCharacterId(campaign, characterId));
    }

    private static synchronized String updateCharacterConcentration(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String spellId = requiredText(b, "spell_id");
        String target = requiredText(b, "target");
        long durationTurns = integer(b, "duration_turns");
        if (!isSpellcastingClass(member.characterClass) || !member.spells.containsKey(spellId)
            || !member.preparedSpellIds.contains(spellId) || durationTurns < 1) throw new IllegalArgumentException();
        member.concentration = new Concentration(spellId, target, durationTurns);
        saveStorage();
        return concentrationJson(member);
    }

    private static synchronized String advanceCharacterConcentration(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (member.concentration != null) {
            member.concentration.remainingTurns--;
            if (member.concentration.remainingTurns == 0) member.concentration = null;
            saveStorage();
        }
        return concentrationJson(member);
    }

    private static synchronized String clearCharacterConcentration(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        member.concentration = null;
        saveStorage();
        return concentrationJson(member);
    }

    private static String concentrationJson(PartyMember member) {
        if (member.concentration == null) return "{\"character_id\":\"" + escape(member.characterId) + "\",\"concentration\":null}";
        Concentration concentration = member.concentration;
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"concentration\":{\"spell_id\":\""
            + escape(concentration.spellId) + "\",\"target\":\"" + escape(concentration.target)
            + "\",\"remaining_turns\":" + concentration.remainingTurns + "}}";
    }

    private static String spellJson(Spell spell) {
        return "{\"spell_id\":\"" + escape(spell.spellId) + "\",\"name\":\"" + escape(spell.name)
            + "\",\"level\":" + spell.level + "}";
    }

    private static synchronized String claimCharacter(String campaignId, String characterId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.members.containsKey(actor.username)) throw new Forbidden();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (member.owner == null) {
            member.owner = actor.username;
            saveStorage();
        } else if (!member.owner.equals(actor.username)) {
            throw new OwnershipConflict();
        }
        return characterOwnerJson(member);
    }

    private static synchronized String transferCharacter(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String newOwner = requiredText(b, "new_owner");
        if (!campaign.members.containsKey(newOwner)) throw new Forbidden();
        member.owner = newOwner;
        saveStorage();
        return characterOwnerJson(member);
    }

    private static synchronized String buildCharacter(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();

        String race = string(b, "race");
        String characterClass = string(b, "class");
        String background = string(b, "background");
        if (!(race.equals("dwarf") || race.equals("elf") || race.equals("halfling") || race.equals("human"))
            || !(characterClass.equals("cleric") || characterClass.equals("fighter") || characterClass.equals("rogue") || characterClass.equals("wizard"))
            || !(background.equals("acolyte") || background.equals("criminal") || background.equals("folk-hero")
                || background.equals("noble") || background.equals("sage") || background.equals("soldier"))) {
            throw new IllegalArgumentException();
        }
        Map<String, Object> abilities = asObject(b.get("abilities"));
        member.strength = abilityScore(abilities, "str");
        member.dexterity = abilityScore(abilities, "dex");
        long conModifier = modifier(abilityScore(abilities, "con"));
        member.constitution = abilityScore(abilities, "con");
        member.intelligence = abilityScore(abilities, "int");
        member.wisdom = abilityScore(abilities, "wis");
        member.charisma = abilityScore(abilities, "cha");
        long hitDie = switch (characterClass) {
            case "cleric", "rogue" -> 8;
            case "fighter" -> 10;
            case "wizard" -> 6;
            default -> throw new IllegalArgumentException();
        };
        long hpMax = Math.max(1, Math.addExact(hitDie, conModifier));
        member.characterClass = characterClass;
        member.conModifier = conModifier;
        member.level = 1;
        member.hpMax = hpMax;
        member.hpCurrent = Math.min(member.hpCurrent, hpMax);
        saveStorage();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"race\":\"" + race
            + "\",\"class\":\"" + characterClass + "\",\"background\":\"" + background
            + "\",\"level\":1,\"hp_max\":" + hpMax + ",\"proficiency_bonus\":2}";
    }

    private static synchronized String levelUpCharacter(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        long level = characterLevel(b, "level");
        if (level != member.level + 1) throw new IllegalArgumentException();
        long hitDie = hitDie(member.characterClass);
        // Fixed average hit-die gains make progression reproducible: d8 gains 5.
        long gain = Math.addExact((hitDie / 2) + 1, member.conModifier);
        member.level = level;
        member.hpMax = Math.max(1, Math.addExact(member.hpMax, gain));
        saveStorage();
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"level\":" + member.level
            + ",\"hp_max\":" + member.hpMax + ",\"hit_dice\":\"1d" + hitDie
            + "\",\"proficiency_bonus\":" + proficiencyBonus(member.level) + "}";
    }

    private static synchronized String skillCheck(String campaignId, String characterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        PartyMember member = memberByCharacterId(campaign, characterId);
        if (!actor.username.equals(member.owner)) throw new Forbidden();
        String skill = string(b, "skill");
        String ability = string(b, "ability");
        if (!isSkill(skill) || !isAbility(ability)) throw new IllegalArgumentException();
        long roll = integer(b, "roll");
        long abilityModifier = modifier(member.abilityScore(ability));
        long checkModifier = Math.addExact(abilityModifier, bool(b, "proficient") ? proficiencyBonus(member.level) : 0);
        long total = Math.addExact(roll, checkModifier);
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"skill\":\"" + escape(skill)
            + "\",\"ability\":\"" + escape(ability) + "\",\"modifier\":" + checkModifier + ",\"total\":" + total + "}";
    }

    private static boolean isSkill(String skill) {
        return switch (skill) {
            case "acrobatics", "animal-handling", "arcana", "athletics", "deception", "history", "insight",
                "intimidation", "investigation", "medicine", "nature", "perception", "performance", "persuasion",
                "religion", "sleight-of-hand", "stealth", "survival" -> true;
            default -> false;
        };
    }

    private static boolean isAbility(String ability) {
        return ability.equals("str") || ability.equals("dex") || ability.equals("con") || ability.equals("int")
            || ability.equals("wis") || ability.equals("cha");
    }

    private static long hitDie(String characterClass) {
        return switch (characterClass) {
            case "cleric", "rogue" -> 8;
            case "fighter" -> 10;
            case "wizard" -> 6;
            default -> throw new IllegalArgumentException();
        };
    }

    private static String characterOwnerJson(PartyMember member) {
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"owner\":\""
            + escape(member.owner) + "\"}";
    }

    private static PartyMember memberByCharacterId(PlayCampaign campaign, String characterId) {
        for (PartyMember member : campaign.members.values()) if (member.characterId.equals(characterId)) return member;
        throw new UnknownRecord();
    }

    private static void setMemberHitPoints(PartyMember member, long hp) {
        member.hpCurrent = hp;
        if (hp == 0 && member.status.equals("conscious")) member.status = "unconscious";
    }

    private static void restoreMember(PartyMember member, long hp) {
        member.hpCurrent = hp;
        if (hp > 0 && !member.status.equals("dead")) {
            member.status = "conscious";
            member.deathSaveSuccesses = 0;
            member.deathSaveFailures = 0;
        }
    }

    private static String deathSaveJson(PartyMember member) {
        return "{\"character_id\":\"" + escape(member.characterId) + "\",\"successes\":" + member.deathSaveSuccesses
            + ",\"failures\":" + member.deathSaveFailures + ",\"status\":\"" + member.status + "\"}";
    }

    private static synchronized String addCombatAction(String campaignId, String encounterId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        Encounter encounter = encounter(campaignId, encounterId);
        CombatTurnEntry active = activeCombatant(encounter);
        if (!actor.role.equals("player") || active.username == null || !actor.username.equals(active.username)) throw new TurnConflict();
        String type = requiredText(b, "type");
        if (!type.equals("attack") && !type.equals("help") && !type.equals("dodge") && !type.equals("ready")) throw new IllegalArgumentException();
        PlayEvent action = new PlayEvent(nextPlayEventSequence(campaign), "combat_action", actor.username,
            type, requiredText(b, "text"), requiredText(b, "target"));
        campaign.events.add(action);
        saveStorage();
        return combatActionJson(action);
    }

    private static Encounter encounter(String campaignId, String encounterId) {
        Encounter encounter = ENCOUNTERS.get(encounterId);
        if (encounter == null || !encounter.campaignId.equals(campaignId)) throw new UnknownRecord();
        return encounter;
    }

    private static List<CombatTurnEntry> encounterOrder(Encounter encounter) {
        List<CombatTurnEntry> naturalOrder = new ArrayList<>();
        for (EncounterMonster monster : encounter.monsters.values())
            naturalOrder.add(new CombatTurnEntry(null, monster.id, monster.name, "monster", monster.initiative));
        for (EncounterCombatant combatant : encounter.combatants.values())
            naturalOrder.add(new CombatTurnEntry(combatant.username, combatant.username, combatant.name, "player", combatant.initiative));
        naturalOrder.sort(Comparator.comparingLong(CombatTurnEntry::initiative).reversed()
            .thenComparing(CombatTurnEntry::name).thenComparing(CombatTurnEntry::kind).thenComparing(CombatTurnEntry::id));
        if (encounter.turnOrder == null) return naturalOrder;
        Map<String, CombatTurnEntry> byKey = new LinkedHashMap<>();
        for (CombatTurnEntry entry : naturalOrder) byKey.put(turnEntryKey(entry), entry);
        List<CombatTurnEntry> order = new ArrayList<>();
        for (String key : encounter.turnOrder) {
            CombatTurnEntry entry = byKey.remove(key);
            if (entry != null) order.add(entry);
        }
        // Combatants added after a delay retain deterministic initiative placement.
        order.addAll(byKey.values());
        return order;
    }

    private static String turnEntryKey(CombatTurnEntry entry) { return entry.kind + ":" + entry.id; }

    private static CombatTurnEntry activeCombatant(Encounter encounter) {
        List<CombatTurnEntry> order = encounterOrder(encounter);
        if (order.isEmpty()) throw new IllegalArgumentException();
        if (encounter.turnIndex >= order.size()) encounter.turnIndex = 0;
        return order.get((int) encounter.turnIndex);
    }

    private static String encounterTurnJson(Encounter encounter) {
        CombatTurnEntry active = activeCombatant(encounter);
        return "{\"round\":" + encounter.round + ",\"turn_index\":" + encounter.turnIndex + ",\"active\":{\"name\":\""
            + escape(active.name) + "\",\"kind\":\"" + active.kind + "\",\"initiative\":" + active.initiative + "}}";
    }

    private static String encounterStatusJson(Encounter encounter) {
        List<CombatTurnEntry> order = encounterOrder(encounter);
        CombatTurnEntry active = activeCombatant(encounter);
        StringBuilder out = new StringBuilder("{\"round\":").append(encounter.round)
            .append(",\"turn_index\":").append(encounter.turnIndex).append(",\"active\":")
            .append(encounterTurnEntryJson(active)).append(",\"order\":[");
        for (int i = 0; i < order.size(); i++) {
            if (i > 0) out.append(',');
            out.append(encounterTurnEntryJson(order.get(i)));
        }
        out.append("],\"conditions\":{");
        for (int i = 0; i < order.size(); i++) {
            if (i > 0) out.append(',');
            CombatTurnEntry combatant = order.get(i);
            out.append('"').append(escape(combatant.id)).append("\":")
                .append(conditionsArray(encounter.conditions.get(combatant.id)));
        }
        return out.append("}}").toString();
    }

    private static String encounterOrderJson(List<CombatTurnEntry> order) {
        StringBuilder out = new StringBuilder("{\"order\":[");
        for (int i = 0; i < order.size(); i++) {
            if (i > 0) out.append(',');
            out.append(encounterTurnEntryJson(order.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String encounterTurnEntryJson(CombatTurnEntry entry) {
        return "{\"name\":\"" + escape(entry.name) + "\",\"kind\":\"" + entry.kind
            + "\",\"initiative\":" + entry.initiative + "}";
    }

    private static void expireEncounterConditions(Encounter encounter, String target) {
        List<Condition> attached = encounter.conditions.get(target);
        for (int i = attached.size() - 1; i >= 0; i--) {
            Condition condition = attached.get(i);
            condition.remainingRounds--;
            if (condition.remainingRounds <= 0) attached.remove(i);
        }
    }

    private static String nextPlayer(PlayCampaign campaign) {
        if (campaign.nextResolutionStartsParty) {
            campaign.nextResolutionStartsParty = false;
            return campaign.members.values().iterator().next().username;
        }
        String previousActor = null;
        for (int i = campaign.events.size() - 1; i >= 0; i--) {
            PlayEvent event = campaign.events.get(i);
            if (event.kind.equals("action") || event.kind.equals("travel") || event.kind.equals("rest")) {
                previousActor = event.actor;
                break;
            }
        }
        boolean chooseNext = previousActor == null;
        for (PartyMember member : campaign.members.values()) {
            if (chooseNext) return member.username;
            if (member.username.equals(previousActor)) chooseNext = true;
        }
        return campaign.members.values().iterator().next().username;
    }

    /* Locations occupy ordered campaign slots too, even though they are not events. */
    private static long nextPlayEventSequence(PlayCampaign campaign) {
        long lastEventSequence = campaign.events.isEmpty() ? 0 : campaign.events.get(campaign.events.size() - 1).sequence;
        return Math.max(lastEventSequence, campaign.events.size() + campaign.locations.size()) + 1;
    }

    private static synchronized String playCampaignTurn(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!campaign.owner.equals(actor.username) && !campaign.members.containsKey(actor.username)) throw new Forbidden();
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"current_actor\":"
            + jsonNullableString(campaign.currentActor) + ",\"phase\":\""
            + (campaign.nextResolutionStartsParty ? "exploration" : "player") + "\",\"turn_number\":"
            + campaign.turnNumber + ",\"queue\":" + playCampaignQueue(campaign) + ",\"overdue\":false,\"logical_deadline\":"
            + (campaign.turnNumber + 1) + "}";
    }

    private static synchronized String playerTurnContext(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player")) throw new Forbidden();
        PartyMember member = campaign.members.get(actor.username);
        if (member == null) throw new Forbidden();
        return "{\"is_my_turn\":" + actor.username.equals(campaign.currentActor)
            + ",\"current_actor\":" + jsonNullableString(campaign.currentActor)
            + ",\"character\":{\"id\":\"" + escape(member.characterId) + "\",\"name\":\""
            + escape(member.name) + "\"},\"recent_events\":" + recentNarrations(campaign) + "}";
    }

    private static synchronized String gmTurnStatus(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        StringBuilder party = new StringBuilder("[");
        for (PartyMember member : campaign.members.values()) {
            if (party.length() > 1) party.append(',');
            party.append(partyMemberJson(member));
        }
        return "{\"needs_attention\":" + campaign.owner.equals(campaign.currentActor)
            + ",\"current_actor\":" + jsonNullableString(campaign.currentActor)
            + ",\"party\":" + party.append(']')
            + ",\"recent_events\":" + recentNarrations(campaign) + "}";
    }

    private static synchronized String updateCampaignDocument(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        campaign.story = string(b, "story");
        campaign.dmNotes = string(b, "dm_notes");
        saveStorage();
        return campaignDocumentJson(campaign, true);
    }

    private static synchronized String campaignDocument(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean owner = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!owner && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        return campaignDocumentJson(campaign, owner);
    }

    private static synchronized String createCampaignBackup(String campaignId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        CampaignBackup backup = new CampaignBackup("backup-" + (campaign.backups.size() + 1L), campaign.story, campaign.status);
        campaign.backups.add(backup);
        saveStorage();
        return campaignBackupJson(backup);
    }

    private static synchronized String listCampaignBackups(String campaignId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"backups\":[");
        for (int i = 0; i < campaign.backups.size(); i++) {
            if (i > 0) out.append(',');
            out.append(campaignBackupJson(campaign.backups.get(i)));
        }
        return out.append("]}").toString();
    }

    private static synchronized String restoreCampaignBackup(String campaignId, String backupId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        for (CampaignBackup backup : campaign.backups) {
            if (backup.backupId.equals(backupId)) {
                campaign.story = backup.story;
                campaign.status = backup.status;
                saveStorage();
                return campaignBackupJson(backup);
            }
        }
        throw new UnknownRecord();
    }

    private static synchronized String createCampaignExport(String campaignId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        CampaignExport snapshot = new CampaignExport(campaign.exports.size() + 1L, campaign.story, campaign.status);
        campaign.exports.add(snapshot);
        saveStorage();
        return campaignExportJson(snapshot);
    }

    private static synchronized String listCampaignExports(String campaignId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"exports\":[");
        for (int i = 0; i < campaign.exports.size(); i++) {
            if (i > 0) out.append(',');
            out.append(campaignExportJson(campaign.exports.get(i)));
        }
        return out.append("]}").toString();
    }

    private static synchronized String readCampaignExport(String campaignId, String requestedVersion, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        long version = number(requestedVersion);
        if (version <= 0 || version > campaign.exports.size()) throw new UnknownRecord();
        return campaignExportJson(campaign.exports.get((int) version - 1));
    }

    private static String campaignExportJson(CampaignExport snapshot) {
        return "{\"version\":" + snapshot.version + ",\"story\":\"" + escape(snapshot.story)
            + "\",\"status\":\"" + escape(snapshot.status) + "\"}";
    }

    private static String campaignBackupJson(CampaignBackup backup) {
        return "{\"backup_id\":\"" + escape(backup.backupId) + "\",\"story\":\"" + escape(backup.story)
            + "\",\"status\":\"" + escape(backup.status) + "\"}";
    }

    private static synchronized String importCampaignSnapshot(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        if (body.size() != 3 || !body.keySet().containsAll(List.of("version", "story", "status"))) throw new IllegalArgumentException();
        long version = integer(body, "version");
        String story = requiredText(body, "story");
        String status = string(body, "status");
        if (version != 1 || !(status.equals("lobby") || status.equals("started"))) throw new IllegalArgumentException();
        CampaignImport snapshot = new CampaignImport(version, story, status);
        campaign.story = snapshot.story;
        campaign.status = snapshot.status;
        campaign.importedSnapshot = snapshot;
        saveStorage();
        return campaignImportJson(snapshot);
    }

    private static synchronized String importedState(String campaignId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        if (campaign.importedSnapshot == null) throw new UnknownRecord();
        return campaignImportJson(campaign.importedSnapshot);
    }

    private static String campaignImportJson(CampaignImport snapshot) {
        return "{\"version\":" + snapshot.version + ",\"story\":\"" + escape(snapshot.story)
            + "\",\"status\":\"" + escape(snapshot.status) + "\"}";
    }

    private static synchronized MigrationResult migrateCampaignSnapshot(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 2 || !body.containsKey("schema_version") || !body.containsKey("story")) throw new IllegalArgumentException();
        if (integer(body, "schema_version") != 1) throw new IllegalArgumentException();
        String story = requiredText(body, "story");
        if (campaign.migratedState != null && campaign.migratedState.story.equals(story)) {
            return new MigrationResult(campaign.migratedState, false);
        }
        campaign.migratedState = new MigratedState(story, campaign.name);
        saveStorage();
        return new MigrationResult(campaign.migratedState, true);
    }

    private static synchronized String migrationState(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (campaign.migratedState == null) throw new UnknownRecord();
        return migrationJson(campaign.migratedState);
    }

    private static String migrationJson(MigratedState state) {
        return "{\"schema_version\":2,\"story\":\"" + escape(state.story)
            + "\",\"campaign_name\":\"" + escape(state.campaignName) + "\"}";
    }

    private static synchronized String createScene(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        if (campaign.scenes.containsKey(id)) throw new DuplicateId();
        Scene scene = new Scene(id, name);
        campaign.scenes.put(id, scene);
        saveStorage();
        return sceneJson(scene);
    }

    private static synchronized String enterScene(String campaignId, String sceneId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Scene scene = campaign.scenes.get(sceneId);
        if (scene == null) throw new UnknownRecord();
        if (scene.status.equals("closed")) throw new SceneConflict();
        campaign.currentSceneId = scene.id;
        saveStorage();
        return "{\"current_scene_id\":\"" + escape(scene.id) + "\",\"name\":\"" + escape(scene.name) + "\"}";
    }

    private static synchronized String closeScene(String campaignId, String sceneId, User actor) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Scene scene = campaign.scenes.get(sceneId);
        if (scene == null) throw new UnknownRecord();
        scene.status = "closed";
        if (scene.id.equals(campaign.currentSceneId)) campaign.currentSceneId = null;
        saveStorage();
        return "{\"id\":\"" + escape(scene.id) + "\",\"status\":\"closed\"}";
    }

    private static synchronized String currentScene(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean owner = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!owner && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        Scene scene = campaign.currentSceneId == null ? null : campaign.scenes.get(campaign.currentSceneId);
        if (scene == null || scene.status.equals("closed")) throw new UnknownRecord();
        return sceneJson(scene);
    }

    private static synchronized String createLocation(String campaignId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        if (campaign.locations.containsKey(id)) throw new DuplicateId();
        Location location = new Location(id, name);
        campaign.locations.put(id, location);
        saveStorage();
        return locationJson(location);
    }

    private static synchronized String createLocationConnection(String campaignId, String fromId, User actor, Map<String, Object> b) {
        PlayCampaign campaign = ownedPlayCampaign(campaignId, actor);
        Location from = campaign.locations.get(fromId);
        String toId = requiredText(b, "to_id");
        long travelTurns = positive(integer(b, "travel_turns"));
        if (from == null || !campaign.locations.containsKey(toId) || from.connections.containsKey(toId)) throw new IllegalArgumentException();
        from.connections.put(toId, travelTurns);
        saveStorage();
        return "{\"from_id\":\"" + escape(fromId) + "\",\"to_id\":\"" + escape(toId)
            + "\",\"travel_turns\":" + travelTurns + "}";
    }

    private static synchronized String travelLocations(String campaignId, String locationId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean owner = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!owner && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        Location location = campaign.locations.get(locationId);
        if (location == null) throw new UnknownRecord();
        StringBuilder destinations = new StringBuilder("[");
        for (Map.Entry<String, Long> connection : location.connections.entrySet()) {
            if (destinations.length() > 1) destinations.append(',');
            Location destination = campaign.locations.get(connection.getKey());
            destinations.append("{\"id\":\"").append(escape(destination.id)).append("\",\"name\":\"")
                .append(escape(destination.name)).append("\",\"travel_turns\":").append(connection.getValue()).append('}');
        }
        return "{\"destinations\":" + destinations.append(']') + "}";
    }

    private static synchronized String appendProjectionEvent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("player") || !campaign.members.containsKey(actor.username)) throw new Forbidden();
        String eventId = requiredText(body, "event_id");
        String kind = string(body, "kind");
        String value = null;
        if (kind.equals("set-story")) {
            value = requiredText(body, "value");
        } else if (kind.equals("increment-danger")) {
            if (body.containsKey("value")) throw new IllegalArgumentException();
        } else {
            throw new IllegalArgumentException();
        }
        for (ProjectionEvent event : campaign.projectionEvents) if (event.eventId.equals(eventId)) throw new ProjectionEventConflict();
        long sequence = 1;
        for (ProjectionEvent existing : campaign.projectionEvents) sequence = Math.max(sequence, existing.sequence + 1);
        ProjectionEvent event = new ProjectionEvent(sequence, eventId, kind, value);
        campaign.projectionEvents.add(event);
        saveStorage();
        return projectionEventJson(event);
    }

    private static synchronized String projection(String campaignId, User actor) {
        return projectionJson(readablePlayCampaign(campaignId, actor));
    }

    private static synchronized String rebuildProjection(String campaignId, User actor) {
        return projectionJson(readablePlayCampaign(campaignId, actor));
    }

    private static synchronized String appendReplayEvent(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (body.size() != 3 || !body.keySet().containsAll(List.of("event_id", "kind", "text"))) throw new IllegalArgumentException();
        String eventId = requiredText(body, "event_id");
        String kind = string(body, "kind");
        String text = requiredText(body, "text");
        if (!kind.equals("append")) throw new IllegalArgumentException();
        if (campaign.replayEventsById.containsKey(eventId)) throw new ReplayEventConflict();
        ReplayEvent event = new ReplayEvent(eventId, text, campaign.replayEvents.size() + 1L);
        campaign.replayEvents.add(event);
        campaign.replayEventsById.put(eventId, event);
        saveStorage();
        return replayEventJson(event);
    }

    private static synchronized String replay(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        StringBuilder story = new StringBuilder();
        StringBuilder ids = new StringBuilder();
        for (ReplayEvent event : campaign.replayEvents) {
            story.append(event.text);
            if (!ids.isEmpty()) ids.append(',');
            ids.append(event.eventId);
        }
        return "{\"story\":\"" + escape(story.toString()) + "\",\"event_ids\":" + jsonStrings(campaign.replayEvents.stream().map(event -> event.eventId).toList())
            + ",\"digest\":\"" + escape(ids + "|" + story) + "\"}";
    }

    private static String replayEventJson(ReplayEvent event) {
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"kind\":\"append\",\"text\":\""
            + escape(event.text) + "\",\"sequence\":" + event.sequence + "}";
    }

    private static synchronized String configureRngSeed(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!isCampaignDm(campaign, actor)) throw new Forbidden();
        if (body.size() != 1 || !body.containsKey("seed")) throw new IllegalArgumentException();
        String seed = requiredText(body, "seed");
        if (campaign.rngSeed != null) throw new RngConflict();
        campaign.rngSeed = seed;
        try { sql("INSERT INTO play_campaign_rng_seeds VALUES (" + sqlText(campaign.id) + "," + sqlText(seed) + ");"); }
        catch (IOException e) { throw new IllegalStateException("storage unavailable", e); }
        saveStorage();
        return rngLedgerJson(campaign);
    }

    private static synchronized String appendRngRoll(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (body.size() != 2 || !body.containsKey("roll_id") || !body.containsKey("sides")) throw new IllegalArgumentException();
        if (campaign.rngSeed == null) throw new RngConflict();
        String rollId = requiredText(body, "roll_id");
        long sides = integer(body, "sides");
        if (sides < 2 || sides > 100) throw new IllegalArgumentException();
        if (campaign.rngRollsById.containsKey(rollId)) throw new RngConflict();
        long sequence = campaign.rngRolls.size() + 1L;
        long acc = 0;
        byte[] bytes = (campaign.rngSeed + "|" + sequence + "|" + rollId + "|" + sides).getBytes(StandardCharsets.UTF_8);
        for (byte value : bytes) acc = (acc * 31 + (value & 0xffL)) & 0xffffffffL;
        RngRoll roll = new RngRoll(rollId, sides, (acc % sides) + 1, sequence);
        campaign.rngRolls.add(roll);
        campaign.rngRollsById.put(rollId, roll);
        try { sql("INSERT INTO play_campaign_rng_rolls VALUES (" + sqlText(campaign.id) + "," + roll.sequence + "," + sqlText(roll.rollId) + "," + roll.sides + "," + roll.result + ");"); }
        catch (IOException e) { throw new IllegalStateException("storage unavailable", e); }
        saveStorage();
        return rngRollJson(roll);
    }

    private static synchronized String rngLedger(String campaignId, User actor) {
        return rngLedgerJson(readablePlayCampaign(campaignId, actor));
    }

    private static String rngLedgerJson(PlayCampaign campaign) {
        StringBuilder out = new StringBuilder("{\"seed\":");
        out.append(campaign.rngSeed == null ? "null" : "\"" + escape(campaign.rngSeed) + "\"").append(",\"rolls\":[");
        for (int i = 0; i < campaign.rngRolls.size(); i++) {
            if (i > 0) out.append(',');
            out.append(rngRollJson(campaign.rngRolls.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String rngRollJson(RngRoll roll) {
        return "{\"roll_id\":\"" + escape(roll.rollId) + "\",\"sides\":" + roll.sides
            + ",\"result\":" + roll.result + ",\"sequence\":" + roll.sequence + "}";
    }

    private static synchronized String createModerationReport(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (body.size() != 3 || !body.containsKey("report_id") || !body.containsKey("target_id") || !body.containsKey("reason")) throw new IllegalArgumentException();
        String reportId = requiredText(body, "report_id");
        String targetId = requiredText(body, "target_id");
        String reason = requiredText(body, "reason");
        if (campaign.moderationReports.containsKey(reportId)) throw new ModerationReportConflict();
        ModerationReport report = new ModerationReport(reportId, targetId, reason, actor.username, campaign.moderationReports.size() + 1L);
        campaign.moderationReports.put(reportId, report);
        saveStorage();
        return moderationReportJson(report);
    }

    private static synchronized String moderationReports(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"reports\":[");
        boolean first = true;
        for (ModerationReport report : campaign.moderationReports.values()) {
            if (!first) out.append(',');
            out.append(moderationReportJson(report));
            first = false;
        }
        return out.append("]}").toString();
    }

    private static synchronized String resolveModerationReport(String campaignId, String reportId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        ModerationReport report = campaign.moderationReports.get(reportId);
        if (report == null) throw new UnknownRecord();
        if (body.size() != 2 || !body.containsKey("action") || !body.containsKey("note")) throw new IllegalArgumentException();
        String action = requiredText(body, "action");
        String note = requiredText(body, "note");
        if (!action.equals("allow") && !action.equals("remove")) throw new IllegalArgumentException();
        if (!report.status.equals("open")) throw new ModerationReportConflict();
        report.status = "resolved";
        report.action = action;
        report.note = note;
        report.resolver = actor.username;
        saveStorage();
        return moderationReportJson(report);
    }

    private static String moderationReportJson(ModerationReport report) {
        StringBuilder out = new StringBuilder("{\"report_id\":\"").append(escape(report.reportId))
            .append("\",\"target_id\":\"").append(escape(report.targetId))
            .append("\",\"reason\":\"").append(escape(report.reason))
            .append("\",\"status\":\"").append(report.status)
            .append("\",\"reporter\":\"").append(escape(report.reporter))
            .append("\",\"sequence\":").append(report.sequence);
        if (report.status.equals("resolved")) out.append(",\"action\":\"").append(report.action)
            .append("\",\"note\":\"").append(escape(report.note))
            .append("\",\"resolver\":\"").append(escape(report.resolver)).append('"');
        return out.append('}').toString();
    }

    private static synchronized String replaceSafetyBoundaries(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        requireCampaignDm(campaign, actor);
        if (body.size() != 1 || !body.containsKey("blocked_tags")) throw new IllegalArgumentException();
        List<String> tags = safetyTags(array(body, "blocked_tags"));
        tags.sort(String::compareTo);
        campaign.blockedSafetyTags.clear();
        campaign.blockedSafetyTags.addAll(tags);
        saveStorage();
        return safetyBoundariesJson(campaign);
    }

    private static synchronized String safetyBoundaries(String campaignId, User actor) {
        return safetyBoundariesJson(readablePlayCampaign(campaignId, actor));
    }

    private static synchronized String submitSafetyCheck(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (body.size() != 4 || !body.keySet().containsAll(List.of("event_id", "kind", "text", "tags"))) throw new IllegalArgumentException();
        String eventId = requiredText(body, "event_id");
        String kind = string(body, "kind");
        String text = requiredText(body, "text");
        List<String> tags = safetyTags(array(body, "tags"));
        if (!kind.equals("narration") && !kind.equals("chat")) throw new IllegalArgumentException();
        if (campaign.safetyEventsById.containsKey(eventId)) throw new SafetyCheckConflict();
        for (String tag : tags) if (campaign.blockedSafetyTags.contains(tag)) throw new SafetyCheckConflict();
        SafetyEvent event = new SafetyEvent(eventId, kind, text, tags, campaign.safetyEvents.size() + 1L);
        campaign.safetyEvents.add(event);
        campaign.safetyEventsById.put(eventId, event);
        saveStorage();
        return safetyEventJson(event);
    }

    private static synchronized String safetyEvents(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"events\":[");
        for (int i = 0; i < campaign.safetyEvents.size(); i++) {
            if (i > 0) out.append(',');
            out.append(safetyEventJson(campaign.safetyEvents.get(i)));
        }
        return out.append("]}").toString();
    }

    private static List<String> safetyTags(List<Object> values) {
        if (values.isEmpty()) throw new IllegalArgumentException();
        List<String> tags = new ArrayList<>();
        for (Object value : values) {
            if (!(value instanceof String tag) || tag.trim().isEmpty() || tags.contains(tag)) throw new IllegalArgumentException();
            tags.add(tag);
        }
        return tags;
    }

    private static String safetyBoundariesJson(PlayCampaign campaign) {
        return "{\"blocked_tags\":" + jsonStrings(campaign.blockedSafetyTags) + "}";
    }

    private static String safetyEventJson(SafetyEvent event) {
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"kind\":\"" + event.kind
            + "\",\"text\":\"" + escape(event.text) + "\",\"tags\":" + jsonStrings(event.tags)
            + ",\"sequence\":" + event.sequence + "}";
    }

    private static synchronized IdempotentEventResult createIdempotentEvent(String campaignId, User actor, String key, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (key == null || key.trim().isEmpty()) throw new IllegalArgumentException();
        key = key.trim();
        if (body.size() != 2 || !body.containsKey("event_id") || !body.containsKey("value")) throw new IllegalArgumentException();
        String eventId = requiredText(body, "event_id");
        String value = requiredText(body, "value");
        IdempotentEvent existing = campaign.idempotentEventsByKey.get(key);
        if (existing != null) {
            if (!existing.eventId.equals(eventId) || !existing.value.equals(value)) throw new IdempotentEventConflict();
            return new IdempotentEventResult(existing, false);
        }
        if (campaign.idempotentEventsById.containsKey(eventId)) throw new IdempotentEventConflict();
        long sequence = campaign.idempotentEvents.size() + 1L;
        IdempotentEvent event = new IdempotentEvent(eventId, value, sequence, key);
        campaign.idempotentEvents.add(event);
        campaign.idempotentEventsByKey.put(key, event);
        campaign.idempotentEventsById.put(eventId, event);
        saveStorage();
        return new IdempotentEventResult(event, true);
    }

    private static synchronized String idempotentEvents(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"events\":[");
        List<IdempotentEvent> events = new ArrayList<>(campaign.idempotentEvents);
        events.sort(Comparator.comparingLong(event -> event.sequence));
        for (int i = 0; i < events.size(); i++) {
            if (i > 0) out.append(',');
            out.append(idempotentEventJson(events.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String idempotentEventJson(IdempotentEvent event) {
        return "{\"event_id\":\"" + escape(event.eventId) + "\",\"value\":\"" + escape(event.value)
            + "\",\"sequence\":" + event.sequence + ",\"idempotency_key\":\"" + escape(event.idempotencyKey) + "\"}";
    }

    private static synchronized SafeTurnResult submitSafeTurn(String campaignId, User actor, Map<String, Object> body) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        if (body.size() != 3 || !body.containsKey("submission_id") || !body.containsKey("expected_turn") || !body.containsKey("action")) throw new IllegalArgumentException();
        String submissionId = requiredText(body, "submission_id");
        long expectedTurn = positive(integer(body, "expected_turn"));
        String action = requiredText(body, "action");
        if (campaign.safeTurnsBySubmissionId.containsKey(submissionId)) throw new SafeTurnConflict();
        if (expectedTurn != campaign.safeCurrentTurn) return new SafeTurnResult(false, "{\"current_turn\":" + campaign.safeCurrentTurn + "}");
        long acceptedTurn = campaign.safeCurrentTurn++;
        SafeTurn turn = new SafeTurn(submissionId, action, acceptedTurn, campaign.safeCurrentTurn);
        campaign.safeTurns.add(turn);
        campaign.safeTurnsBySubmissionId.put(submissionId, turn);
        saveStorage();
        return new SafeTurnResult(true, safeTurnJson(turn));
    }

    private static synchronized String safeTurns(String campaignId, User actor) {
        PlayCampaign campaign = readablePlayCampaign(campaignId, actor);
        StringBuilder out = new StringBuilder("{\"current_turn\":").append(campaign.safeCurrentTurn).append(",\"accepted\":[");
        for (int i = 0; i < campaign.safeTurns.size(); i++) {
            if (i > 0) out.append(',');
            out.append(safeTurnJson(campaign.safeTurns.get(i)));
        }
        return out.append("]}").toString();
    }

    private static String safeTurnJson(SafeTurn turn) {
        return "{\"submission_id\":\"" + escape(turn.submissionId) + "\",\"action\":\"" + escape(turn.action)
            + "\",\"accepted_turn\":" + turn.acceptedTurn + ",\"next_turn\":" + turn.nextTurn + "}";
    }

    private static PlayCampaign readablePlayCampaign(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        boolean owner = actor.role.equals("dm") && campaign.owner.equals(actor.username);
        if (!owner && (!actor.role.equals("player") || !campaign.members.containsKey(actor.username))) throw new Forbidden();
        return campaign;
    }

    private static String projectionJson(PlayCampaign campaign) {
        String story = "";
        long danger = 0;
        StringBuilder ids = new StringBuilder("[");
        List<ProjectionEvent> ordered = new ArrayList<>(campaign.projectionEvents);
        ordered.sort(Comparator.comparingLong(event -> event.sequence));
        for (ProjectionEvent event : ordered) {
            if (ids.length() > 1) ids.append(',');
            ids.append('"').append(escape(event.eventId)).append('"');
            if (event.kind.equals("set-story")) story = event.value;
            else if (event.kind.equals("increment-danger")) danger++;
        }
        return "{\"story\":\"" + escape(story) + "\",\"danger\":" + danger + ",\"applied_event_ids\":" + ids.append(']') + "}";
    }

    private static String projectionEventJson(ProjectionEvent event) {
        return "{\"sequence\":" + event.sequence + ",\"event_id\":\"" + escape(event.eventId)
            + "\",\"kind\":\"" + event.kind + "\"" + (event.value == null ? "" : ",\"value\":\"" + escape(event.value) + "\"") + "}";
    }

    private static PlayCampaign ownedPlayCampaign(String campaignId, User actor) {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) throw new UnknownRecord();
        if (!actor.role.equals("dm") || !campaign.owner.equals(actor.username)) throw new Forbidden();
        return campaign;
    }

    private static Encounter ownedEncounter(String campaignId, String encounterId, User actor) {
        ownedPlayCampaign(campaignId, actor);
        Encounter encounter = ENCOUNTERS.get(encounterId);
        if (encounter == null || !encounter.campaignId.equals(campaignId)) throw new UnknownRecord();
        return encounter;
    }

    private static String playCampaignQueue(PlayCampaign campaign) {
        List<String> queue = new ArrayList<>();
        for (PartyMember member : campaign.members.values()) {
            queue.add(member.username);
            queue.add(campaign.owner);
        }
        return jsonStrings(queue);
    }

    private static String recentNarrations(PlayCampaign campaign) {
        StringBuilder result = new StringBuilder("[");
        for (int i = 0; i < campaign.events.size(); i++) {
            if (i > 0) result.append(',');
            PlayEvent event = campaign.events.get(i);
            result.append(event.kind.equals("narration") ? narrationJson(event)
                : event.kind.equals("chat") ? messageJson(event)
                : event.kind.equals("resolution") ? resolutionJson(event, null, null)
                : event.kind.equals("travel") ? travelJson(event, campaign.owner)
                : event.kind.equals("rest") ? restJson(event, campaign.members.get(event.actor), campaign.owner)
                : actionJson(event, null));
        }
        return result.append(']').toString();
    }

    private static synchronized String addCampaignCharacter(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        long level = characterLevel(b, "level");
        String characterClass = requiredText(b, "class");
        if (campaignHasId(id, record -> record.characters)) throw new DuplicateId();
        CampaignCharacter character = new CampaignCharacter(id, name, level, characterClass);
        campaign.characters.put(id, character);
        saveStorage();
        return campaignCharacterJson(character);
    }

    private static synchronized String scheduleSession(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String startsAt = requiredText(b, "starts_at");
        Instant starts;
        try { starts = Instant.parse(startsAt); }
        catch (DateTimeParseException e) { throw new IllegalArgumentException(); }
        long durationMinutes = positive(integer(b, "duration_minutes"));
        List<String> agenda = strings(array(b, "agenda"));
        if (campaignHasId(id, record -> record.scheduledSessions)) throw new DuplicateId();
        ScheduledSession session = new ScheduledSession(id, startsAt, starts, durationMinutes, agenda);
        campaign.scheduledSessions.put(id, session);
        saveStorage();
        return scheduledSessionJson(session, true);
    }

    private static synchronized String recordAttendance(String campaignId, String sessionId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        ScheduledSession session = campaign.scheduledSessions.get(sessionId);
        if (session == null) throw new UnknownRecord();
        List<String> present = strings(array(b, "present"));
        List<String> absent = strings(array(b, "absent"));
        Map<String, Boolean> attendance = new LinkedHashMap<>();
        for (String characterId : present) {
            if (!campaign.characters.containsKey(characterId) || attendance.put(characterId, true) != null) throw new IllegalArgumentException();
        }
        for (String characterId : absent) {
            if (!campaign.characters.containsKey(characterId) || attendance.put(characterId, false) != null) throw new IllegalArgumentException();
        }
        session.attendance.clear();
        session.attendance.putAll(attendance);
        saveStorage();
        return "{\"session_id\":\"" + escape(session.id) + "\",\"present_count\":" + present.size()
            + ",\"absent_count\":" + absent.size() + "}";
    }

    private static synchronized String nextScheduledSession(String campaignId) {
        Campaign campaign = campaign(campaignId);
        ScheduledSession next = campaign.scheduledSessions.values().stream()
            .min(Comparator.comparing((ScheduledSession session) -> session.starts).thenComparing(session -> session.id))
            .orElseThrow(UnknownRecord::new);
        return scheduledSessionJson(next, false);
    }

    private static synchronized String addInventory(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String itemSlug = requiredText(b, "item_slug");
        long quantity = positive(integer(b, "quantity"));
        String owner = requiredText(b, "owner");
        if (!owner.equals("party")) throw new IllegalArgumentException();
        campaign.partyInventory.merge(itemSlug, quantity, Math::addExact);
        saveStorage();
        return "{\"item_slug\":\"" + escape(itemSlug) + "\",\"quantity\":" + quantity + ",\"owner\":\"party\"}";
    }

    private static synchronized String assignEquipment(String campaignId, String characterId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        if (!campaign.characters.containsKey(characterId)) throw new UnknownRecord();
        String itemSlug = requiredText(b, "item_slug");
        long quantity = positive(integer(b, "quantity"));
        long available = campaign.partyInventory.getOrDefault(itemSlug, 0L);
        if (available < quantity) throw new IllegalArgumentException();
        if (available == quantity) campaign.partyInventory.remove(itemSlug);
        else campaign.partyInventory.put(itemSlug, available - quantity);
        campaign.equipment.computeIfAbsent(characterId, unused -> new LinkedHashMap<>()).merge(itemSlug, quantity, Math::addExact);
        saveStorage();
        return "{\"character_id\":\"" + escape(characterId) + "\",\"item_slug\":\"" + escape(itemSlug) + "\",\"quantity\":" + quantity + "}";
    }

    private static synchronized String createCraftingProject(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String characterId = requiredText(b, "character_id");
        String itemSlug = requiredText(b, "item_slug");
        long daysRequired = positive(integer(b, "days_required"));
        long costGp = integer(b, "cost_gp");
        if (costGp < 0 || !campaign.characters.containsKey(characterId)) throw new IllegalArgumentException();
        if (campaignHasId(id, record -> record.craftingProjects)) throw new DuplicateId();
        CraftingProject project = new CraftingProject(id, characterId, itemSlug, daysRequired, costGp);
        campaign.craftingProjects.put(id, project);
        saveStorage();
        return craftingProjectJson(project, true);
    }

    private static synchronized String advanceCraftingProject(String campaignId, String projectId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        CraftingProject project = campaign.craftingProjects.get(projectId);
        if (project == null) throw new UnknownRecord();
        long days = positive(integer(b, "days"));
        if (!project.status.equals("complete")) {
            project.daysCompleted = Math.min(project.daysRequired, Math.addExact(project.daysCompleted, days));
            if (project.daysCompleted == project.daysRequired) {
                project.status = "complete";
                campaign.partyInventory.merge(project.itemSlug, 1L, Math::addExact);
            }
            saveStorage();
        }
        return craftingProjectJson(project, false);
    }

    private static synchronized String addCampaignEvent(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String kind = requiredText(b, "kind");
        String summary = requiredText(b, "summary");
        if (campaignHasId(id, record -> record.events)) throw new DuplicateId();
        campaign.events.put(id, new CampaignEvent(id, kind, summary));
        saveStorage();
        return "{\"id\":\"" + escape(id) + "\",\"kind\":\"" + escape(kind) + "\"}";
    }

    private static synchronized String createFaction(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        String stance = requiredText(b, "stance");
        if (campaignHasId(id, record -> record.factions)) throw new DuplicateId();
        Faction faction = new Faction(id, name, stance);
        campaign.factions.put(id, faction);
        saveStorage();
        return factionJson(faction);
    }

    private static synchronized String createNpc(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String name = requiredText(b, "name");
        String factionId = requiredText(b, "faction_id");
        long disposition = integer(b, "disposition");
        if (!campaign.factions.containsKey(factionId)) throw new IllegalArgumentException();
        if (campaignHasId(id, record -> record.npcs)) throw new DuplicateId();
        Npc npc = new Npc(id, name, factionId, disposition);
        campaign.npcs.put(id, npc);
        saveStorage();
        return npcJson(npc);
    }

    private static synchronized String createQuest(String campaignId, Map<String, Object> b) {
        Campaign campaign = campaign(campaignId);
        String id = requiredText(b, "id");
        String title = requiredText(b, "title");
        String status = requiredText(b, "status");
        boolean duplicateId = campaignHasId(id, record -> record.quests);
        if (!(status.equals("active") || status.equals("completed") || status.equals("blocked")) || duplicateId) {
            if (duplicateId) throw new DuplicateId();
            throw new IllegalArgumentException();
        }
        List<String> milestones = strings(array(b, "milestones"));
        Quest quest = new Quest(id, title, status, milestones);
        campaign.quests.put(id, quest);
        saveStorage();
        return questJson(quest, true);
    }

    private static synchronized String updateQuestProgress(String campaignId, String questId, Map<String, Object> b) {
        Quest quest = campaign(campaignId).quests.get(questId);
        if (quest == null) throw new UnknownRecord();
        List<String> completed = strings(array(b, "completed"));
        for (String milestone : completed) {
            Boolean done = quest.milestones.get(milestone);
            if (done == null) throw new IllegalArgumentException();
            quest.milestones.put(milestone, true);
        }
        saveStorage();
        return questJson(quest, false);
    }

    private static synchronized String questSummary(String campaignId) {
        Campaign campaign = campaign(campaignId);
        long active = 0, completed = 0, blocked = 0;
        for (Quest quest : campaign.quests.values()) {
            if (quest.status.equals("active")) active++;
            else if (quest.status.equals("completed")) completed++;
            else blocked++;
        }
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"active\":" + active
            + ",\"completed\":" + completed + ",\"blocked\":" + blocked + "}";
    }

    private static synchronized String relationshipSummary(String campaignId) {
        Campaign campaign = campaign(campaignId);
        long friendly = campaign.npcs.values().stream().filter(npc -> npc.disposition > 0).count();
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"factions\":" + campaign.factions.size()
            + ",\"npcs\":" + campaign.npcs.size() + ",\"friendly_npcs\":" + friendly + "}";
    }

    private static synchronized String inventorySummary(String campaignId) {
        Campaign campaign = campaign(campaignId);
        long assignedItems = 0;
        for (Map<String, Long> assigned : campaign.equipment.values()) assignedItems += assigned.size();
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"party_items\":" + campaign.partyInventory.size()
            + ",\"assigned_items\":" + assignedItems + ",\"healing_potions_available\":"
            + campaign.partyInventory.getOrDefault("healing-potion", 0L) + "}";
    }

    private static synchronized String campaignAnalyticsSummary(String campaignId) {
        Campaign campaign = campaign(campaignId);
        boolean hasDm = !campaign.dm.isEmpty();
        boolean hasCharacters = !campaign.characters.isEmpty();
        boolean hasNextSession = !campaign.scheduledSessions.isEmpty();
        long openQuests = campaign.quests.values().stream().filter(quest -> !quest.status.equals("completed")).count();
        boolean hasActiveQuest = campaign.quests.values().stream().anyMatch(quest -> quest.status.equals("active"));
        long friendlyNpcs = campaign.npcs.values().stream().filter(npc -> npc.disposition > 0).count();
        long readiness = (hasDm ? 25 : 0) + (hasCharacters ? 25 : 0)
            + (hasNextSession ? 20 : 0) + (hasActiveQuest ? 15 : 0);
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"readiness_score\":" + readiness
            + ",\"open_quests\":" + openQuests + ",\"friendly_npcs\":" + friendlyNpcs
            + ",\"scheduled_sessions\":" + campaign.scheduledSessions.size()
            + ",\"inventory_items\":" + campaign.partyInventory.size() + "}";
    }

    private static synchronized String campaignRiskReport(String campaignId, Map<String, Object> b) {
        bool(b, "include_zeroes");
        Campaign campaign = campaign(campaignId);
        boolean hasDm = !campaign.dm.isEmpty();
        boolean hasCharacters = !campaign.characters.isEmpty();
        boolean hasNextSession = !campaign.scheduledSessions.isEmpty();
        boolean hasActiveQuest = campaign.quests.values().stream().anyMatch(quest -> quest.status.equals("active"));
        List<String> missing = new ArrayList<>();
        if (!hasDm) missing.add("dm");
        if (!hasCharacters) missing.add("characters");
        if (!hasNextSession) missing.add("next_session");
        if (!hasActiveQuest) missing.add("active_quest");
        String riskLevel = missing.isEmpty() ? "low" : missing.size() == 1 ? "medium" : "high";
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"risk_level\":\"" + riskLevel
            + "\",\"missing\":" + jsonStrings(missing) + ",\"signals\":{\"has_dm\":" + hasDm
            + ",\"has_characters\":" + hasCharacters + ",\"has_next_session\":" + hasNextSession
            + ",\"has_active_quest\":" + hasActiveQuest + "}}";
    }

    private static synchronized String campaignState(String id) {
        Campaign campaign = campaign(id);
        StringBuilder out = new StringBuilder(campaignJson(campaign, false)).append(",\"characters\":[");
        int index = 0;
        for (CampaignCharacter character : campaign.characters.values()) {
            if (index++ > 0) out.append(',');
            out.append(campaignCharacterJson(character));
        }
        return out.append("],\"log_count\":").append(campaign.events.size()).append('}').toString();
    }

    private static synchronized String campaignAudit(String campaignId) {
        Campaign campaign = campaign(campaignId);
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"events\":" + campaign.events.size()
            + ",\"quests\":" + campaign.quests.size() + ",\"npcs\":" + campaign.npcs.size()
            + ",\"sessions\":" + campaign.scheduledSessions.size() + "}";
    }

    private static synchronized String campaignExport(String campaignId) {
        Campaign campaign = campaign(campaignId);
        return "{\"campaign_id\":\"" + escape(campaign.id) + "\",\"name\":\"" + escape(campaign.name)
            + "\",\"characters\":" + campaign.characters.size() + ",\"quests\":" + campaign.quests.size()
            + ",\"npcs\":" + campaign.npcs.size() + ",\"inventory_items\":" + campaign.partyInventory.size()
            + ",\"sessions\":" + campaign.scheduledSessions.size() + ",\"schema_version\":1}";
    }

    private static Campaign campaign(String id) {
        Campaign campaign = CAMPAIGNS.get(id);
        if (campaign == null) throw new UnknownRecord();
        return campaign;
    }

    /** Campaign record IDs are globally unique within each record kind, not merely per campaign. */
    private static boolean campaignHasId(String id, Function<Campaign, Map<String, ?>> records) {
        for (Campaign campaign : CAMPAIGNS.values()) if (records.apply(campaign).containsKey(id)) return true;
        return false;
    }

    private static String campaignId(String path, String suffix) {
        return path.substring("/v1/campaigns/".length(), path.length() - suffix.length());
    }

    private static String playCampaignId(String path, String suffix) {
        return path.substring("/v1/play/campaigns/".length(), path.length() - suffix.length());
    }

    private static boolean playCharacterExists(PlayCampaign campaign, String characterId) {
        for (PartyMember member : campaign.members.values()) if (member.characterId.equals(characterId)) return true;
        return false;
    }

    private static String campaignJson(Campaign campaign) { return campaignJson(campaign, true); }
    private static String campaignJson(Campaign campaign, boolean close) {
        return "{\"id\":\"" + escape(campaign.id) + "\",\"name\":\"" + escape(campaign.name)
            + "\",\"dm\":\"" + escape(campaign.dm) + (close ? "\"}" : "\"");
    }
    private static String playCampaignJson(PlayCampaign campaign) {
        return "{\"id\":\"" + escape(campaign.id) + "\",\"name\":\"" + escape(campaign.name)
            + "\",\"owner\":\"" + escape(campaign.owner) + "\",\"status\":\"" + campaign.status + "\",\"max_players\":" + campaign.maxPlayers + "}";
    }
    private static String playCampaignStartJson(PlayCampaign campaign) {
        return "{\"id\":\"" + escape(campaign.id) + "\",\"status\":\"" + campaign.status
            + "\",\"current_actor\":\"" + escape(campaign.currentActor) + "\",\"turn_number\":" + campaign.turnNumber + "}";
    }
    private static String sessionZeroJson(SessionZero settings) {
        StringBuilder out = new StringBuilder("{\"rules\":\"").append(escape(settings.rules)).append("\",\"tone\":\"")
            .append(escape(settings.tone)).append("\",\"consent\":[");
        for (int i = 0; i < settings.consent.size(); i++) {
            if (i > 0) out.append(',');
            out.append('\"').append(escape(settings.consent.get(i))).append('\"');
        }
        return out.append("]}").toString();
    }
    private static String contentJson(Content content) {
        return "{\"content_id\":\"" + escape(content.contentId) + "\",\"kind\":\"" + escape(content.kind)
            + "\",\"text\":\"" + escape(content.text) + "\",\"tags\":" + jsonStrings(content.tags) + "}";
    }
    private static String campaignDocumentJson(PlayCampaign campaign, boolean includeDmNotes) {
        return "{\"story\":\"" + escape(campaign.story) + "\""
            + (includeDmNotes ? ",\"dm_notes\":\"" + escape(campaign.dmNotes) + "\"" : "") + "}";
    }
    private static String sceneJson(Scene scene) {
        return "{\"id\":\"" + escape(scene.id) + "\",\"name\":\"" + escape(scene.name)
            + "\",\"status\":\"" + scene.status + "\"}";
    }
    private static String locationJson(Location location) {
        return "{\"id\":\"" + escape(location.id) + "\",\"name\":\"" + escape(location.name) + "\"}";
    }
    private static String encounterJson(Encounter encounter) {
        return "{\"id\":\"" + escape(encounter.id) + "\",\"name\":\"" + escape(encounter.name)
            + "\",\"status\":\"" + encounter.status + "\",\"combatants\":[]}";
    }
    private static String encounterRewardJson(String encounterId, EncounterReward reward) {
        StringBuilder out = new StringBuilder("{\"encounter_id\":\"").append(escape(encounterId))
            .append("\",\"xp\":").append(reward.xp).append(",\"loot\":[");
        for (int i = 0; i < reward.loot.size(); i++) {
            if (i > 0) out.append(',');
            Loot item = reward.loot.get(i);
            out.append("{\"slug\":\"").append(escape(item.slug)).append("\",\"quantity\":").append(item.quantity).append('}');
        }
        return out.append("]}").toString();
    }
    private static String encounterMonsterJson(EncounterMonster monster) {
        return "{\"monster_id\":\"" + escape(monster.id) + "\",\"name\":\"" + escape(monster.name)
            + "\",\"hp_max\":" + monster.hpMax + ",\"initiative\":" + monster.initiative
            + ",\"hp_current\":" + monster.hpCurrent + "}";
    }
    private static String encounterCombatantJson(EncounterCombatant combatant) {
        return "{\"member\":\"" + escape(combatant.username) + "\",\"character_id\":\""
            + escape(combatant.characterId) + "\",\"name\":\"" + escape(combatant.name)
            + "\",\"initiative\":" + combatant.initiative + "}";
    }
    private static String jsonNullableString(String value) {
        return value == null ? "null" : "\"" + escape(value) + "\"";
    }
    private static String partyMemberJson(PartyMember member) {
        return "{\"username\":\"" + escape(member.username) + "\",\"character_id\":\"" + escape(member.characterId)
            + "\",\"name\":\"" + escape(member.name) + "\",\"class\":\"" + escape(member.characterClass) + "\"}";
    }
    private static String narrationJson(PlayEvent narration) {
        return "{\"sequence\":" + narration.sequence + ",\"kind\":\"narration\",\"actor\":\""
            + escape(narration.actor) + "\",\"text\":\"" + escape(narration.text) + "\"}";
    }
    private static String messageJson(PlayEvent message) {
        return "{\"sequence\":" + message.sequence + ",\"kind\":\"chat\",\"actor\":\""
            + escape(message.actor) + "\",\"text\":\"" + escape(message.text) + "\"}";
    }
    private static String actionJson(PlayEvent action, String nextActor) {
        return "{\"sequence\":" + action.sequence + ",\"kind\":\"action\",\"actor\":\""
            + escape(action.actor) + "\",\"type\":\"" + escape(action.type) + "\",\"text\":\""
            + escape(action.text) + "\"" + (nextActor == null ? "" : ",\"next_actor\":\"" + escape(nextActor) + "\"") + "}";
    }
    private static String combatActionJson(PlayEvent action) {
        return "{\"sequence\":" + action.sequence + ",\"kind\":\"combat_action\",\"actor\":\""
            + escape(action.actor) + "\",\"type\":\"" + escape(action.type) + "\",\"target\":\""
            + escape(action.target) + "\",\"text\":\"" + escape(action.text) + "\"}";
    }
    private static String resolutionJson(PlayEvent resolution, String nextActor, Long turnNumber) {
        return "{\"sequence\":" + resolution.sequence + ",\"kind\":\"resolution\",\"actor\":\"dm\",\"text\":\""
            + escape(resolution.text) + "\"" + (nextActor == null ? "" : ",\"next_actor\":\"" + escape(nextActor) + "\"")
            + (turnNumber == null ? "" : ",\"turn_number\":" + turnNumber) + "}";
    }
    private static String travelJson(PlayEvent travel, String nextActor) {
        return "{\"sequence\":" + travel.sequence + ",\"kind\":\"travel\",\"actor\":\""
            + escape(travel.actor) + "\",\"destination_id\":\"" + escape(travel.type)
            + "\",\"travel_turns\":" + travel.text + ",\"next_actor\":\"" + escape(nextActor) + "\"}";
    }
    private static String restJson(PlayEvent rest, PartyMember member, String nextActor) {
        return "{\"sequence\":" + rest.sequence + ",\"kind\":\"rest\",\"actor\":\""
            + escape(rest.actor) + "\",\"type\":\"" + escape(rest.type) + "\",\"hp_current\":"
            + member.hpCurrent + ",\"hp_max\":" + member.hpMax + ",\"next_actor\":\"" + escape(nextActor) + "\"}";
    }
    private static String campaignCharacterJson(CampaignCharacter character) {
        return "{\"id\":\"" + escape(character.id) + "\",\"name\":\"" + escape(character.name)
            + "\",\"level\":" + character.level + ",\"class\":\"" + escape(character.characterClass) + "\"}";
    }
    private static String questJson(Quest quest, boolean includeTitle) {
        StringBuilder out = new StringBuilder("{\"id\":\"").append(escape(quest.id)).append("\",");
        if (includeTitle) out.append("\"title\":\"").append(escape(quest.title)).append("\",");
        return out.append("\"status\":\"").append(quest.status).append("\",\"milestones_total\":")
            .append(quest.milestones.size()).append(",\"milestones_done\":").append(quest.milestones.values().stream().filter(Boolean::booleanValue).count()).append('}').toString();
    }
    private static String factionJson(Faction faction) {
        return "{\"id\":\"" + escape(faction.id) + "\",\"name\":\"" + escape(faction.name)
            + "\",\"stance\":\"" + escape(faction.stance) + "\"}";
    }
    private static String npcJson(Npc npc) {
        return "{\"id\":\"" + escape(npc.id) + "\",\"name\":\"" + escape(npc.name)
            + "\",\"faction_id\":\"" + escape(npc.factionId) + "\",\"disposition\":" + npc.disposition + "}";
    }
    private static String craftingProjectJson(CraftingProject project, boolean includeDetails) {
        String out = "{\"id\":\"" + escape(project.id) + "\",";
        if (includeDetails) out += "\"character_id\":\"" + escape(project.characterId) + "\",\"item_slug\":\"" + escape(project.itemSlug)
            + "\",\"days_required\":" + project.daysRequired + ",";
        return out + "\"days_completed\":" + project.daysCompleted + ",\"status\":\"" + project.status + "\"}";
    }
    private static String scheduledSessionJson(ScheduledSession session, boolean includeDuration) {
        String out = "{\"id\":\"" + escape(session.id) + "\",\"starts_at\":\"" + escape(session.startsAt) + "\",";
        if (includeDuration) out += "\"duration_minutes\":" + session.durationMinutes + ",";
        return out + "\"agenda_count\":" + session.agenda.size() + "}";
    }

    private static String monsterJson(Monster monster, boolean includeTags) {
        String out = "{\"slug\":\"" + escape(monster.slug) + "\",\"name\":\"" + escape(monster.name)
            + "\",\"cr\":\"" + escape(monster.cr) + "\",\"armor_class\":" + monster.armorClass
            + ",\"hit_points\":" + monster.hitPoints;
        if (!includeTags) return out + "}";
        StringBuilder tags = new StringBuilder(",\"tags\":[");
        for (int i = 0; i < monster.tags.size(); i++) {
            if (i > 0) tags.append(',');
            tags.append('\"').append(escape(monster.tags.get(i))).append('\"');
        }
        return out + tags.append("]}").toString();
    }

    private static String itemJson(Item item) {
        return "{\"slug\":\"" + escape(item.slug) + "\",\"name\":\"" + escape(item.name)
            + "\",\"type\":\"" + escape(item.type) + "\",\"rarity\":\"" + escape(item.rarity)
            + "\",\"cost_gp\":" + item.costGp + "}";
    }

    // Java's standard library has no password API, so PBKDF2 keeps password handling isolated and hashed.
    private static byte[] hashPassword(String password) {
        byte[] salt = new byte[16];
        RANDOM.nextBytes(salt);
        byte[] digest = pbkdf2(password.toCharArray(), salt);
        byte[] stored = new byte[salt.length + digest.length];
        System.arraycopy(salt, 0, stored, 0, salt.length);
        System.arraycopy(digest, 0, stored, salt.length, digest.length);
        return stored;
    }

    private static boolean verifyPassword(String password, byte[] stored) {
        if (stored.length < 17) return false;
        byte[] salt = new byte[16];
        System.arraycopy(stored, 0, salt, 0, salt.length);
        byte[] expected = new byte[stored.length - salt.length];
        System.arraycopy(stored, salt.length, expected, 0, expected.length);
        return MessageDigest.isEqual(expected, pbkdf2(password.toCharArray(), salt));
    }

    private static byte[] pbkdf2(char[] password, byte[] salt) {
        PBEKeySpec spec = new PBEKeySpec(password, salt, 100_000, 256);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
        } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
            throw new IllegalStateException("PBKDF2 unavailable", e);
        } finally {
            spec.clearPassword();
        }
    }

    private static String dice(Map<String, Object> b) {
        Matcher m = DICE.matcher(string(b, "expression"));
        if (!m.matches()) throw new IllegalArgumentException();
        long count = positive(m.group(1)), sides = positive(m.group(2));
        long modifier = m.group(3) == null ? 0 : number(m.group(3));
        long min = Math.addExact(count, modifier);
        long max = Math.addExact(Math.multiplyExact(count, sides), modifier);
        double average = (count * (sides + 1) / 2.0) + modifier;
        return "{\"dice_count\":" + count + ",\"sides\":" + sides + ",\"modifier\":" + modifier
            + ",\"min\":" + min + ",\"max\":" + max + ",\"average\":" + jsonNumber(average) + "}";
    }

    private static String ability(Map<String, Object> b) {
        long total = Math.addExact(integer(b, "roll"), integer(b, "modifier"));
        long dc = integer(b, "dc");
        return "{\"total\":" + total + ",\"success\":" + (total >= dc) + ",\"margin\":" + Math.subtractExact(total, dc) + "}";
    }

    private static String encounter(Map<String, Object> b) {
        List<Object> party = array(b, "party"), monsters = array(b, "monsters");
        if (party.isEmpty() || monsters.isEmpty()) throw new IllegalArgumentException();
        long easy = 0, medium = 0, hard = 0, deadly = 0, base = 0, monsterCount = 0;
        for (Object p : party) {
            if (integer(asObject(p), "level") != 3) throw new IllegalArgumentException();
            easy += 75; medium += 150; hard += 225; deadly += 400;
        }
        for (Object item : monsters) {
            Map<String, Object> monster = asObject(item);
            Integer xp = XP.get(string(monster, "cr"));
            long count = positive(integer(monster, "count"));
            if (xp == null) throw new IllegalArgumentException();
            base = Math.addExact(base, Math.multiplyExact(xp, count));
            monsterCount = Math.addExact(monsterCount, count);
        }
        double multiplier = encounterMultiplier(monsterCount);
        long adjusted = Math.round(base * multiplier);
        String difficulty = adjusted >= deadly ? "deadly" : adjusted >= hard ? "hard" : adjusted >= medium ? "medium" : adjusted >= easy ? "easy" : "trivial";
        return "{\"base_xp\":" + base + ",\"monster_count\":" + monsterCount + ",\"multiplier\":" + jsonNumber(multiplier)
            + ",\"adjusted_xp\":" + adjusted + ",\"difficulty\":\"" + difficulty + "\",\"thresholds\":{\"easy\":" + easy
            + ",\"medium\":" + medium + ",\"hard\":" + hard + ",\"deadly\":" + deadly + "}}";
    }

    private static synchronized String encounterBuilder(Map<String, Object> b) {
        String campaignId = requiredText(b, "campaign_id");
        campaign(campaignId);
        List<Object> party = array(b, "party");
        List<Object> monsterSlugs = array(b, "monster_slugs");
        if (party.isEmpty() || monsterSlugs.isEmpty()) throw new IllegalArgumentException();

        long easy = 0, medium = 0, hard = 0, deadly = 0, base = 0;
        for (Object member : party) {
            long level = characterLevel(asObject(member), "level");
            long[] thresholds = encounterThresholds(level);
            easy = Math.addExact(easy, thresholds[0]);
            medium = Math.addExact(medium, thresholds[1]);
            hard = Math.addExact(hard, thresholds[2]);
            deadly = Math.addExact(deadly, thresholds[3]);
        }
        for (Object value : monsterSlugs) {
            if (!(value instanceof String slug) || slug.isEmpty()) throw new IllegalArgumentException();
            Monster monster = MONSTERS.get(slug);
            if (monster == null) throw new UnknownRecord();
            Integer xp = XP.get(monster.cr);
            if (xp == null) throw new IllegalArgumentException();
            base = Math.addExact(base, xp);
        }
        long count = monsterSlugs.size();
        double multiplier = encounterMultiplier(count);
        long adjusted = Math.round(base * multiplier);
        String difficulty = adjusted >= deadly ? "deadly" : adjusted >= hard ? "hard" : adjusted >= medium ? "medium" : adjusted >= easy ? "easy" : "trivial";
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"base_xp\":" + base
            + ",\"adjusted_xp\":" + adjusted + ",\"difficulty\":\"" + difficulty
            + "\",\"monster_count\":" + count + ",\"recommendation\":\"" + recommendation(difficulty) + "\"}";
    }

    private static synchronized String lootParcel(Map<String, Object> b) {
        String campaignId = requiredText(b, "campaign_id");
        campaign(campaignId);
        if (integer(b, "tier") != 1) throw new IllegalArgumentException();
        integer(b, "seed");
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"coins_gp\":75,\"items\":[{\"slug\":\"healing-potion\",\"quantity\":2}]}";
    }

    private static synchronized String sessionRecap(Map<String, Object> b) {
        String campaignId = requiredText(b, "campaign_id");
        Campaign campaign = campaign(campaignId);
        if (campaign.events.isEmpty()) throw new IllegalArgumentException();
        CampaignEvent latest = null;
        for (CampaignEvent event : campaign.events.values()) latest = event;
        return "{\"campaign_id\":\"" + escape(campaignId) + "\",\"summary\":\""
            + escape(latest.summary) + "\",\"open_threads\":[\"Resolve goblin trail ambush\"]}";
    }

    private static double encounterMultiplier(long monsterCount) {
        return monsterCount == 1 ? 1 : monsterCount == 2 ? 1.5 : monsterCount <= 6 ? 2
            : monsterCount <= 10 ? 2.5 : monsterCount <= 14 ? 3 : 4;
    }

    private static String recommendation(String difficulty) {
        return switch (difficulty) {
            case "trivial" -> "no meaningful risk";
            case "easy" -> "safe warm-up";
            case "medium" -> "balanced challenge";
            case "hard" -> "dangerous fight";
            default -> "consider reducing foes";
        };
    }

    private static long[] encounterThresholds(long level) {
        return switch ((int) level) {
            case 1 -> new long[] {25, 50, 75, 100};
            case 2 -> new long[] {50, 100, 150, 200};
            case 3 -> new long[] {75, 150, 225, 400};
            case 4 -> new long[] {125, 250, 375, 500};
            case 5 -> new long[] {250, 500, 750, 1100};
            case 6 -> new long[] {300, 600, 900, 1400};
            case 7 -> new long[] {350, 750, 1100, 1700};
            case 8 -> new long[] {450, 900, 1400, 2100};
            case 9 -> new long[] {550, 1100, 1600, 2400};
            case 10 -> new long[] {600, 1200, 1900, 2800};
            case 11 -> new long[] {800, 1600, 2400, 3600};
            case 12 -> new long[] {1000, 2000, 3000, 4500};
            case 13 -> new long[] {1100, 2200, 3400, 5100};
            case 14 -> new long[] {1250, 2500, 3800, 5700};
            case 15 -> new long[] {1400, 2800, 4300, 6400};
            case 16 -> new long[] {1600, 3200, 4800, 7200};
            case 17 -> new long[] {2000, 3900, 5900, 8800};
            case 18 -> new long[] {2100, 4200, 6300, 9500};
            case 19 -> new long[] {2400, 4900, 7300, 10900};
            case 20 -> new long[] {2800, 5700, 8500, 12700};
            default -> throw new IllegalArgumentException();
        };
    }

    private static String initiative(Map<String, Object> b) {
        List<Combatant> all = new ArrayList<>();
        for (Object item : array(b, "combatants")) {
            Map<String, Object> c = asObject(item);
            String name = string(c, "name");
            long dex = integer(c, "dex"), roll = integer(c, "roll");
            all.add(new Combatant(name, dex, Math.addExact(roll, dex)));
        }
        all.sort(Comparator.comparingLong(Combatant::score).reversed().thenComparing(Comparator.comparingLong(Combatant::dex).reversed()).thenComparing(Combatant::name));
        StringBuilder out = new StringBuilder("{\"order\":[");
        for (int i = 0; i < all.size(); i++) {
            if (i > 0) out.append(',');
            Combatant c = all.get(i);
            out.append("{\"name\":\"").append(escape(c.name)).append("\",\"score\":").append(c.score).append('}');
        }
        return out.append("]}").toString();
    }

    private static synchronized String createSession(Map<String, Object> b) {
        String id = string(b, "id");
        if (id.isEmpty() || SESSIONS.containsKey(id)) throw new IllegalArgumentException();
        List<Combatant> order = new ArrayList<>();
        Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        for (Object item : array(b, "combatants")) {
            Map<String, Object> c = asObject(item);
            String name = string(c, "name");
            if (name.isEmpty() || conditions.containsKey(name)) throw new IllegalArgumentException();
            long dex = integer(c, "dex");
            order.add(new Combatant(name, dex, Math.addExact(integer(c, "roll"), dex)));
            conditions.put(name, new ArrayList<>());
        }
        if (order.isEmpty()) throw new IllegalArgumentException();
        order.sort(Comparator.comparingLong(Combatant::score).reversed().thenComparing(Comparator.comparingLong(Combatant::dex).reversed()).thenComparing(Combatant::name));
        CombatSession session = new CombatSession(id, order, conditions);
        SESSIONS.put(id, session);
        saveStorage();
        return sessionState(session, false);
    }

    private static synchronized String addCondition(String id, Map<String, Object> b) {
        CombatSession session = session(id);
        String target = string(b, "target");
        String condition = string(b, "condition");
        long duration = positive(integer(b, "duration_rounds"));
        List<Condition> attached = session.conditions.get(target);
        if (attached == null) throw new IllegalArgumentException();
        attached.add(new Condition(condition, duration));
        saveStorage();
        return "{\"target\":\"" + escape(target) + "\",\"conditions\":" + conditionsArray(attached) + "}";
    }

    private static synchronized String advance(String id) {
        CombatSession session = session(id);
        session.turnIndex++;
        if (session.turnIndex == session.order.size()) { session.turnIndex = 0; session.round++; }
        List<Condition> attached = session.conditions.get(session.order.get(session.turnIndex).name);
        for (int i = attached.size() - 1; i >= 0; i--) {
            Condition condition = attached.get(i);
            condition.remainingRounds--;
            if (condition.remainingRounds == 0) attached.remove(i);
        }
        saveStorage();
        return sessionState(session, true);
    }

    /* SQLite is accessed through the platform sqlite3 client so this remains a stdlib-only Java program. */
    private static synchronized void initializeStorage() throws IOException {
        sql("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            + "INSERT OR REPLACE INTO schema_meta VALUES ('schema_version','1');"
            + "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS monster_tags (monster_slug TEXT NOT NULL, position INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (monster_slug, position));"
            + "CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, max_players INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (campaign_id TEXT PRIMARY KEY);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, backup_id TEXT NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, backup_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_migrations (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, campaign_name TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_session_zero (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_session_zero_consent (campaign_id TEXT NOT NULL, position INTEGER NOT NULL, consent TEXT NOT NULL, PRIMARY KEY (campaign_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, content_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_content_tags (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, position INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, note_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, whisper_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, record_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_state (campaign_id TEXT PRIMARY KEY, status TEXT NOT NULL, current_actor TEXT, turn_number INTEGER);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_exploration_queue (campaign_id TEXT PRIMARY KEY, starts_party INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_turns (encounter_id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_order (encounter_id TEXT NOT NULL, position INTEGER NOT NULL, entry_key TEXT NOT NULL, PRIMARY KEY (encounter_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (encounter_id TEXT NOT NULL, monster_id TEXT NOT NULL, name TEXT NOT NULL, hp_max INTEGER NOT NULL, hp_current INTEGER NOT NULL, initiative INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (encounter_id, monster_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (encounter_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, initiative INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (encounter_id, username));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (encounter_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (encounter_id, target, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_encounter_reward_loot (encounter_id TEXT NOT NULL, position INTEGER NOT NULL, slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (encounter_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_scene_state (campaign_id TEXT PRIMARY KEY, current_scene_id TEXT);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_nudges (campaign_id TEXT PRIMARY KEY, nudge_count INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, invitation_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY (campaign_id, username));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, position INTEGER NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, PRIMARY KEY (campaign_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, timestamp INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, timestamp), UNIQUE (campaign_id, correlation_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, owner TEXT, level INTEGER NOT NULL DEFAULT 1, con_modifier INTEGER NOT NULL DEFAULT 0, str_score INTEGER NOT NULL DEFAULT 10, dex_score INTEGER NOT NULL DEFAULT 10, con_score INTEGER NOT NULL DEFAULT 10, int_score INTEGER NOT NULL DEFAULT 10, wis_score INTEGER NOT NULL DEFAULT 10, cha_score INTEGER NOT NULL DEFAULT 10, hp_current INTEGER NOT NULL DEFAULT 20, hp_max INTEGER NOT NULL DEFAULT 20, status TEXT NOT NULL DEFAULT 'conscious', death_save_successes INTEGER NOT NULL DEFAULT 0, death_save_failures INTEGER NOT NULL DEFAULT 0, gold INTEGER NOT NULL DEFAULT 10, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence));"
            + "CREATE TABLE IF NOT EXISTS play_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_inventory (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, slot));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_currency (campaign_id TEXT PRIMARY KEY, transfer_id INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, recipient_character_id TEXT, assigned_votes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, loot_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, name TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_recipe_ingredients (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id, item_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id));"
            + "CREATE TABLE IF NOT EXISTS play_character_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL, completions INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, activity_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, availability TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_settlement_services (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, service TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, character_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_shop_stock (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id, item_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, npc_id, dialogue_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, source_id, target_id, kind));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, clue_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_quest_dependencies (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, dependency_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id, dependency_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL, awarded INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_items (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id, item_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id, character_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, resolution_turn_number INTEGER, resolution_text TEXT, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, faction_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (campaign_id TEXT NOT NULL, position INTEGER NOT NULL, faction_id TEXT NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (campaign_id, position));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, type TEXT, text TEXT NOT NULL, target TEXT, PRIMARY KEY (campaign_id, sequence));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, roll_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, action TEXT, note TEXT, resolver TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, report_id));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key));"
            + "CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT NOT NULL, accepted_turn INTEGER NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, accepted_turn), UNIQUE (campaign_id, submission_id));"
            + "CREATE TABLE IF NOT EXISTS campaign_characters (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaign_events (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaign_quests (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS quest_milestones (quest_id TEXT NOT NULL, position INTEGER NOT NULL, milestone TEXT NOT NULL, done INTEGER NOT NULL, PRIMARY KEY (quest_id, position));"
            + "CREATE TABLE IF NOT EXISTS campaign_factions (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, name TEXT NOT NULL, stance TEXT NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaign_npcs (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, item_slug));"
            + "CREATE TABLE IF NOT EXISTS character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug));"
            + "CREATE TABLE IF NOT EXISTS crafting_projects (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL, cost_gp INTEGER NOT NULL, status TEXT NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS campaign_scheduled_sessions (campaign_id TEXT NOT NULL, id TEXT PRIMARY KEY, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, position INTEGER NOT NULL);"
            + "CREATE TABLE IF NOT EXISTS scheduled_session_agenda (session_id TEXT NOT NULL, position INTEGER NOT NULL, item TEXT NOT NULL, PRIMARY KEY (session_id, position));"
            + "CREATE TABLE IF NOT EXISTS scheduled_session_attendance (session_id TEXT NOT NULL, character_id TEXT NOT NULL, present INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (session_id, character_id));");
        ensureMemberHealthColumns();
        ensureMemberDeathSaveColumns();
        ensureMemberOwnerColumn();
        ensureMemberProgressionColumns();
        ensureMemberAbilityColumns();
        ensureMemberGoldColumn();
        ensureMemberCharacterIdScope();
        ensurePlayEventTargetColumn();
        loadStorage();
    }

    private static void ensureMemberHealthColumns() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|hp_current|")) sql("ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20;");
        if (!columns.contains("|hp_max|")) sql("ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20;");
    }

    private static void ensureMemberDeathSaveColumns() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|status|")) sql("ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious';");
        if (!columns.contains("|death_save_successes|")) sql("ALTER TABLE play_campaign_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0;");
        if (!columns.contains("|death_save_failures|")) sql("ALTER TABLE play_campaign_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0;");
    }

    private static void ensureMemberOwnerColumn() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|owner|")) {
            sql("ALTER TABLE play_campaign_members ADD COLUMN owner TEXT;");
            sql("UPDATE play_campaign_members SET owner = username WHERE owner IS NULL;");
        }
    }

    private static void ensureMemberProgressionColumns() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|level|")) sql("ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1;");
        if (!columns.contains("|con_modifier|")) sql("ALTER TABLE play_campaign_members ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0;");
    }

    private static void ensureMemberAbilityColumns() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|str_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN str_score INTEGER NOT NULL DEFAULT 10;");
        if (!columns.contains("|dex_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN dex_score INTEGER NOT NULL DEFAULT 10;");
        if (!columns.contains("|con_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN con_score INTEGER NOT NULL DEFAULT 10;");
        if (!columns.contains("|int_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN int_score INTEGER NOT NULL DEFAULT 10;");
        if (!columns.contains("|wis_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN wis_score INTEGER NOT NULL DEFAULT 10;");
        if (!columns.contains("|cha_score|")) sql("ALTER TABLE play_campaign_members ADD COLUMN cha_score INTEGER NOT NULL DEFAULT 10;");
    }

    private static void ensureMemberGoldColumn() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_members);", true);
        if (!columns.contains("|gold|")) sql("ALTER TABLE play_campaign_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10;");
    }

    private static void ensureMemberCharacterIdScope() throws IOException {
        String definition = sql("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_members';", true);
        if (!definition.contains("character_id TEXT UNIQUE")) return;
        sql("BEGIN; ALTER TABLE play_campaign_members RENAME TO play_campaign_members_legacy;"
            + "CREATE TABLE play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, owner TEXT, level INTEGER NOT NULL DEFAULT 1, con_modifier INTEGER NOT NULL DEFAULT 0, str_score INTEGER NOT NULL DEFAULT 10, dex_score INTEGER NOT NULL DEFAULT 10, con_score INTEGER NOT NULL DEFAULT 10, int_score INTEGER NOT NULL DEFAULT 10, wis_score INTEGER NOT NULL DEFAULT 10, cha_score INTEGER NOT NULL DEFAULT 10, hp_current INTEGER NOT NULL DEFAULT 20, hp_max INTEGER NOT NULL DEFAULT 20, status TEXT NOT NULL DEFAULT 'conscious', death_save_successes INTEGER NOT NULL DEFAULT 0, death_save_failures INTEGER NOT NULL DEFAULT 0, gold INTEGER NOT NULL DEFAULT 10, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id));"
            + "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, level, con_modifier, str_score, dex_score, con_score, int_score, wis_score, cha_score, hp_current, hp_max, status, death_save_successes, death_save_failures, gold, position) SELECT campaign_id, username, character_id, name, class, owner, level, con_modifier, str_score, dex_score, con_score, int_score, wis_score, cha_score, hp_current, hp_max, status, death_save_successes, death_save_failures, gold, position FROM play_campaign_members_legacy;"
            + "DROP TABLE play_campaign_members_legacy; COMMIT;");
    }

    private static void ensurePlayEventTargetColumn() throws IOException {
        String columns = sql("PRAGMA table_info(play_campaign_events);", true);
        if (!columns.contains("|target|")) sql("ALTER TABLE play_campaign_events ADD COLUMN target TEXT;");
    }

    private static synchronized void resetStorage() throws IOException {
        sql("BEGIN; " + CLEAR_STORAGE_TABLES + "DELETE FROM play_campaign_migrations; DELETE FROM play_campaign_replay_events; DELETE FROM play_campaign_rng_rolls; DELETE FROM play_campaign_rng_seeds; "
            + "INSERT OR REPLACE INTO schema_meta VALUES ('schema_version','1'); COMMIT;");
        clearCaches();
    }

    private static void saveStorage() {
        StringBuilder statement = new StringBuilder("BEGIN; ").append(CLEAR_STORAGE_TABLES).append("DELETE FROM play_campaign_migrations; DELETE FROM play_campaign_replay_events;");
        for (Map.Entry<String, User> entry : USERS.entrySet()) {
            User user = entry.getValue();
            statement.append("INSERT INTO users VALUES (").append(sqlText(entry.getKey())).append(',')
                .append(sqlText(user.role)).append(',').append(sqlText(Base64.getEncoder().encodeToString(user.passwordHash))).append(");");
        }
        for (CombatSession session : SESSIONS.values()) {
            String state = Base64.getEncoder().encodeToString(storageState(session).getBytes(StandardCharsets.UTF_8));
            statement.append("INSERT INTO combat_sessions VALUES (").append(sqlText(session.id)).append(',').append(sqlText(state)).append(");");
        }
        for (Monster monster : MONSTERS.values()) {
            statement.append("INSERT INTO monsters VALUES (").append(sqlText(monster.slug)).append(',').append(sqlText(monster.name)).append(',').append(sqlText(monster.cr)).append(',').append(monster.armorClass).append(',').append(monster.hitPoints).append(");");
            for (int i = 0; i < monster.tags.size(); i++) statement.append("INSERT INTO monster_tags VALUES (").append(sqlText(monster.slug)).append(',').append(i).append(',').append(sqlText(monster.tags.get(i))).append(");");
        }
        for (Item item : ITEMS.values()) statement.append("INSERT INTO items VALUES (").append(sqlText(item.slug)).append(',').append(sqlText(item.name)).append(',').append(sqlText(item.type)).append(',').append(sqlText(item.rarity)).append(',').append(item.costGp).append(");");
        for (PlayCampaign campaign : PLAY_CAMPAIGNS.values()) {
            statement.append("INSERT INTO play_campaigns VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.name)).append(',').append(sqlText(campaign.owner)).append(',').append(campaign.maxPlayers).append(");");
            for (Map.Entry<String, String> spectator : SPECTATOR_CAMPAIGNS.entrySet()) {
                if (spectator.getValue().equals(campaign.id)) statement.append("INSERT INTO play_campaign_spectators VALUES (").append(sqlText(spectator.getKey())).append(',').append(sqlText(campaign.id)).append(");");
            }
            if (campaign.calendar != null) statement.append("INSERT INTO play_campaign_calendars VALUES (").append(sqlText(campaign.id)).append(',').append(campaign.calendar.day).append(',').append(sqlText(campaign.calendar.season)).append(");");
            statement.append("INSERT INTO play_campaign_documents VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.story)).append(',').append(sqlText(campaign.dmNotes)).append(");");
            if (campaign.fixtureSeeded) statement.append("INSERT INTO play_campaign_fixture_seeds VALUES (").append(sqlText(campaign.id)).append(");");
            for (CampaignExport snapshot : campaign.exports) {
                statement.append("INSERT INTO play_campaign_exports VALUES (").append(sqlText(campaign.id)).append(',').append(snapshot.version).append(',').append(sqlText(snapshot.story)).append(',').append(sqlText(snapshot.status)).append(");");
            }
            for (int backupPosition = 0; backupPosition < campaign.backups.size(); backupPosition++) {
                CampaignBackup backup = campaign.backups.get(backupPosition);
                statement.append("INSERT INTO play_campaign_backups VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(backup.backupId)).append(',').append(sqlText(backup.story)).append(',').append(sqlText(backup.status)).append(',').append(backupPosition).append(");");
            }
            if (campaign.importedSnapshot != null) statement.append("INSERT INTO play_campaign_imports VALUES (").append(sqlText(campaign.id)).append(',').append(campaign.importedSnapshot.version).append(',').append(sqlText(campaign.importedSnapshot.story)).append(',').append(sqlText(campaign.importedSnapshot.status)).append(");");
            if (campaign.migratedState != null) statement.append("INSERT INTO play_campaign_migrations VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.migratedState.story)).append(',').append(sqlText(campaign.migratedState.campaignName)).append(");");
            if (campaign.sessionZero != null) {
                statement.append("INSERT INTO play_campaign_session_zero VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.sessionZero.rules)).append(',').append(sqlText(campaign.sessionZero.tone)).append(");");
                for (int i = 0; i < campaign.sessionZero.consent.size(); i++) statement.append("INSERT INTO play_campaign_session_zero_consent VALUES (").append(sqlText(campaign.id)).append(',').append(i).append(',').append(sqlText(campaign.sessionZero.consent.get(i))).append(");");
            }
            int contentPosition = 0;
            for (Content content : campaign.content.values()) {
                statement.append("INSERT INTO play_campaign_content VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(content.contentId)).append(',').append(sqlText(content.kind)).append(',').append(sqlText(content.text)).append(',').append(contentPosition++).append(");");
                for (int tagPosition = 0; tagPosition < content.tags.size(); tagPosition++) statement.append("INSERT INTO play_campaign_content_tags VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(content.contentId)).append(',').append(tagPosition).append(',').append(sqlText(content.tags.get(tagPosition))).append(");");
            }
            int notePosition = 0;
            for (Note note : campaign.notes.values()) statement.append("INSERT INTO play_campaign_notes VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(note.noteId)).append(',').append(sqlText(note.text)).append(',').append(sqlText(note.visibility)).append(',').append(sqlText(note.owner)).append(',').append(notePosition++).append(");");
            int whisperPosition = 0;
            for (Whisper whisper : campaign.whispers.values()) statement.append("INSERT INTO play_campaign_whispers VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(whisper.whisperId)).append(',').append(sqlText(whisper.fromCharacterId)).append(',').append(sqlText(whisper.toCharacterId)).append(',').append(sqlText(whisper.text)).append(',').append(whisperPosition++).append(");");
            int searchRecordPosition = 0;
            for (SearchRecord record : campaign.searchRecords.values()) statement.append("INSERT INTO play_campaign_search_records VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(record.recordId)).append(',').append(sqlText(record.text)).append(',').append(searchRecordPosition++).append(");");
            int rateEventPosition = 0;
            for (RateEvent event : campaign.rateEvents.values()) statement.append("INSERT INTO play_campaign_rate_events VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(event.eventId)).append(',').append(sqlText(event.actor)).append(',').append(rateEventPosition++).append(");");
            statement.append("INSERT INTO play_campaign_state VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.status)).append(',')
                .append(campaign.currentActor == null ? "NULL" : sqlText(campaign.currentActor)).append(',').append(campaign.turnNumber).append(");");
            if (campaign.nextResolutionStartsParty) statement.append("INSERT INTO play_campaign_exploration_queue VALUES (").append(sqlText(campaign.id)).append(",1);");
            int recipePosition = 0;
            for (Recipe recipe : campaign.recipes.values()) {
                statement.append("INSERT INTO play_campaign_recipes VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(recipe.recipeId)).append(',').append(sqlText(recipe.name)).append(',').append(sqlText(recipe.outputItem)).append(',').append(recipe.outputQuantity).append(',').append(recipePosition++).append(");");
                int ingredientPosition = 0;
                for (Map.Entry<String, Long> ingredient : recipe.ingredients.entrySet()) statement.append("INSERT INTO play_campaign_recipe_ingredients VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(recipe.recipeId)).append(',').append(sqlText(ingredient.getKey())).append(',').append(ingredient.getValue()).append(',').append(ingredientPosition++).append(");");
            }
            int activityPosition = 0;
            for (DowntimeActivity activity : campaign.downtimeActivities.values()) {
                statement.append("INSERT INTO play_campaign_downtime_activities VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(activity.activityId)).append(',').append(sqlText(activity.name)).append(',').append(activity.cyclesRequired).append(',').append(activityPosition++).append(");");
            }
            if (campaign.currentSceneId != null) statement.append("INSERT INTO play_campaign_scene_state VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.currentSceneId)).append(");");
            int scenePosition = 0;
            for (Scene scene : campaign.scenes.values()) {
                statement.append("INSERT INTO play_campaign_scenes VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(scene.id)).append(',').append(sqlText(scene.name)).append(',').append(sqlText(scene.status)).append(',').append(scenePosition++).append(");");
            }
            int locationPosition = 0;
            for (Location location : campaign.locations.values()) {
                statement.append("INSERT INTO play_campaign_locations VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(location.id)).append(',').append(sqlText(location.name)).append(',').append(locationPosition++).append(");");
                int connectionPosition = 0;
                for (Map.Entry<String, Long> connection : location.connections.entrySet()) {
                    statement.append("INSERT INTO play_campaign_location_connections VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(location.id)).append(',').append(sqlText(connection.getKey())).append(',').append(connection.getValue()).append(',').append(connectionPosition++).append(");");
                }
            }
            if (campaign.nudgeCount > 0) statement.append("INSERT INTO play_campaign_nudges VALUES (").append(sqlText(campaign.id)).append(',').append(campaign.nudgeCount).append(");");
            if (campaign.currencyTransferId > 0) statement.append("INSERT INTO play_campaign_currency VALUES (").append(sqlText(campaign.id)).append(',').append(campaign.currencyTransferId).append(");");
            for (TransactionalTransfer transfer : campaign.transactionalTransfers) statement.append("INSERT INTO play_campaign_transactional_transfers VALUES (").append(sqlText(campaign.id)).append(',').append(transfer.sequence).append(',').append(sqlText(transfer.fromCharacterId)).append(',').append(sqlText(transfer.toCharacterId)).append(',').append(transfer.amount).append(',').append(transfer.fromGold).append(',').append(transfer.toGold).append(");");
            int invitationPosition = 0;
            for (Invitation invitation : campaign.invitations.values()) {
                statement.append("INSERT INTO play_campaign_invitations VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(sqlText(invitation.invitationId)).append(',').append(sqlText(invitation.username)).append(',')
                    .append(sqlText(invitation.characterId)).append(',').append(sqlText(invitation.status)).append(',')
                    .append(invitationPosition++).append(");");
            }
            for (Delegation delegation : campaign.delegations.values()) statement.append("INSERT INTO play_campaign_delegations VALUES (")
                .append(sqlText(campaign.id)).append(',').append(sqlText(delegation.username)).append(',').append(delegation.active ? 1 : 0).append(");");
            for (int auditPosition = 0; auditPosition < campaign.delegationAudit.size(); auditPosition++) {
                DelegationAuditEntry entry = campaign.delegationAudit.get(auditPosition);
                statement.append("INSERT INTO play_campaign_delegation_audit VALUES (").append(sqlText(campaign.id)).append(',').append(auditPosition).append(',')
                    .append(sqlText(entry.username)).append(',').append(sqlText(entry.action)).append(");");
            }
            for (AuditEvent entry : campaign.auditEvents) {
                statement.append("INSERT INTO play_campaign_audit_events VALUES (").append(sqlText(campaign.id)).append(',').append(entry.timestamp).append(',')
                    .append(sqlText(entry.kind)).append(',').append(sqlText(entry.actor)).append(',').append(sqlText(entry.role)).append(',')
                    .append(sqlText(entry.correlationId)).append(");");
            }
            for (LootRecord loot : campaign.loot.values()) {
                statement.append("INSERT INTO play_campaign_loot VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(loot.lootId)).append(',').append(sqlText(loot.itemId)).append(',').append(loot.quantity).append(',').append(sqlText(loot.status)).append(',').append(loot.recipientCharacterId == null ? "NULL" : sqlText(loot.recipientCharacterId)).append(',').append(loot.assignedVotes).append(");");
                for (Map.Entry<String, String> vote : loot.votes.entrySet()) statement.append("INSERT INTO play_campaign_loot_votes VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(loot.lootId)).append(',').append(sqlText(vote.getKey())).append(',').append(sqlText(vote.getValue())).append(");");
            }
            for (PlayNpc npc : campaign.npcs.values()) {
                statement.append("INSERT INTO play_campaign_npcs VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(npc.npcId)).append(',').append(sqlText(npc.name)).append(',').append(sqlText(npc.agenda)).append(',').append(sqlText(npc.publicStatus)).append(");");
                for (int dialoguePosition = 0; dialoguePosition < npc.dialogue.size(); dialoguePosition++) {
                    DialogueEntry entry = npc.dialogue.get(dialoguePosition);
                    statement.append("INSERT INTO play_campaign_npc_dialogue VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(npc.npcId)).append(',').append(sqlText(entry.dialogueId)).append(',').append(sqlText(entry.speaker)).append(',').append(sqlText(entry.text)).append(',').append(sqlText(entry.visibility)).append(',').append(dialoguePosition).append(");");
                }
            }
            int settlementPosition = 0;
            for (Settlement settlement : campaign.settlements.values()) {
                statement.append("INSERT INTO play_campaign_settlements VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(settlement.settlementId)).append(',').append(sqlText(settlement.name)).append(',').append(sqlText(settlement.availability)).append(',').append(settlementPosition++).append(");");
                for (int servicePosition = 0; servicePosition < settlement.services.size(); servicePosition++) statement.append("INSERT INTO play_campaign_settlement_services VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(settlement.settlementId)).append(',').append(sqlText(settlement.services.get(servicePosition))).append(',').append(servicePosition).append(");");
                for (int discoveryPosition = 0; discoveryPosition < settlement.discoveredBy.size(); discoveryPosition++) statement.append("INSERT INTO play_campaign_settlement_discoveries VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(settlement.settlementId)).append(',').append(sqlText(settlement.discoveredBy.get(discoveryPosition))).append(',').append(discoveryPosition).append(");");
                int shopPosition = 0;
                for (Shop shop : settlement.shops.values()) {
                    statement.append("INSERT INTO play_campaign_shops VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(settlement.settlementId)).append(',').append(sqlText(shop.shopId)).append(',').append(sqlText(shop.name)).append(',').append(shop.buyPrice).append(',').append(shop.sellPrice).append(',').append(shopPosition++).append(");");
                    int stockPosition = 0;
                    for (Map.Entry<String, Long> item : shop.stock.entrySet()) statement.append("INSERT INTO play_campaign_shop_stock VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(settlement.settlementId)).append(',').append(sqlText(shop.shopId)).append(',').append(sqlText(item.getKey())).append(',').append(item.getValue()).append(',').append(stockPosition++).append(");");
                }
            }
            int relationshipPosition = 0;
            for (Relationship relationship : campaign.relationships.values()) {
                statement.append("INSERT INTO play_campaign_relationships VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(sqlText(relationship.sourceId)).append(',').append(sqlText(relationship.targetId)).append(',')
                    .append(sqlText(relationship.kind)).append(',').append(relationship.score).append(',')
                    .append(relationshipPosition++).append(");");
            }
            int cluePosition = 0;
            for (Clue clue : campaign.clues.values()) {
                statement.append("INSERT INTO play_campaign_clues VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(sqlText(clue.clueId)).append(',').append(sqlText(clue.text)).append(',')
                    .append(sqlText(clue.audience)).append(',')
                    .append(clue.characterId == null ? "NULL" : sqlText(clue.characterId)).append(',')
                    .append(cluePosition++).append(");");
            }
            int questPosition = 0;
            for (PlayQuest quest : campaign.quests.values()) {
                statement.append("INSERT INTO play_campaign_quests VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(quest.questId)).append(',').append(sqlText(quest.title)).append(',').append(sqlText(quest.state)).append(',').append(questPosition++).append(");");
                for (int dependencyPosition = 0; dependencyPosition < quest.dependsOn.size(); dependencyPosition++) {
                    statement.append("INSERT INTO play_campaign_quest_dependencies VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(quest.questId)).append(',').append(sqlText(quest.dependsOn.get(dependencyPosition))).append(',').append(dependencyPosition).append(");");
                }
                if (quest.reward != null) {
                    statement.append("INSERT INTO play_campaign_quest_rewards VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(quest.questId)).append(',').append(quest.reward.xp).append(',').append(quest.reward.awarded ? 1 : 0).append(");");
                    int itemPosition = 0;
                    for (Map.Entry<String, Long> item : quest.reward.items.entrySet()) statement.append("INSERT INTO play_campaign_quest_reward_items VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(quest.questId)).append(',').append(sqlText(item.getKey())).append(',').append(item.getValue()).append(',').append(itemPosition++).append(");");
                }
            }
            int worldEventPosition = 0;
            for (WorldEvent event : campaign.worldEvents.values()) {
                statement.append("INSERT INTO play_campaign_world_events VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(sqlText(event.eventId)).append(',').append(event.turnNumber).append(',').append(sqlText(event.title)).append(',')
                    .append(sqlText(event.text)).append(',').append(event.resolution == null ? "NULL" : event.resolution.turnNumber).append(',')
                    .append(event.resolution == null ? "NULL" : sqlText(event.resolution.text)).append(',').append(worldEventPosition++).append(");");
            }
            int factionPosition = 0;
            for (PlayFaction faction : campaign.playFactions.values()) {
                statement.append("INSERT INTO play_campaign_factions VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(faction.factionId)).append(',').append(sqlText(faction.name)).append(',').append(factionPosition++).append(");");
            }
            for (int reputationPosition = 0; reputationPosition < campaign.reputationHistory.size(); reputationPosition++) {
                ReputationRecord record = campaign.reputationHistory.get(reputationPosition);
                statement.append("INSERT INTO play_campaign_reputation_history VALUES (").append(sqlText(campaign.id)).append(',').append(reputationPosition).append(',').append(sqlText(record.factionId)).append(',').append(sqlText(record.characterId)).append(',').append(record.reputation).append(',').append(record.delta).append(',').append(sqlText(record.reason)).append(");");
            }
            int position = 0;
            for (PartyMember member : campaign.members.values()) {
                statement.append("INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, level, con_modifier, str_score, dex_score, con_score, int_score, wis_score, cha_score, hp_current, hp_max, status, death_save_successes, death_save_failures, gold, position) VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.username)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(member.name)).append(',').append(sqlText(member.characterClass)).append(',').append(member.owner == null ? "NULL" : sqlText(member.owner)).append(',').append(member.level).append(',').append(member.conModifier).append(',').append(member.strength).append(',').append(member.dexterity).append(',').append(member.constitution).append(',').append(member.intelligence).append(',').append(member.wisdom).append(',').append(member.charisma).append(',').append(member.hpCurrent).append(',').append(member.hpMax).append(',').append(sqlText(member.status)).append(',').append(member.deathSaveSuccesses).append(',').append(member.deathSaveFailures).append(',').append(member.gold).append(',').append(position++).append(");");
                int spellPosition = 0;
                for (Spell spell : member.spells.values()) {
                    statement.append("INSERT INTO play_character_spells VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(spell.spellId)).append(',').append(sqlText(spell.name)).append(',').append(spell.level).append(',').append(spellPosition++).append(");");
                }
                for (int preparedPosition = 0; preparedPosition < member.preparedSpellIds.size(); preparedPosition++) {
                    statement.append("INSERT INTO play_character_prepared_spells VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(member.preparedSpellIds.get(preparedPosition))).append(',').append(preparedPosition).append(");");
                }
                for (CastEvent cast : member.casts) {
                    statement.append("INSERT INTO play_character_casts VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(cast.sequence).append(',').append(sqlText(cast.spellId)).append(',').append(sqlText(cast.target)).append(',').append(cast.slotLevel).append(',').append(cast.slotsRemaining).append(");");
                }
                if (member.concentration != null) {
                    Concentration concentration = member.concentration;
                    statement.append("INSERT INTO play_character_concentrations VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(concentration.spellId)).append(',').append(sqlText(concentration.target)).append(',').append(concentration.remainingTurns).append(");");
                }
                for (Map.Entry<String, Long> item : member.inventory.entrySet()) {
                    statement.append("INSERT INTO play_character_inventory VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(item.getKey())).append(',').append(item.getValue()).append(");");
                }
                for (QuestRewardGrant grant : member.questRewardGrants.values()) statement.append("INSERT INTO play_campaign_quest_reward_grants VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(grant.questId)).append(',').append(sqlText(member.characterId)).append(',').append(grant.xp).append(");");
                for (Map.Entry<String, Equipment> entry : member.equipment.entrySet()) {
                    Equipment equipment = entry.getValue();
                    statement.append("INSERT INTO play_character_equipment VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(entry.getKey())).append(',').append(sqlText(equipment.itemId)).append(',').append(equipment.attuned ? 1 : 0).append(");");
                }
                for (DowntimeAllocation allocation : member.downtimeAllocations.values()) {
                    statement.append("INSERT INTO play_character_downtime_allocations VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(member.characterId)).append(',').append(sqlText(allocation.activityId)).append(',').append(allocation.cyclesCompleted).append(',').append(allocation.completions).append(");");
                }
            }
            for (PlayEvent event : campaign.events) {
                statement.append("INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, text, target) VALUES (").append(sqlText(campaign.id)).append(',').append(event.sequence).append(',').append(sqlText(event.kind)).append(',').append(sqlText(event.actor)).append(',')
                    .append(event.type == null ? "NULL" : sqlText(event.type)).append(',').append(sqlText(event.text)).append(',')
                    .append(event.target == null ? "NULL" : sqlText(event.target)).append(");");
                if (event.kind.equals("narration")) statement.append("INSERT INTO play_campaign_narrations VALUES (").append(sqlText(campaign.id)).append(',').append(event.sequence).append(',').append(sqlText(event.text)).append(");");
            }
            for (FeedEvent event : campaign.feedEvents) {
                statement.append("INSERT INTO play_campaign_feed_events VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(event.sequence).append(',').append(sqlText(event.eventId)).append(',').append(sqlText(event.text)).append(");");
            }
            for (ProjectionEvent event : campaign.projectionEvents) {
                statement.append("INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (")
                    .append(sqlText(campaign.id)).append(',').append(event.sequence).append(',').append(sqlText(event.eventId)).append(',')
                    .append(sqlText(event.kind)).append(',').append(event.value == null ? "NULL" : sqlText(event.value)).append(");");
            }
            for (ReplayEvent event : campaign.replayEvents) {
                statement.append("INSERT INTO play_campaign_replay_events VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(event.sequence).append(',').append(sqlText(event.eventId)).append(',').append(sqlText(event.text)).append(");");
            }
            for (ModerationReport report : campaign.moderationReports.values()) {
                statement.append("INSERT INTO play_campaign_moderation_reports VALUES (").append(sqlText(campaign.id)).append(',')
                    .append(report.sequence).append(',').append(sqlText(report.reportId)).append(',').append(sqlText(report.targetId)).append(',')
                    .append(sqlText(report.reason)).append(',').append(sqlText(report.status)).append(',').append(sqlText(report.reporter)).append(',')
                    .append(report.action == null ? "NULL" : sqlText(report.action)).append(',')
                    .append(report.note == null ? "NULL" : sqlText(report.note)).append(',')
                    .append(report.resolver == null ? "NULL" : sqlText(report.resolver)).append(");");
            }
            for (IdempotentEvent event : campaign.idempotentEvents) {
                statement.append("INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (")
                    .append(sqlText(campaign.id)).append(',').append(event.sequence).append(',').append(sqlText(event.eventId)).append(',')
                    .append(sqlText(event.value)).append(',').append(sqlText(event.idempotencyKey)).append(");");
            }
            if (campaign.safeCurrentTurn != 1) statement.append("INSERT INTO play_campaign_safe_turn_state VALUES (")
                .append(sqlText(campaign.id)).append(',').append(campaign.safeCurrentTurn).append(");");
            for (SafeTurn turn : campaign.safeTurns) statement.append("INSERT INTO play_campaign_safe_turns VALUES (")
                .append(sqlText(campaign.id)).append(',').append(turn.acceptedTurn).append(',').append(sqlText(turn.submissionId)).append(',')
                .append(sqlText(turn.action)).append(',').append(turn.nextTurn).append(");");
        }
        for (Encounter encounter : ENCOUNTERS.values()) {
            statement.append("INSERT INTO play_campaign_encounters VALUES (").append(sqlText(encounter.id)).append(',')
                .append(sqlText(encounter.campaignId)).append(',').append(sqlText(encounter.name)).append(',').append(sqlText(encounter.status)).append(");");
            if (encounter.reward != null) {
                statement.append("INSERT INTO play_campaign_encounter_rewards VALUES (").append(sqlText(encounter.id)).append(',')
                    .append(encounter.reward.xp).append(");");
                for (int lootPosition = 0; lootPosition < encounter.reward.loot.size(); lootPosition++) {
                    Loot item = encounter.reward.loot.get(lootPosition);
                    statement.append("INSERT INTO play_campaign_encounter_reward_loot VALUES (").append(sqlText(encounter.id)).append(',')
                        .append(lootPosition).append(',').append(sqlText(item.slug)).append(',').append(item.quantity).append(");");
                }
            }
            statement.append("INSERT INTO play_campaign_encounter_turns VALUES (").append(sqlText(encounter.id)).append(',')
                .append(encounter.round).append(',').append(encounter.turnIndex).append(");");
            if (encounter.turnOrder != null) {
                for (int orderPosition = 0; orderPosition < encounter.turnOrder.size(); orderPosition++) {
                    statement.append("INSERT INTO play_campaign_encounter_order VALUES (").append(sqlText(encounter.id)).append(',')
                        .append(orderPosition).append(',').append(sqlText(encounter.turnOrder.get(orderPosition))).append(");");
                }
            }
            int position = 0;
            for (EncounterMonster monster : encounter.monsters.values()) {
                statement.append("INSERT INTO play_campaign_encounter_monsters VALUES (").append(sqlText(encounter.id)).append(',')
                    .append(sqlText(monster.id)).append(',').append(sqlText(monster.name)).append(',').append(monster.hpMax).append(',')
                    .append(monster.hpCurrent).append(',').append(monster.initiative).append(',').append(position++).append(");");
            }
            position = 0;
            for (EncounterCombatant combatant : encounter.combatants.values()) {
                statement.append("INSERT INTO play_campaign_encounter_combatants VALUES (").append(sqlText(encounter.id)).append(',')
                    .append(sqlText(combatant.username)).append(',').append(sqlText(combatant.characterId)).append(',')
                    .append(sqlText(combatant.name)).append(',').append(combatant.initiative).append(',').append(position++).append(");");
            }
            for (Map.Entry<String, List<Condition>> entry : encounter.conditions.entrySet()) {
                int conditionPosition = 0;
                for (Condition condition : entry.getValue()) {
                    statement.append("INSERT INTO play_campaign_encounter_conditions VALUES (").append(sqlText(encounter.id)).append(',')
                        .append(sqlText(entry.getKey())).append(',').append(sqlText(condition.condition)).append(',')
                        .append(condition.remainingRounds).append(',').append(conditionPosition++).append(");");
                }
            }
        }
        for (Campaign campaign : CAMPAIGNS.values()) {
            statement.append("INSERT INTO campaigns VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(campaign.name)).append(',').append(sqlText(campaign.dm)).append(");");
            int position = 0;
            for (CampaignCharacter character : campaign.characters.values()) {
                statement.append("INSERT INTO campaign_characters VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(character.id)).append(',').append(sqlText(character.name)).append(',').append(character.level).append(',').append(sqlText(character.characterClass)).append(',').append(position++).append(");");
            }
            position = 0;
            for (CampaignEvent event : campaign.events.values()) {
                statement.append("INSERT INTO campaign_events VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(event.id)).append(',').append(sqlText(event.kind)).append(',').append(sqlText(event.summary)).append(',').append(position++).append(");");
            }
            position = 0;
            for (Quest quest : campaign.quests.values()) {
                statement.append("INSERT INTO campaign_quests VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(quest.id)).append(',').append(sqlText(quest.title)).append(',').append(sqlText(quest.status)).append(',').append(position++).append(");");
                int milestonePosition = 0;
                for (Map.Entry<String, Boolean> milestone : quest.milestones.entrySet()) {
                    statement.append("INSERT INTO quest_milestones VALUES (").append(sqlText(quest.id)).append(',').append(milestonePosition++).append(',').append(sqlText(milestone.getKey())).append(',').append(milestone.getValue() ? 1 : 0).append(");");
                }
            }
            position = 0;
            for (Faction faction : campaign.factions.values()) {
                statement.append("INSERT INTO campaign_factions VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(faction.id)).append(',').append(sqlText(faction.name)).append(',').append(sqlText(faction.stance)).append(',').append(position++).append(");");
            }
            position = 0;
            for (Npc npc : campaign.npcs.values()) {
                statement.append("INSERT INTO campaign_npcs VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(npc.id)).append(',').append(sqlText(npc.name)).append(',').append(sqlText(npc.factionId)).append(',').append(npc.disposition).append(',').append(position++).append(");");
            }
            position = 0;
            for (Map.Entry<String, Long> item : campaign.partyInventory.entrySet()) {
                statement.append("INSERT INTO campaign_inventory VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(item.getKey())).append(',').append(item.getValue()).append(',').append(position++).append(");");
            }
            position = 0;
            for (Map.Entry<String, Map<String, Long>> character : campaign.equipment.entrySet()) {
                for (Map.Entry<String, Long> item : character.getValue().entrySet()) {
                    statement.append("INSERT INTO character_equipment VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(character.getKey())).append(',').append(sqlText(item.getKey())).append(',').append(item.getValue()).append(',').append(position++).append(");");
                }
            }
            position = 0;
            for (CraftingProject project : campaign.craftingProjects.values()) {
                statement.append("INSERT INTO crafting_projects VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(project.id)).append(',').append(sqlText(project.characterId)).append(',').append(sqlText(project.itemSlug)).append(',').append(project.daysRequired).append(',').append(project.daysCompleted).append(',').append(project.costGp).append(',').append(sqlText(project.status)).append(',').append(position++).append(");");
            }
            position = 0;
            for (ScheduledSession session : campaign.scheduledSessions.values()) {
                statement.append("INSERT INTO campaign_scheduled_sessions VALUES (").append(sqlText(campaign.id)).append(',').append(sqlText(session.id)).append(',').append(sqlText(session.startsAt)).append(',').append(session.durationMinutes).append(',').append(position++).append(");");
                for (int i = 0; i < session.agenda.size(); i++) statement.append("INSERT INTO scheduled_session_agenda VALUES (").append(sqlText(session.id)).append(',').append(i).append(',').append(sqlText(session.agenda.get(i))).append(");");
                int attendancePosition = 0;
                for (Map.Entry<String, Boolean> attendance : session.attendance.entrySet()) statement.append("INSERT INTO scheduled_session_attendance VALUES (").append(sqlText(session.id)).append(',').append(sqlText(attendance.getKey())).append(',').append(attendance.getValue() ? 1 : 0).append(',').append(attendancePosition++).append(");");
            }
        }
        statement.append("COMMIT;");
        try { sql(statement.toString()); } catch (IOException e) { throw new IllegalStateException("storage unavailable", e); }
    }

    private static void loadStorage() throws IOException {
        clearCaches();
        for (String line : sql("SELECT username || char(31) || role || char(31) || password_hash FROM users;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 3) USERS.put(fields[0], new User(fields[0], fields[1], Base64.getDecoder().decode(fields[2])));
        }
        for (String line : sql("SELECT state FROM combat_sessions;", true).split("\\R")) {
            if (!line.isEmpty()) restoreSession(new String(Base64.getDecoder().decode(line), StandardCharsets.UTF_8));
        }
        Map<String, List<String>> tags = new LinkedHashMap<>();
        for (String line : sql("SELECT monster_slug || char(31) || tag FROM monster_tags ORDER BY monster_slug, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 2) tags.computeIfAbsent(fields[0], unused -> new ArrayList<>()).add(fields[1]);
        }
        for (String line : sql("SELECT slug || char(31) || name || char(31) || cr || char(31) || armor_class || char(31) || hit_points FROM monsters;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 5) MONSTERS.put(fields[0], new Monster(fields[0], fields[1], fields[2], Long.parseLong(fields[3]), Long.parseLong(fields[4]), tags.getOrDefault(fields[0], List.of())));
        }
        for (String line : sql("SELECT slug || char(31) || name || char(31) || type || char(31) || rarity || char(31) || cost_gp FROM items;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 5) ITEMS.put(fields[0], new Item(fields[0], fields[1], fields[2], fields[3], Long.parseLong(fields[4])));
        }
        for (String line : sql("SELECT id || char(31) || name || char(31) || owner || char(31) || max_players FROM play_campaigns;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 4) PLAY_CAMPAIGNS.put(fields[0], new PlayCampaign(fields[0], fields[1], fields[2], Long.parseLong(fields[3])));
        }
        for (String line : sql("SELECT spectator_id || char(31) || campaign_id FROM play_campaign_spectators;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 2 && PLAY_CAMPAIGNS.containsKey(fields[1])) SPECTATOR_CAMPAIGNS.put(fields[0], fields[1]);
        }
        for (String campaignId : sql("SELECT campaign_id FROM play_campaign_fixture_seeds;", true).split("\\R")) {
            PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
            if (campaign != null) campaign.fixtureSeeded = true;
        }
        for (String line : sql("SELECT campaign_id || char(31) || seed FROM play_campaign_rng_seeds;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 2 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.rngSeed = fields[1];
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || roll_id || char(31) || sides || char(31) || result FROM play_campaign_rng_rolls ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                RngRoll roll = new RngRoll(fields[2], Long.parseLong(fields[3]), Long.parseLong(fields[4]), Long.parseLong(fields[1]));
                campaign.rngRolls.add(roll);
                campaign.rngRollsById.put(roll.rollId, roll);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || report_id || char(31) || target_id || char(31) || reason || char(31) || status || char(31) || reporter || char(31) || COALESCE(action, '') || char(31) || COALESCE(note, '') || char(31) || COALESCE(resolver, '') FROM play_campaign_moderation_reports ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 10 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                ModerationReport report = new ModerationReport(fields[2], fields[3], fields[4], fields[6], Long.parseLong(fields[1]));
                report.status = fields[5];
                report.action = fields[7].isEmpty() ? null : fields[7];
                report.note = fields[8].isEmpty() ? null : fields[8];
                report.resolver = fields[9].isEmpty() ? null : fields[9];
                campaign.moderationReports.put(report.reportId, report);
            }
        }
        Map<String, List<String>> sessionZeroConsent = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || consent FROM play_campaign_session_zero_consent ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 2) sessionZeroConsent.computeIfAbsent(fields[0], unused -> new ArrayList<>()).add(fields[1]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || rules || char(31) || tone FROM play_campaign_session_zero;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.sessionZero = new SessionZero(fields[1], fields[2], sessionZeroConsent.getOrDefault(fields[0], List.of()));
        }
        Map<String, List<String>> contentTags = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || content_id || char(31) || tag FROM play_campaign_content_tags ORDER BY campaign_id, content_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 3) contentTags.computeIfAbsent(fields[0] + "\\u0000" + fields[1], unused -> new ArrayList<>()).add(fields[2]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || content_id || char(31) || kind || char(31) || text FROM play_campaign_content ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.content.put(fields[1], new Content(fields[1], fields[2], fields[3], contentTags.getOrDefault(fields[0] + "\\u0000" + fields[1], List.of())));
        }
        for (String line : sql("SELECT campaign_id || char(31) || note_id || char(31) || text || char(31) || visibility || char(31) || owner FROM play_campaign_notes ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue; String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.notes.put(fields[1], new Note(fields[1], fields[2], fields[3], fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || whisper_id || char(31) || from_character_id || char(31) || to_character_id || char(31) || text FROM play_campaign_whispers ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue; String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.whispers.put(fields[1], new Whisper(fields[1], fields[2], fields[3], fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || record_id || char(31) || text FROM play_campaign_search_records ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue; String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.searchRecords.put(fields[1], new SearchRecord(fields[1], fields[2]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || event_id || char(31) || actor FROM play_campaign_rate_events ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue; String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.rateEvents.put(fields[1], new RateEvent(fields[1], fields[2]));
        }
        Map<String, Recipe> recipes = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || recipe_id || char(31) || name || char(31) || output_item || char(31) || output_quantity FROM play_campaign_recipes ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Recipe recipe = new Recipe(fields[1], fields[2], Map.of(), fields[3], Long.parseLong(fields[4]));
                campaign.recipes.put(recipe.recipeId, recipe);
                recipes.put(fields[0] + "\\u0000" + fields[1], recipe);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || recipe_id || char(31) || item_id || char(31) || quantity FROM play_campaign_recipe_ingredients ORDER BY campaign_id, recipe_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Recipe recipe = fields.length == 4 ? recipes.get(fields[0] + "\\u0000" + fields[1]) : null;
            if (recipe != null) recipe.ingredients.put(fields[2], Long.parseLong(fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || activity_id || char(31) || name || char(31) || cycles_required FROM play_campaign_downtime_activities ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.downtimeActivities.put(fields[1], new DowntimeActivity(fields[1], fields[2], Long.parseLong(fields[3])));
        }
        for (String line : sql("SELECT campaign_id || char(31) || day || char(31) || season FROM play_campaign_calendars;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.calendar = new Calendar(Long.parseLong(fields[1]), fields[2]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || npc_id || char(31) || name || char(31) || agenda || char(31) || public_status FROM play_campaign_npcs ORDER BY campaign_id, npc_id;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.npcs.put(fields[1], new PlayNpc(fields[1], fields[2], fields[3], fields[4]));
        }
        Map<String, List<String>> settlementServices = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || settlement_id || char(31) || service FROM play_campaign_settlement_services ORDER BY campaign_id, settlement_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 3) settlementServices.computeIfAbsent(fields[0] + "\\u0000" + fields[1], unused -> new ArrayList<>()).add(fields[2]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || settlement_id || char(31) || name || char(31) || availability FROM play_campaign_settlements ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.settlements.put(fields[1], new Settlement(fields[1], fields[2], settlementServices.getOrDefault(fields[0] + "\\u0000" + fields[1], List.of()), fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || settlement_id || char(31) || character_id FROM play_campaign_settlement_discoveries ORDER BY campaign_id, settlement_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            Settlement settlement = campaign == null ? null : campaign.settlements.get(fields[1]);
            if (settlement != null) settlement.discoveredBy.add(fields[2]);
        }
        Map<String, Shop> shops = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || settlement_id || char(31) || shop_id || char(31) || name || char(31) || buy_price || char(31) || sell_price FROM play_campaign_shops ORDER BY campaign_id, settlement_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 6 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            Settlement settlement = campaign == null ? null : campaign.settlements.get(fields[1]);
            if (settlement != null) {
                Shop shop = new Shop(fields[2], fields[3], Map.of(), Long.parseLong(fields[4]), Long.parseLong(fields[5]));
                settlement.shops.put(shop.shopId, shop);
                shops.put(fields[0] + "\\u0000" + fields[1] + "\\u0000" + fields[2], shop);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || settlement_id || char(31) || shop_id || char(31) || item_id || char(31) || quantity FROM play_campaign_shop_stock ORDER BY campaign_id, settlement_id, shop_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Shop shop = fields.length == 5 ? shops.get(fields[0] + "\\u0000" + fields[1] + "\\u0000" + fields[2]) : null;
            if (shop != null) shop.stock.put(fields[3], Long.parseLong(fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || npc_id || char(31) || dialogue_id || char(31) || speaker || char(31) || text || char(31) || visibility FROM play_campaign_npc_dialogue ORDER BY campaign_id, npc_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 6 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            PlayNpc npc = campaign == null ? null : campaign.npcs.get(fields[1]);
            if (npc != null) npc.dialogue.add(new DialogueEntry(fields[2], fields[3], fields[4], fields[5]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || source_id || char(31) || target_id || char(31) || kind || char(31) || score FROM play_campaign_relationships ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Relationship relationship = new Relationship(fields[1], fields[2], fields[3], Long.parseLong(fields[4]));
                campaign.relationships.put(relationshipKey(relationship.sourceId, relationship.targetId, relationship.kind), relationship);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || clue_id || char(31) || text || char(31) || audience || char(31) || COALESCE(character_id, '') FROM play_campaign_clues ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.clues.put(fields[1], new Clue(fields[1], fields[2], fields[3], fields[4].isEmpty() ? null : fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || quest_id || char(31) || title || char(31) || state FROM play_campaign_quests ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                PlayQuest quest = new PlayQuest(fields[1], fields[2], List.of());
                quest.state = fields[3];
                campaign.quests.put(fields[1], quest);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || quest_id || char(31) || dependency_id FROM play_campaign_quest_dependencies ORDER BY campaign_id, quest_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            PlayQuest quest = campaign == null ? null : campaign.quests.get(fields[1]);
            if (quest != null) quest.dependsOn.add(fields[2]);
        }
        Map<String, Map<String, Long>> rewardItems = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || quest_id || char(31) || item_id || char(31) || quantity FROM play_campaign_quest_reward_items ORDER BY campaign_id, quest_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 4) rewardItems.computeIfAbsent(fields[0] + "\\u0000" + fields[1], unused -> new LinkedHashMap<>()).put(fields[2], Long.parseLong(fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || quest_id || char(31) || xp || char(31) || awarded FROM play_campaign_quest_rewards;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            PlayQuest quest = campaign == null ? null : campaign.quests.get(fields[1]);
            if (quest != null) { quest.reward = new QuestReward(Long.parseLong(fields[2]), rewardItems.getOrDefault(fields[0] + "\\u0000" + fields[1], Map.of())); quest.reward.awarded = !fields[3].equals("0"); }
        }
        for (String line : sql("SELECT campaign_id || char(31) || event_id || char(31) || turn_number || char(31) || title || char(31) || text || char(31) || COALESCE(resolution_turn_number, '') || char(31) || COALESCE(resolution_text, '') FROM play_campaign_world_events ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 7 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                WorldEvent event = new WorldEvent(fields[1], Long.parseLong(fields[2]), fields[3], fields[4]);
                if (!fields[5].isEmpty()) event.resolution = new WorldEventResolution(Long.parseLong(fields[5]), fields[6]);
                campaign.worldEvents.put(event.eventId, event);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || faction_id || char(31) || name FROM play_campaign_factions ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.playFactions.put(fields[1], new PlayFaction(fields[1], fields[2]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || faction_id || char(31) || character_id || char(31) || reputation || char(31) || delta || char(31) || reason FROM play_campaign_reputation_history ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 6 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.reputationHistory.add(new ReputationRecord(fields[1], fields[2], Long.parseLong(fields[3]), Long.parseLong(fields[4]), fields[5]));
        }
        for (String line : sql("SELECT id || char(31) || campaign_id || char(31) || name || char(31) || status FROM play_campaign_encounters;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[1]) : null;
            if (campaign != null) {
                Encounter encounter = new Encounter(fields[0], fields[1], fields[2]);
                encounter.status = fields[3];
                ENCOUNTERS.put(encounter.id, encounter);
                if (encounter.status.equals("active") && campaign.activeEncounterId == null) campaign.activeEncounterId = encounter.id;
            }
        }
        Map<String, List<Loot>> rewardLoot = new LinkedHashMap<>();
        for (String line : sql("SELECT encounter_id || char(31) || slug || char(31) || quantity FROM play_campaign_encounter_reward_loot ORDER BY encounter_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 3) rewardLoot.computeIfAbsent(fields[0], unused -> new ArrayList<>()).add(new Loot(fields[1], Long.parseLong(fields[2])));
        }
        for (String line : sql("SELECT encounter_id || char(31) || xp FROM play_campaign_encounter_rewards;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 2 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null) encounter.reward = new EncounterReward(Long.parseLong(fields[1]), rewardLoot.getOrDefault(fields[0], List.of()));
        }
        for (String line : sql("SELECT encounter_id || char(31) || round || char(31) || turn_index FROM play_campaign_encounter_turns;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 3 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null) { encounter.round = Long.parseLong(fields[1]); encounter.turnIndex = Long.parseLong(fields[2]); }
        }
        for (String line : sql("SELECT encounter_id || char(31) || monster_id || char(31) || name || char(31) || hp_max || char(31) || hp_current || char(31) || initiative FROM play_campaign_encounter_monsters ORDER BY encounter_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 6 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null) { encounter.monsters.put(fields[1], new EncounterMonster(fields[1], fields[2], Long.parseLong(fields[3]), Long.parseLong(fields[4]), Long.parseLong(fields[5]))); encounter.conditions.put(fields[1], new ArrayList<>()); }
        }
        for (String line : sql("SELECT encounter_id || char(31) || username || char(31) || character_id || char(31) || name || char(31) || initiative FROM play_campaign_encounter_combatants ORDER BY encounter_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 5 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null) { encounter.combatants.put(fields[1], new EncounterCombatant(fields[1], fields[2], fields[3], Long.parseLong(fields[4]))); encounter.conditions.put(fields[1], new ArrayList<>()); }
        }
        for (String line : sql("SELECT encounter_id || char(31) || entry_key FROM play_campaign_encounter_order ORDER BY encounter_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 2 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null) {
                if (encounter.turnOrder == null) encounter.turnOrder = new ArrayList<>();
                encounter.turnOrder.add(fields[1]);
            }
        }
        for (String line : sql("SELECT encounter_id || char(31) || target || char(31) || condition || char(31) || remaining_rounds FROM play_campaign_encounter_conditions ORDER BY encounter_id, target, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Encounter encounter = fields.length == 4 ? ENCOUNTERS.get(fields[0]) : null;
            if (encounter != null && encounter.conditions.containsKey(fields[1])) encounter.conditions.get(fields[1]).add(new Condition(fields[2], Long.parseLong(fields[3])));
        }
        for (String line : sql("SELECT campaign_id || char(31) || story || char(31) || dm_notes FROM play_campaign_documents;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) { campaign.story = fields[1]; campaign.dmNotes = fields[2]; }
        }
        for (String line : sql("SELECT campaign_id || char(31) || status || char(31) || COALESCE(current_actor, '') || char(31) || COALESCE(turn_number, 0) FROM play_campaign_state;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                campaign.status = fields[1];
                campaign.currentActor = fields[2].isEmpty() ? null : fields[2];
                campaign.turnNumber = Long.parseLong(fields[3]);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || version || char(31) || story || char(31) || status FROM play_campaign_exports ORDER BY campaign_id, version;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.exports.add(new CampaignExport(Long.parseLong(fields[1]), fields[2], fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || backup_id || char(31) || story || char(31) || status FROM play_campaign_backups ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.backups.add(new CampaignBackup(fields[1], fields[2], fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || version || char(31) || story || char(31) || status FROM play_campaign_imports;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.importedSnapshot = new CampaignImport(Long.parseLong(fields[1]), fields[2], fields[3]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || story || char(31) || campaign_name FROM play_campaign_migrations;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.migratedState = new MigratedState(fields[1], fields[2]);
        }
        for (String campaignId : sql("SELECT campaign_id FROM play_campaign_exploration_queue WHERE starts_party = 1;", true).split("\\R")) {
            PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
            if (campaign != null) campaign.nextResolutionStartsParty = true;
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || name || char(31) || status FROM play_campaign_scenes ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Scene scene = new Scene(fields[1], fields[2]);
                scene.status = fields[3];
                campaign.scenes.put(scene.id, scene);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || COALESCE(current_scene_id, '') FROM play_campaign_scene_state;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 2 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.currentSceneId = fields[1].isEmpty() ? null : fields[1];
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || name FROM play_campaign_locations ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.locations.put(fields[1], new Location(fields[1], fields[2]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || from_id || char(31) || to_id || char(31) || travel_turns FROM play_campaign_location_connections ORDER BY campaign_id, from_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            Location from = campaign == null ? null : campaign.locations.get(fields[1]);
            if (from != null && campaign.locations.containsKey(fields[2])) from.connections.put(fields[2], Long.parseLong(fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || nudge_count FROM play_campaign_nudges;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 2 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.nudgeCount = Long.parseLong(fields[1]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || transfer_id FROM play_campaign_currency;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 2 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.currencyTransferId = Long.parseLong(fields[1]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || from_character_id || char(31) || to_character_id || char(31) || amount || char(31) || from_gold || char(31) || to_gold FROM play_campaign_transactional_transfers ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 7 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                long sequence = Long.parseLong(fields[1]);
                campaign.transactionalTransfers.add(new TransactionalTransfer(fields[2], fields[3], Long.parseLong(fields[4]), Long.parseLong(fields[5]), Long.parseLong(fields[6]), sequence));
                campaign.transactionalTransferSequence = Math.max(campaign.transactionalTransferSequence, sequence);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || loot_id || char(31) || item_id || char(31) || quantity || char(31) || status || char(31) || COALESCE(recipient_character_id, '') || char(31) || assigned_votes FROM play_campaign_loot ORDER BY campaign_id, loot_id;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 7 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                LootRecord loot = new LootRecord(fields[1], fields[2], Long.parseLong(fields[3]));
                loot.status = fields[4]; loot.recipientCharacterId = fields[5].isEmpty() ? null : fields[5]; loot.assignedVotes = Long.parseLong(fields[6]);
                campaign.loot.put(loot.lootId, loot);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || loot_id || char(31) || voter || char(31) || recipient_character_id FROM play_campaign_loot_votes ORDER BY campaign_id, loot_id, voter;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            LootRecord loot = campaign == null ? null : campaign.loot.get(fields[1]);
            if (loot != null) loot.votes.put(fields[2], fields[3]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || username || char(31) || character_id || char(31) || name || char(31) || class || char(31) || COALESCE(owner, '') || char(31) || level || char(31) || con_modifier || char(31) || str_score || char(31) || dex_score || char(31) || con_score || char(31) || int_score || char(31) || wis_score || char(31) || cha_score || char(31) || hp_current || char(31) || hp_max || char(31) || status || char(31) || death_save_successes || char(31) || death_save_failures || char(31) || gold FROM play_campaign_members ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 20 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                PartyMember member = new PartyMember(fields[1], fields[2], fields[3], fields[4], fields[5].isEmpty() ? null : fields[5], Long.parseLong(fields[6]), Long.parseLong(fields[7]), Long.parseLong(fields[8]), Long.parseLong(fields[9]), Long.parseLong(fields[10]), Long.parseLong(fields[11]), Long.parseLong(fields[12]), Long.parseLong(fields[13]), Long.parseLong(fields[14]), Long.parseLong(fields[15]), fields[16], Long.parseLong(fields[17]), Long.parseLong(fields[18]));
                member.gold = Long.parseLong(fields[19]);
                campaign.members.put(fields[1], member);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || invitation_id || char(31) || username || char(31) || character_id || char(31) || status FROM play_campaign_invitations ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Invitation invitation = new Invitation(fields[1], fields[2], fields[3]);
                invitation.status = fields[4];
                campaign.invitations.put(invitation.invitationId, invitation);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || username || char(31) || active FROM play_campaign_delegations ORDER BY campaign_id, username;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.delegations.put(fields[1], new Delegation(fields[1], List.of("narrate"), fields[2].equals("1")));
        }
        for (String line : sql("SELECT campaign_id || char(31) || username || char(31) || action FROM play_campaign_delegation_audit ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.delegationAudit.add(new DelegationAuditEntry(fields[1], fields[2], List.of("narrate")));
        }
        for (String line : sql("SELECT campaign_id || char(31) || timestamp || char(31) || kind || char(31) || actor || char(31) || role || char(31) || correlation_id FROM play_campaign_audit_events ORDER BY campaign_id, timestamp;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 6 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                AuditEvent entry = new AuditEvent(fields[2], fields[3], fields[4], Long.parseLong(fields[1]), fields[5]);
                campaign.auditEvents.add(entry);
                campaign.auditCorrelationIds.put(entry.correlationId, entry);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || spell_id || char(31) || name || char(31) || level FROM play_character_spells ORDER BY campaign_id, character_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).spells.put(fields[2], new Spell(fields[2], fields[3], Long.parseLong(fields[4]))); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || spell_id FROM play_character_prepared_spells ORDER BY campaign_id, character_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).preparedSpellIds.add(fields[2]); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || sequence || char(31) || spell_id || char(31) || target || char(31) || slot_level || char(31) || slots_remaining FROM play_character_casts ORDER BY campaign_id, character_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 7 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).casts.add(new CastEvent(fields[3], fields[4], Long.parseLong(fields[5]), Long.parseLong(fields[6]), Long.parseLong(fields[2]))); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || spell_id || char(31) || target || char(31) || remaining_turns FROM play_character_concentrations;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).concentration = new Concentration(fields[2], fields[3], Long.parseLong(fields[4])); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || item_id || char(31) || quantity FROM play_character_inventory ORDER BY campaign_id, character_id, item_id;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).inventory.put(fields[2], Long.parseLong(fields[3])); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || activity_id || char(31) || cycles_completed || char(31) || completions FROM play_character_downtime_allocations ORDER BY campaign_id, character_id, activity_id;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null && campaign.downtimeActivities.containsKey(fields[2])) {
                try {
                    DowntimeAllocation allocation = new DowntimeAllocation(fields[1], fields[2]);
                    allocation.cyclesCompleted = Long.parseLong(fields[3]);
                    allocation.completions = Long.parseLong(fields[4]);
                    memberByCharacterId(campaign, fields[1]).downtimeAllocations.put(fields[2], allocation);
                } catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || quest_id || char(31) || character_id || char(31) || xp FROM play_campaign_quest_reward_grants ORDER BY campaign_id, quest_id, character_id;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            PlayQuest quest = campaign == null ? null : campaign.quests.get(fields[1]);
            if (quest != null) {
                try { memberByCharacterId(campaign, fields[2]).questRewardGrants.put(fields[1], new QuestRewardGrant(fields[1], Long.parseLong(fields[3]), quest.reward == null ? Map.of() : quest.reward.items)); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || slot || char(31) || item_id || char(31) || attuned FROM play_character_equipment ORDER BY campaign_id, character_id, slot;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                try { memberByCharacterId(campaign, fields[1]).equipment.put(fields[2], new Equipment(fields[3], !fields[4].equals("0"))); }
                catch (UnknownRecord ignored) { }
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || kind || char(31) || actor || char(31) || COALESCE(type, '') || char(31) || text || char(31) || COALESCE(target, '') FROM play_campaign_events ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 7 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.events.add(new PlayEvent(Long.parseLong(fields[1]), fields[2], fields[3], fields[4].isEmpty() ? null : fields[4], fields[5], fields[6].isEmpty() ? null : fields[6]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || event_id || char(31) || text FROM play_campaign_feed_events ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                FeedEvent event = new FeedEvent(fields[2], fields[3], Long.parseLong(fields[1]));
                campaign.feedEvents.add(event);
                campaign.feedEventsById.put(event.eventId, event);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || event_id || char(31) || kind || char(31) || COALESCE(value, '') FROM play_campaign_projection_events ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.projectionEvents.add(new ProjectionEvent(Long.parseLong(fields[1]), fields[2], fields[3], fields[4].isEmpty() ? null : fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || event_id || char(31) || text FROM play_campaign_replay_events ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 4 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                ReplayEvent event = new ReplayEvent(fields[2], fields[3], Long.parseLong(fields[1]));
                campaign.replayEvents.add(event);
                campaign.replayEventsById.put(event.eventId, event);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || event_id || char(31) || value || char(31) || idempotency_key FROM play_campaign_idempotent_events ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                IdempotentEvent event = new IdempotentEvent(fields[2], fields[3], Long.parseLong(fields[1]), fields[4]);
                campaign.idempotentEvents.add(event);
                campaign.idempotentEventsByKey.put(event.idempotencyKey, event);
                campaign.idempotentEventsById.put(event.eventId, event);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || current_turn FROM play_campaign_safe_turn_state;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 2 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.safeCurrentTurn = Long.parseLong(fields[1]);
        }
        for (String line : sql("SELECT campaign_id || char(31) || submission_id || char(31) || action || char(31) || accepted_turn || char(31) || next_turn FROM play_campaign_safe_turns ORDER BY campaign_id, accepted_turn;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 5 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                SafeTurn turn = new SafeTurn(fields[1], fields[2], Long.parseLong(fields[3]), Long.parseLong(fields[4]));
                campaign.safeTurns.add(turn);
                campaign.safeTurnsBySubmissionId.put(turn.submissionId, turn);
            }
        }
        for (String line : sql("SELECT campaign_id || char(31) || sequence || char(31) || text FROM play_campaign_narrations ORDER BY campaign_id, sequence;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            PlayCampaign campaign = fields.length == 3 ? PLAY_CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null && campaign.events.isEmpty()) campaign.events.add(new PlayEvent(Long.parseLong(fields[1]), "narration", "dm", null, fields[2], null));
        }
        for (String line : sql("SELECT id || char(31) || name || char(31) || dm FROM campaigns;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            if (fields.length == 3) CAMPAIGNS.put(fields[0], new Campaign(fields[0], fields[1], fields[2]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || name || char(31) || level || char(31) || class FROM campaign_characters ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 5 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.characters.put(fields[1], new CampaignCharacter(fields[1], fields[2], Long.parseLong(fields[3]), fields[4]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || kind || char(31) || summary FROM campaign_events ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 4 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.events.put(fields[1], new CampaignEvent(fields[1], fields[2], fields[3]));
        }
        Map<String, Quest> quests = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || title || char(31) || status FROM campaign_quests ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 4 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Quest quest = new Quest(fields[1], fields[2], fields[3], List.of());
                campaign.quests.put(quest.id, quest);
                quests.put(quest.id, quest);
            }
        }
        for (String line : sql("SELECT quest_id || char(31) || milestone || char(31) || done FROM quest_milestones ORDER BY quest_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Quest quest = fields.length == 3 ? quests.get(fields[0]) : null;
            if (quest != null) quest.milestones.put(fields[1], fields[2].equals("1"));
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || name || char(31) || stance FROM campaign_factions ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 4 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.factions.put(fields[1], new Faction(fields[1], fields[2], fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || name || char(31) || faction_id || char(31) || disposition FROM campaign_npcs ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 5 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.npcs.put(fields[1], new Npc(fields[1], fields[2], fields[3], Long.parseLong(fields[4])));
        }
        for (String line : sql("SELECT campaign_id || char(31) || item_slug || char(31) || quantity FROM campaign_inventory ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 3 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.partyInventory.put(fields[1], Long.parseLong(fields[2]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || character_id || char(31) || item_slug || char(31) || quantity FROM character_equipment ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 4 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) campaign.equipment.computeIfAbsent(fields[1], unused -> new LinkedHashMap<>()).put(fields[2], Long.parseLong(fields[3]));
        }
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || character_id || char(31) || item_slug || char(31) || days_required || char(31) || days_completed || char(31) || cost_gp || char(31) || status FROM crafting_projects ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 8 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                CraftingProject project = new CraftingProject(fields[1], fields[2], fields[3], Long.parseLong(fields[4]), Long.parseLong(fields[6]));
                project.daysCompleted = Long.parseLong(fields[5]);
                project.status = fields[7];
                campaign.craftingProjects.put(project.id, project);
            }
        }
        Map<String, ScheduledSession> scheduledSessions = new LinkedHashMap<>();
        for (String line : sql("SELECT campaign_id || char(31) || id || char(31) || starts_at || char(31) || duration_minutes FROM campaign_scheduled_sessions ORDER BY campaign_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            Campaign campaign = fields.length == 4 ? CAMPAIGNS.get(fields[0]) : null;
            if (campaign != null) {
                Instant starts;
                try { starts = Instant.parse(fields[2]); } catch (DateTimeParseException e) { continue; }
                ScheduledSession session = new ScheduledSession(fields[1], fields[2], starts, Long.parseLong(fields[3]), List.of());
                campaign.scheduledSessions.put(session.id, session);
                scheduledSessions.put(session.id, session);
            }
        }
        for (String line : sql("SELECT session_id || char(31) || item FROM scheduled_session_agenda ORDER BY session_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            ScheduledSession session = fields.length == 2 ? scheduledSessions.get(fields[0]) : null;
            if (session != null) session.agenda.add(fields[1]);
        }
        for (String line : sql("SELECT session_id || char(31) || character_id || char(31) || present FROM scheduled_session_attendance ORDER BY session_id, position;", true).split("\\R")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\u001f", -1);
            ScheduledSession session = fields.length == 3 ? scheduledSessions.get(fields[0]) : null;
            if (session != null) session.attendance.put(fields[1], fields[2].equals("1"));
        }
    }

    /** Keep reload and reset in lockstep: both replace the complete in-memory snapshot. */
    private static void clearCaches() {
        USERS.clear();
        SESSIONS.clear();
        MONSTERS.clear();
        ITEMS.clear();
        CAMPAIGNS.clear();
        PLAY_CAMPAIGNS.clear();
        SPECTATOR_CAMPAIGNS.clear();
        ENCOUNTERS.clear();
    }

    private static String storageState(CombatSession session) {
        StringBuilder out = new StringBuilder("{\"id\":\"").append(escape(session.id)).append("\",\"round\":").append(session.round)
            .append(",\"turn_index\":").append(session.turnIndex).append(",\"order\":[");
        for (int i = 0; i < session.order.size(); i++) {
            if (i > 0) out.append(',');
            Combatant c = session.order.get(i);
            out.append("{\"name\":\"").append(escape(c.name)).append("\",\"dex\":").append(c.dex).append(",\"score\":").append(c.score).append('}');
        }
        out.append("],\"conditions\":{");
        boolean first = true;
        for (Combatant c : session.order) {
            if (!first) out.append(',');
            first = false;
            out.append('"').append(escape(c.name)).append("\":").append(conditionsArray(session.conditions.get(c.name)));
        }
        return out.append("}}").toString();
    }

    private static void restoreSession(String state) {
        Map<String, Object> saved = object(state);
        List<Combatant> order = new ArrayList<>();
        for (Object item : array(saved, "order")) {
            Map<String, Object> c = asObject(item);
            order.add(new Combatant(string(c, "name"), integer(c, "dex"), integer(c, "score")));
        }
        Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        Map<String, Object> savedConditions = asObject(saved.get("conditions"));
        for (Combatant c : order) {
            List<Condition> attached = new ArrayList<>();
            for (Object item : array(savedConditions, c.name)) {
                Map<String, Object> condition = asObject(item);
                attached.add(new Condition(string(condition, "condition"), integer(condition, "remaining_rounds")));
            }
            conditions.put(c.name, attached);
        }
        CombatSession session = new CombatSession(string(saved, "id"), order, conditions);
        session.round = integer(saved, "round");
        session.turnIndex = Math.toIntExact(integer(saved, "turn_index"));
        SESSIONS.put(session.id, session);
    }

    private static String sqlText(String value) { return "'" + value.replace("'", "''") + "'"; }
    private static String sql(String statement) throws IOException { return sql(statement, false); }
    private static String sql(String statement, boolean output) throws IOException {
        // The complete in-memory snapshot grows throughout the cumulative suite.
        // Supplying it as a command-line argument eventually exceeds exec's argv
        // limit, so feed it to sqlite's standard input instead.
        Process process = new ProcessBuilder("sqlite3", "-batch", "-noheader", DATABASE.toString()).start();
        try (OutputStream stdin = process.getOutputStream()) {
            stdin.write(statement.getBytes(StandardCharsets.UTF_8));
        }
        String stdout = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        String stderr = new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
        try { if (process.waitFor() != 0) throw new IOException("sqlite error: " + stderr); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException("sqlite interrupted", e); }
        return output ? stdout : "";
    }

    private static CombatSession session(String id) {
        CombatSession session = SESSIONS.get(id);
        if (session == null) throw new UnknownSession();
        return session;
    }

    private static String sessionId(String path, String suffix) {
        return path.substring("/v1/combat/sessions/".length(), path.length() - suffix.length());
    }

    private static String sessionState(CombatSession session, boolean includeConditions) {
        Combatant active = session.order.get(session.turnIndex);
        StringBuilder out = new StringBuilder("{\"id\":\"").append(escape(session.id)).append("\",\"round\":")
            .append(session.round).append(",\"turn_index\":").append(session.turnIndex).append(",\"active\":")
            .append(combatantJson(active));
        if (!includeConditions) {
            out.append(",\"order\":[");
            for (int i = 0; i < session.order.size(); i++) { if (i > 0) out.append(','); out.append(combatantJson(session.order.get(i))); }
            return out.append("]}").toString();
        }
        out.append(",\"conditions\":{");
        boolean first = true;
        for (Combatant combatant : session.order) {
            List<Condition> attached = session.conditions.get(combatant.name);
            if (!first) out.append(',');
            first = false;
            out.append("\"").append(escape(combatant.name)).append("\":").append(conditionsArray(attached));
        }
        return out.append("}}").toString();
    }

    private static String combatantJson(Combatant c) { return "{\"name\":\"" + escape(c.name) + "\",\"score\":" + c.score + "}"; }
    private static String conditionsArray(List<Condition> conditions) {
        StringBuilder out = new StringBuilder("[");
        for (int i = 0; i < conditions.size(); i++) {
            if (i > 0) out.append(',');
            Condition condition = conditions.get(i);
            out.append("{\"condition\":\"").append(escape(condition.condition)).append("\",\"remaining_rounds\":").append(condition.remainingRounds).append('}');
        }
        return out.append(']').toString();
    }

    private static String abilityModifier(Map<String, Object> b) {
        long score = abilityScore(b, "score");
        return "{\"score\":" + score + ",\"modifier\":" + modifier(score) + "}";
    }

    private static String proficiency(Map<String, Object> b) {
        long level = characterLevel(b, "level");
        return "{\"level\":" + level + ",\"proficiency_bonus\":" + proficiencyBonus(level) + "}";
    }

    private static String derivedStats(Map<String, Object> b) {
        long level = characterLevel(b, "level");
        Map<String, Object> abilities = asObject(b.get("abilities"));
        long str = modifier(abilityScore(abilities, "str"));
        long dex = modifier(abilityScore(abilities, "dex"));
        long con = modifier(abilityScore(abilities, "con"));
        long intel = modifier(abilityScore(abilities, "int"));
        long wis = modifier(abilityScore(abilities, "wis"));
        long cha = modifier(abilityScore(abilities, "cha"));
        Map<String, Object> armor = asObject(b.get("armor"));
        long base = integer(armor, "base");
        long dexCap = integer(armor, "dex_cap");
        Object shield = armor.get("shield");
        if (!(shield instanceof Boolean)) throw new IllegalArgumentException();
        long hp = Math.multiplyExact(level, Math.addExact(6, con));
        long armorClass = Math.addExact(Math.addExact(base, Math.min(dex, dexCap)), (Boolean) shield ? 2 : 0);
        return "{\"level\":" + level + ",\"proficiency_bonus\":" + proficiencyBonus(level)
            + ",\"hp_max\":" + hp + ",\"armor_class\":" + armorClass + ",\"modifiers\":{\"str\":" + str
            + ",\"dex\":" + dex + ",\"con\":" + con + ",\"int\":" + intel + ",\"wis\":" + wis
            + ",\"cha\":" + cha + "}}";
    }

    private static String spellSlots(Map<String, Object> b) {
        String characterClass = string(b, "class");
        long level = integer(b, "level");
        if (!characterClass.equals("wizard") || level != 5) throw new IllegalArgumentException();
        return "{\"class\":\"wizard\",\"level\":5,\"slots\":{\"1\":4,\"2\":3,\"3\":2}}";
    }

    private static String longRest(Map<String, Object> b) {
        long level = characterLevel(b, "level");
        long hpCurrent = integer(b, "hp_current");
        long hpMax = positive(integer(b, "hp_max"));
        long hitDiceSpent = integer(b, "hit_dice_spent");
        long exhaustion = integer(b, "exhaustion_level");
        if (hpCurrent < 0 || hpCurrent > hpMax || hitDiceSpent < 0 || hitDiceSpent > level || exhaustion < 0) {
            throw new IllegalArgumentException();
        }
        long restoredHitDice = Math.max(1, level / 2);
        long remainingSpent = Math.max(0, hitDiceSpent - restoredHitDice);
        long remainingExhaustion = Math.max(0, exhaustion - 1);
        return "{\"hp_current\":" + hpMax + ",\"hit_dice_spent\":" + remainingSpent
            + ",\"exhaustion_level\":" + remainingExhaustion + "}";
    }

    private static String equipmentLoad(Map<String, Object> b) {
        long strength = abilityScore(b, "strength");
        long weight = integer(b, "weight");
        if (weight < 0) throw new IllegalArgumentException();
        long capacity = Math.multiplyExact(strength, 15);
        return "{\"capacity\":" + capacity + ",\"weight\":" + weight + ",\"encumbered\":" + (weight > capacity) + "}";
    }

    private static long abilityScore(Map<String, Object> b, String key) {
        long score = integer(b, key);
        if (score < 1 || score > 30) throw new IllegalArgumentException();
        return score;
    }

    private static long modifier(long score) { return Math.floorDiv(score - 10, 2); }
    private static long characterLevel(Map<String, Object> b, String key) {
        long level = integer(b, key);
        if (level < 1 || level > 20) throw new IllegalArgumentException();
        return level;
    }
    private static long proficiencyBonus(long level) { return 2 + (level - 1) / 4; }

    private record Combatant(String name, long dex, long score) { }
    private record User(String username, String role, byte[] passwordHash) { }
    private record Monster(String slug, String name, String cr, long armorClass, long hitPoints, List<String> tags) { }
    private record Item(String slug, String name, String type, String rarity, long costGp) { }
    private record FixtureSeedResult(boolean created) { }
    private static final class Campaign {
        final String id, name, dm;
        final Map<String, CampaignCharacter> characters = new LinkedHashMap<>();
        final Map<String, CampaignEvent> events = new LinkedHashMap<>();
        final Map<String, Quest> quests = new LinkedHashMap<>();
        final Map<String, Faction> factions = new LinkedHashMap<>();
        final Map<String, Npc> npcs = new LinkedHashMap<>();
        final Map<String, Long> partyInventory = new LinkedHashMap<>();
        final Map<String, Map<String, Long>> equipment = new LinkedHashMap<>();
        final Map<String, CraftingProject> craftingProjects = new LinkedHashMap<>();
        final Map<String, ScheduledSession> scheduledSessions = new LinkedHashMap<>();
        Campaign(String id, String name, String dm) { this.id = id; this.name = name; this.dm = dm; }
    }
    private static final class PlayCampaign {
        final String id, name, owner; final long maxPlayers;
        final Map<String, PartyMember> members = new LinkedHashMap<>();
        final Map<String, Invitation> invitations = new LinkedHashMap<>();
        final Map<String, Delegation> delegations = new LinkedHashMap<>();
        final List<DelegationAuditEntry> delegationAudit = new ArrayList<>();
        final List<AuditEvent> auditEvents = new ArrayList<>();
        final Map<String, AuditEvent> auditCorrelationIds = new LinkedHashMap<>();
        final Map<String, LootRecord> loot = new LinkedHashMap<>();
        final Map<String, Recipe> recipes = new LinkedHashMap<>();
        final Map<String, DowntimeActivity> downtimeActivities = new LinkedHashMap<>();
        final Map<String, PlayNpc> npcs = new LinkedHashMap<>();
        final Map<String, Settlement> settlements = new LinkedHashMap<>();
        final Map<String, Relationship> relationships = new LinkedHashMap<>();
        final Map<String, Clue> clues = new LinkedHashMap<>();
        final Map<String, Content> content = new LinkedHashMap<>();
        final Map<String, SearchRecord> searchRecords = new LinkedHashMap<>();
        final Map<String, RateEvent> rateEvents = new LinkedHashMap<>();
        long rejectedRateEvents;
        final Map<String, Note> notes = new LinkedHashMap<>();
        final Map<String, Whisper> whispers = new LinkedHashMap<>();
        final Map<String, PlayQuest> quests = new LinkedHashMap<>();
        final Map<String, WorldEvent> worldEvents = new LinkedHashMap<>();
        final Map<String, PlayFaction> playFactions = new LinkedHashMap<>();
        final List<ReputationRecord> reputationHistory = new ArrayList<>();
        final Map<String, Scene> scenes = new LinkedHashMap<>();
        final Map<String, Location> locations = new LinkedHashMap<>();
        final List<PlayEvent> events = new ArrayList<>();
        final List<FeedEvent> feedEvents = new ArrayList<>();
        final Map<String, FeedEvent> feedEventsById = new LinkedHashMap<>();
        final List<ProjectionEvent> projectionEvents = new ArrayList<>();
        final List<ReplayEvent> replayEvents = new ArrayList<>();
        final Map<String, ReplayEvent> replayEventsById = new LinkedHashMap<>();
        final List<RngRoll> rngRolls = new ArrayList<>();
        final Map<String, RngRoll> rngRollsById = new LinkedHashMap<>();
        final Map<String, ModerationReport> moderationReports = new LinkedHashMap<>();
        final List<String> blockedSafetyTags = new ArrayList<>();
        final List<SafetyEvent> safetyEvents = new ArrayList<>();
        final Map<String, SafetyEvent> safetyEventsById = new LinkedHashMap<>();
        final List<IdempotentEvent> idempotentEvents = new ArrayList<>();
        final Map<String, IdempotentEvent> idempotentEventsByKey = new LinkedHashMap<>();
        final Map<String, IdempotentEvent> idempotentEventsById = new LinkedHashMap<>();
        final List<SafeTurn> safeTurns = new ArrayList<>();
        final Map<String, SafeTurn> safeTurnsBySubmissionId = new LinkedHashMap<>();
        final List<TransactionalTransfer> transactionalTransfers = new ArrayList<>();
        final List<CampaignExport> exports = new ArrayList<>();
        final List<CampaignBackup> backups = new ArrayList<>();
        CampaignImport importedSnapshot;
        MigratedState migratedState;
        String status = "lobby", currentActor, currentSceneId, activeEncounterId, story = "", dmNotes = "", rngSeed; long turnNumber = 0, nudgeCount = 0, currencyTransferId = 0, safeCurrentTurn = 1, transactionalTransferSequence = 0;
        SessionZero sessionZero;
        Calendar calendar;
        boolean nextResolutionStartsParty, fixtureSeeded;
        PlayCampaign(String id, String name, String owner, long maxPlayers) {
            this.id = id; this.name = name; this.owner = owner; this.maxPlayers = maxPlayers;
        }
    }
    private static final class CampaignExport {
        final long version;
        final String story, status;
        CampaignExport(long version, String story, String status) {
            this.version = version; this.story = story; this.status = status;
        }
    }
    private static final class CampaignBackup {
        final String backupId, story, status;
        CampaignBackup(String backupId, String story, String status) {
            this.backupId = backupId; this.story = story; this.status = status;
        }
    }
    private static final class RngRoll {
        final String rollId;
        final long sides, result, sequence;
        RngRoll(String rollId, long sides, long result, long sequence) {
            this.rollId = rollId; this.sides = sides; this.result = result; this.sequence = sequence;
        }
    }
    private static final class ModerationReport {
        final String reportId, targetId, reason, reporter;
        final long sequence;
        String status = "open", action, note, resolver;
        ModerationReport(String reportId, String targetId, String reason, String reporter, long sequence) {
            this.reportId = reportId;
            this.targetId = targetId;
            this.reason = reason;
            this.reporter = reporter;
            this.sequence = sequence;
        }
    }
    private static final class CampaignImport {
        final long version;
        final String story, status;
        CampaignImport(long version, String story, String status) {
            this.version = version; this.story = story; this.status = status;
        }
    }
    private static final class MigratedState {
        final String story, campaignName;
        MigratedState(String story, String campaignName) {
            this.story = story; this.campaignName = campaignName;
        }
    }
    private record MigrationResult(MigratedState state, boolean created) { }
    private static final class SessionZero {
        final String rules, tone;
        final List<String> consent = new ArrayList<>();
        SessionZero(String rules, String tone, List<String> consent) { this.rules = rules; this.tone = tone; this.consent.addAll(consent); }
    }
    private static final class Invitation {
        final String invitationId, username, characterId;
        String status = "pending";
        Invitation(String invitationId, String username, String characterId) {
            this.invitationId = invitationId; this.username = username; this.characterId = characterId;
        }
    }
    private static final class Delegation {
        final String username;
        final List<String> powers = new ArrayList<>();
        boolean active;
        Delegation(String username, List<String> powers, boolean active) {
            this.username = username; this.powers.addAll(powers); this.active = active;
        }
    }
    private static final class DelegationAuditEntry {
        final String username, action;
        final List<String> powers = new ArrayList<>();
        DelegationAuditEntry(String username, String action, List<String> powers) {
            this.username = username; this.action = action; this.powers.addAll(powers);
        }
    }
    private static final class AuditEvent {
        final String kind, actor, role, correlationId;
        final long timestamp;
        AuditEvent(String kind, String actor, String role, long timestamp, String correlationId) {
            this.kind = kind; this.actor = actor; this.role = role; this.timestamp = timestamp; this.correlationId = correlationId;
        }
    }
    private static final class Content {
        final String contentId, kind, text;
        final List<String> tags = new ArrayList<>();
        Content(String contentId, String kind, String text, List<String> tags) {
            this.contentId = contentId; this.kind = kind; this.text = text; this.tags.addAll(tags);
        }
    }
    private record SearchRecord(String recordId, String text) { }
    private record RateEvent(String eventId, String actor) { }
    private record SearchParameters(String query, long limit, long cursor) { }
    private record FeedPagination(long cursor, long limit) { }
    private static final class Note {
        final String noteId, owner;
        String text, visibility;
        Note(String noteId, String text, String visibility, String owner) { this.noteId = noteId; this.text = text; this.visibility = visibility; this.owner = owner; }
    }
    private record Whisper(String whisperId, String fromCharacterId, String toCharacterId, String text) { }
    private static final class Recipe {
        final String recipeId, name, outputItem;
        final Map<String, Long> ingredients = new LinkedHashMap<>();
        final long outputQuantity;
        Recipe(String recipeId, String name, Map<String, Long> ingredients, String outputItem, long outputQuantity) {
            this.recipeId = recipeId; this.name = name; this.ingredients.putAll(ingredients);
            this.outputItem = outputItem; this.outputQuantity = outputQuantity;
        }
    }
    private static final class DowntimeActivity {
        final String activityId, name;
        final long cyclesRequired;
        DowntimeActivity(String activityId, String name, long cyclesRequired) {
            this.activityId = activityId; this.name = name; this.cyclesRequired = cyclesRequired;
        }
    }
    private static final class DowntimeAllocation {
        final String characterId, activityId;
        long cyclesCompleted, completions;
        DowntimeAllocation(String characterId, String activityId) { this.characterId = characterId; this.activityId = activityId; }
    }
    private record SettlementFields(String name, List<String> services, String availability) { }
    private record DiscoveryResult(boolean created, String json) { }
    private static final class Settlement {
        final String settlementId;
        String name, availability;
        final List<String> services = new ArrayList<>();
        final List<String> discoveredBy = new ArrayList<>();
        final Map<String, Shop> shops = new LinkedHashMap<>();
        Settlement(String settlementId, String name, List<String> services, String availability) {
            this.settlementId = settlementId; this.name = name; this.services.addAll(services); this.availability = availability;
        }
    }
    private static final class Shop {
        final String shopId, name;
        final Map<String, Long> stock = new LinkedHashMap<>();
        final long buyPrice, sellPrice;
        Shop(String shopId, String name, Map<String, Long> stock, long buyPrice, long sellPrice) {
            this.shopId = shopId; this.name = name; this.stock.putAll(stock); this.buyPrice = buyPrice; this.sellPrice = sellPrice;
        }
    }
    private static final class PlayQuest {
        final String questId, title;
        final List<String> dependsOn = new ArrayList<>();
        String state = "locked";
        QuestReward reward;
        PlayQuest(String questId, String title, List<String> dependsOn) {
            this.questId = questId; this.title = title; this.dependsOn.addAll(dependsOn);
        }
    }
    private static final class QuestReward {
        final long xp;
        final Map<String, Long> items = new LinkedHashMap<>();
        boolean awarded;
        QuestReward(long xp, Map<String, Long> items) { this.xp = xp; this.items.putAll(items); }
    }
    private static final class QuestRewardGrant {
        final String questId;
        final long xp;
        final Map<String, Long> items = new LinkedHashMap<>();
        QuestRewardGrant(String questId, long xp, Map<String, Long> items) { this.questId = questId; this.xp = xp; this.items.putAll(items); }
    }
    private static final class WorldEvent {
        final String eventId, title, text;
        final long turnNumber;
        WorldEventResolution resolution;
        WorldEvent(String eventId, long turnNumber, String title, String text) {
            this.eventId = eventId; this.turnNumber = turnNumber; this.title = title; this.text = text;
        }
    }
    private static final class Calendar {
        long day;
        final String season;
        Calendar(long day, String season) { this.day = day; this.season = season; }
    }
    private record WorldEventResolution(long turnNumber, String text) { }
    private static final class Scene {
        final String id, name; String status = "open";
        Scene(String id, String name) { this.id = id; this.name = name; }
    }
    private static final class Location {
        final String id, name;
        final Map<String, Long> connections = new LinkedHashMap<>();
        Location(String id, String name) { this.id = id; this.name = name; }
    }
    private static final class Encounter {
        final String id, campaignId, name;
        final Map<String, EncounterMonster> monsters = new LinkedHashMap<>();
        final Map<String, EncounterCombatant> combatants = new LinkedHashMap<>();
        final Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        List<String> turnOrder;
        EncounterReward reward;
        String status = "active";
        long round = 1, turnIndex = 0;
        Encounter(String id, String campaignId, String name) { this.id = id; this.campaignId = campaignId; this.name = name; }
    }
    private static final class EncounterReward {
        final long xp;
        final List<Loot> loot;
        EncounterReward(long xp, List<Loot> loot) { this.xp = xp; this.loot = new ArrayList<>(loot); }
    }
    private record Loot(String slug, long quantity) { }
    private static final class LootRecord {
        final String lootId, itemId;
        final long quantity;
        final Map<String, String> votes = new LinkedHashMap<>();
        String status = "open", recipientCharacterId;
        long assignedVotes;
        LootRecord(String lootId, String itemId, long quantity) { this.lootId = lootId; this.itemId = itemId; this.quantity = quantity; }
    }
    private static final class PlayNpc {
        final String npcId, name;
        final List<DialogueEntry> dialogue = new ArrayList<>();
        String agenda, publicStatus;
        PlayNpc(String npcId, String name, String agenda, String publicStatus) {
            this.npcId = npcId; this.name = name; this.agenda = agenda; this.publicStatus = publicStatus;
        }
    }
    private record DialogueEntry(String dialogueId, String speaker, String text, String visibility) { }
    private static final class Relationship {
        final String sourceId, targetId, kind;
        long score;
        Relationship(String sourceId, String targetId, String kind, long score) {
            this.sourceId = sourceId; this.targetId = targetId; this.kind = kind; this.score = score;
        }
    }
    private record Clue(String clueId, String text, String audience, String characterId) { }
    private record PlayFaction(String factionId, String name) { }
    private record ReputationRecord(String factionId, String characterId, long reputation, long delta, String reason) { }
    private record CombatTurnEntry(String username, String id, String name, String kind, long initiative) { }
    private record EncounterCombatant(String username, String characterId, String name, long initiative) { }
    private static final class EncounterMonster {
        final String id, name; final long hpMax, initiative; long hpCurrent;
        EncounterMonster(String id, String name, long hpMax, long initiative) { this(id, name, hpMax, hpMax, initiative); }
        EncounterMonster(String id, String name, long hpMax, long hpCurrent, long initiative) {
            this.id = id; this.name = name; this.hpMax = hpMax; this.hpCurrent = hpCurrent; this.initiative = initiative;
        }
    }
    private static final class PartyMember {
        final String username, characterId, name;
        final Map<String, Spell> spells = new LinkedHashMap<>();
        final List<String> preparedSpellIds = new ArrayList<>();
        final List<CastEvent> casts = new ArrayList<>();
        final Map<String, Long> inventory = new LinkedHashMap<>();
        final Map<String, QuestRewardGrant> questRewardGrants = new LinkedHashMap<>();
        final Map<String, Equipment> equipment = new LinkedHashMap<>();
        final Map<String, DowntimeAllocation> downtimeAllocations = new LinkedHashMap<>();
        Concentration concentration;
        String characterClass;
        long level = 1, conModifier = 0, strength = 10, dexterity = 10, constitution = 10, intelligence = 10, wisdom = 10, charisma = 10, hpCurrent, hpMax, deathSaveSuccesses, deathSaveFailures, gold = 10;
        String status, owner;
        PartyMember(String username, String characterId, String name, String characterClass) {
            this(username, characterId, name, characterClass, 20, 20, "conscious", 0, 0);
        }
        PartyMember(String username, String characterId, String name, String characterClass, long hpCurrent, long hpMax) {
            this(username, characterId, name, characterClass, hpCurrent, hpMax, hpCurrent == 0 ? "unconscious" : "conscious", 0, 0);
        }
        PartyMember(String username, String characterId, String name, String characterClass, long hpCurrent, long hpMax,
                    String status, long deathSaveSuccesses, long deathSaveFailures) {
            this(username, characterId, name, characterClass, username, hpCurrent, hpMax, status, deathSaveSuccesses, deathSaveFailures);
        }
        PartyMember(String username, String characterId, String name, String characterClass, String owner, long hpCurrent, long hpMax,
                    String status, long deathSaveSuccesses, long deathSaveFailures) {
            this(username, characterId, name, characterClass, owner, 1, 0, hpCurrent, hpMax, status, deathSaveSuccesses, deathSaveFailures);
        }
        PartyMember(String username, String characterId, String name, String characterClass, String owner, long level, long conModifier,
                    long hpCurrent, long hpMax, String status, long deathSaveSuccesses, long deathSaveFailures) {
            this.username = username; this.characterId = characterId; this.name = name; this.characterClass = characterClass;
            this.owner = owner;
            this.level = level; this.conModifier = conModifier; this.hpCurrent = hpCurrent; this.hpMax = hpMax; this.status = status;
            this.deathSaveSuccesses = deathSaveSuccesses; this.deathSaveFailures = deathSaveFailures;
        }
        PartyMember(String username, String characterId, String name, String characterClass, String owner, long level, long conModifier,
                    long strength, long dexterity, long constitution, long intelligence, long wisdom, long charisma,
                    long hpCurrent, long hpMax, String status, long deathSaveSuccesses, long deathSaveFailures) {
            this(username, characterId, name, characterClass, owner, level, conModifier, hpCurrent, hpMax, status, deathSaveSuccesses, deathSaveFailures);
            this.strength = strength; this.dexterity = dexterity; this.constitution = constitution;
            this.intelligence = intelligence; this.wisdom = wisdom; this.charisma = charisma;
        }
        long abilityScore(String ability) {
            return switch (ability) {
                case "str" -> strength; case "dex" -> dexterity; case "con" -> constitution;
                case "int" -> intelligence; case "wis" -> wisdom; case "cha" -> charisma;
                default -> throw new IllegalArgumentException();
            };
        }
    }
    private record Spell(String spellId, String name, long level) { }
    private record CastEvent(String spellId, String target, long slotLevel, long slotsRemaining, long sequence) { }
    private static final class Concentration {
        final String spellId, target;
        long remainingTurns;
        Concentration(String spellId, String target, long remainingTurns) {
            this.spellId = spellId; this.target = target; this.remainingTurns = remainingTurns;
        }
    }
    private static final class Equipment {
        final String itemId;
        boolean attuned;
        Equipment(String itemId, boolean attuned) { this.itemId = itemId; this.attuned = attuned; }
    }
    private record PlayEvent(long sequence, String kind, String actor, String type, String text, String target) { }
    private record FeedEvent(String eventId, String text, long sequence) { }
    private record ProjectionEvent(long sequence, String eventId, String kind, String value) { }
    private record ReplayEvent(String eventId, String text, long sequence) { }
    private record IdempotentEvent(String eventId, String value, long sequence, String idempotencyKey) { }
    private record SafeTurn(String submissionId, String action, long acceptedTurn, long nextTurn) { }
    private record SafetyEvent(String eventId, String kind, String text, List<String> tags, long sequence) { }
    private record TransactionalTransfer(String fromCharacterId, String toCharacterId, long amount, long fromGold, long toGold, long sequence) { }
    private record SafeTurnResult(boolean accepted, String json) { }
    private record IdempotentEventResult(IdempotentEvent event, boolean created) { }
    private record CampaignCharacter(String id, String name, long level, String characterClass) { }
    private record CampaignEvent(String id, String kind, String summary) { }
    private record Faction(String id, String name, String stance) { }
    private record Npc(String id, String name, String factionId, long disposition) { }
    private static final class CraftingProject {
        final String id, characterId, itemSlug; final long daysRequired, costGp;
        long daysCompleted = 0; String status = "active";
        CraftingProject(String id, String characterId, String itemSlug, long daysRequired, long costGp) {
            this.id = id; this.characterId = characterId; this.itemSlug = itemSlug;
            this.daysRequired = daysRequired; this.costGp = costGp;
        }
    }
    private static final class ScheduledSession {
        final String id, startsAt; final Instant starts; final long durationMinutes;
        final List<String> agenda = new ArrayList<>();
        final Map<String, Boolean> attendance = new LinkedHashMap<>();
        ScheduledSession(String id, String startsAt, Instant starts, long durationMinutes, List<String> agenda) {
            this.id = id; this.startsAt = startsAt; this.starts = starts; this.durationMinutes = durationMinutes;
            this.agenda.addAll(agenda);
        }
    }
    private static final class Quest {
        final String id, title, status;
        final Map<String, Boolean> milestones = new LinkedHashMap<>();
        Quest(String id, String title, String status, List<String> milestoneNames) {
            this.id = id; this.title = title; this.status = status;
            for (String milestone : milestoneNames) {
                if (milestones.put(milestone, false) != null) throw new IllegalArgumentException();
            }
        }
    }
    private static final class Condition {
        final String condition; long remainingRounds;
        Condition(String condition, long remainingRounds) { this.condition = condition; this.remainingRounds = remainingRounds; }
    }
    private static final class CombatSession {
        final String id; final List<Combatant> order; final Map<String, List<Condition>> conditions;
        long round = 1; int turnIndex = 0;
        CombatSession(String id, List<Combatant> order, Map<String, List<Condition>> conditions) { this.id = id; this.order = order; this.conditions = conditions; }
    }
    private static final class UnknownSession extends RuntimeException { }
    private static final class DuplicateUser extends RuntimeException { }
    private static final class DuplicateSlug extends RuntimeException { }
    private static final class DuplicateId extends RuntimeException { }
    private static final class DuplicateSpectator extends RuntimeException { }
    private static final class CampaignStartConflict extends RuntimeException { }
    private static final class SessionZeroConflict extends RuntimeException { }
    private static final class TurnConflict extends RuntimeException { }
    private static final class TravelConflict extends RuntimeException { }
    private static final class SceneConflict extends RuntimeException { }
    private static final class DeathSaveConflict extends RuntimeException { }
    private static final class OwnershipConflict extends RuntimeException { }
    private static final class InventoryConflict extends RuntimeException { }
    private static final class CurrencyConflict extends RuntimeException { }
    private static final class ShopStockConflict extends RuntimeException { }
    private static final class LootConflict extends RuntimeException { }
    private static final class AttunementConflict extends RuntimeException { }
    private static final class SpellConflict extends RuntimeException { }
    private static final class SpellSlotConflict extends RuntimeException { }
    private static final class EncounterTransitionConflict extends RuntimeException { }
    private static final class QuestTransitionConflict extends RuntimeException { }
    private static final class QuestRewardConflict extends RuntimeException { }
    private static final class WorldEventConflict extends RuntimeException { }
    private static final class CalendarConflict extends RuntimeException { }
    private static final class InvitationConflict extends RuntimeException { }
    private static final class ProjectionEventConflict extends RuntimeException { }
    private static final class ReplayEventConflict extends RuntimeException { }
    private static final class FeedEventConflict extends RuntimeException { }
    private static final class RngConflict extends RuntimeException { }
    private static final class ModerationReportConflict extends RuntimeException { }
    private static final class SafetyCheckConflict extends RuntimeException { }
    private static final class IdempotentEventConflict extends RuntimeException { }
    private static final class SafeTurnConflict extends RuntimeException { }
    private static final class RateLimitExceeded extends RuntimeException { }
    private static final class SimulatedFailure extends RuntimeException { }
    private static final class UnknownRecord extends RuntimeException { }
    private static final class BadCredentials extends RuntimeException { }
    private static final class Unauthorized extends RuntimeException { }
    private static final class Forbidden extends RuntimeException { }

    private static String readBody(HttpExchange e) throws IOException { return new String(e.getRequestBody().readAllBytes(), StandardCharsets.UTF_8); }
    private static synchronized User actor(HttpExchange exchange) {
        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (authorization == null || !authorization.startsWith("Bearer session-")) throw new Unauthorized();
        String username = authorization.substring("Bearer session-".length());
        if (!USERNAME.matcher(username).matches()) throw new Unauthorized();
        User user = USERS.get(username);
        // Play sessions are deterministic bearer identities.  They must remain
        // usable after storage reset, and non-registered actors are still valid
        // callers that can be denied campaign-scoped permission with 403.
        return user != null ? user : new User(username, username.equals("dm") ? "dm" : "player", new byte[0]);
    }
    private static void reply(HttpExchange e, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        e.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        e.sendResponseHeaders(status, bytes.length);
        e.getResponseBody().write(bytes);
        e.close();
    }
    private static Map<String, Object> object(String text) { Object v = new Json(text).parse(); return asObject(v); }
    @SuppressWarnings("unchecked") private static Map<String, Object> asObject(Object v) { if (!(v instanceof Map)) throw new IllegalArgumentException(); return (Map<String, Object>) v; }
    @SuppressWarnings("unchecked") private static List<Object> array(Map<String, Object> b, String key) { Object v = b.get(key); if (!(v instanceof List)) throw new IllegalArgumentException(); return (List<Object>) v; }
    private static String string(Map<String, Object> b, String key) { Object v = b.get(key); if (!(v instanceof String s)) throw new IllegalArgumentException(); return s; }
    private static boolean bool(Map<String, Object> b, String key) { Object v = b.get(key); if (!(v instanceof Boolean value)) throw new IllegalArgumentException(); return value; }
    private static String requiredText(Map<String, Object> b, String key) { String value = string(b, key); if (value.isEmpty()) throw new IllegalArgumentException(); return value; }
    private static List<String> strings(List<Object> values) {
        List<String> result = new ArrayList<>();
        for (Object value : values) {
            if (!(value instanceof String text) || text.isEmpty()) throw new IllegalArgumentException();
            result.add(text);
        }
        return result;
    }
    private static long integer(Map<String, Object> b, String key) { Object v = b.get(key); if (!(v instanceof Long n)) throw new IllegalArgumentException(); return n; }
    private static long number(String v) { try { return Long.parseLong(v); } catch (NumberFormatException e) { throw new IllegalArgumentException(); } }
    private static long positive(String v) { long n = number(v); if (n <= 0) throw new IllegalArgumentException(); return n; }
    private static long positive(long n) { if (n <= 0) throw new IllegalArgumentException(); return n; }
    private static String jsonNumber(double n) { return n == Math.rint(n) ? Long.toString((long)n) : Double.toString(n); }
    private static String jsonStrings(List<String> values) {
        StringBuilder out = new StringBuilder("[");
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) out.append(',');
            out.append('"').append(escape(values.get(i))).append('"');
        }
        return out.append(']').toString();
    }
    private static String escape(String s) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\' -> out.append("\\\\");
                case '"' -> out.append("\\\"");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> { if (c < 0x20) out.append(String.format("\\u%04x", (int) c)); else out.append(c); }
            }
        }
        return out.toString();
    }

    private static final class Json {
        private final String s; private int i;
        Json(String s) { this.s = s; }
        Object parse() { Object v = value(); ws(); if (i != s.length()) bad(); return v; }
        private Object value() { ws(); if (i == s.length()) bad(); char c = s.charAt(i); return c == '{' ? obj() : c == '[' ? arr() : c == '"' ? str() : c == '-' || Character.isDigit(c) ? num() : literal(); }
        private Map<String, Object> obj() { Map<String, Object> m = new LinkedHashMap<>(); take('{'); ws(); if (peek('}')) { i++; return m; } while (true) { String key = str(); ws(); take(':'); m.put(key, value()); ws(); if (peek('}')) { i++; return m; } take(','); ws(); } }
        private List<Object> arr() { List<Object> a = new ArrayList<>(); take('['); ws(); if (peek(']')) { i++; return a; } while (true) { a.add(value()); ws(); if (peek(']')) { i++; return a; } take(','); } }
        private String str() { take('"'); StringBuilder b = new StringBuilder(); while (i < s.length() && s.charAt(i) != '"') { char c = s.charAt(i++); if (c == '\\') { if (i == s.length()) bad(); char e = s.charAt(i++); if (e == '"' || e == '\\' || e == '/') b.append(e); else if (e == 'b') b.append('\b'); else if (e == 'f') b.append('\f'); else if (e == 'n') b.append('\n'); else if (e == 'r') b.append('\r'); else if (e == 't') b.append('\t'); else if (e == 'u') { if (i + 4 > s.length()) bad(); try { b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); } catch (NumberFormatException x) { bad(); } i += 4; } else bad(); } else { if (c < 0x20) bad(); b.append(c); } } take('"'); return b.toString(); }
        private Long num() { int start = i; if (peek('-')) i++; if (i == s.length() || !Character.isDigit(s.charAt(i))) bad(); if (s.charAt(i) == '0') i++; else while (i < s.length() && Character.isDigit(s.charAt(i))) i++; if (i < s.length() && (s.charAt(i) == '.' || s.charAt(i) == 'e' || s.charAt(i) == 'E')) bad(); try { return Long.parseLong(s.substring(start, i)); } catch (NumberFormatException e) { bad(); return 0L; } }
        private Object literal() { if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; } if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; } if (s.startsWith("null", i)) { i += 4; return null; } bad(); return null; }
        private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }
        private boolean peek(char c) { return i < s.length() && s.charAt(i) == c; }
        private void take(char c) { if (!peek(c)) bad(); i++; }
        private void bad() { throw new IllegalArgumentException(); }
    }
}
