import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * Standalone D&D 5e tooling API served with the JDK's built-in HttpServer
 * (no third-party dependencies). All request-serving state lives in the
 * in-memory maps declared alongside each domain's handlers (combat sessions,
 * users, monsters, items, campaigns); {@code game.db} is a best-effort SQLite
 * mirror touched only on startup and {@code /v1/storage/reset}, not read on
 * the request path. See CODEBASE.md for the full routing and module map.
 */
public class Main {

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        initStorage();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", Main::handleHealth);
        server.createContext("/v1/dice/stats", Main::handleDiceStats);
        server.createContext("/v1/checks/ability", Main::handleAbilityCheck);
        server.createContext("/v1/encounters/adjusted-xp", Main::handleAdjustedXp);
        server.createContext("/v1/initiative/order", Main::handleInitiativeOrder);
        server.createContext("/v1/characters/ability-modifier", Main::handleAbilityModifier);
        server.createContext("/v1/characters/proficiency", Main::handleProficiency);
        server.createContext("/v1/characters/derived-stats", Main::handleDerivedStats);
        server.createContext("/v1/combat/sessions", Main::handleCombat);
        server.createContext("/v1/auth/register", Main::handleRegister);
        server.createContext("/v1/auth/login", Main::handleLogin);
        server.createContext("/v1/storage/status", Main::handleStorageStatus);
        server.createContext("/v1/storage/reset", Main::handleStorageReset);
        server.createContext("/v1/compendium/monsters", Main::handleMonsters);
        server.createContext("/v1/compendium/items", Main::handleItems);
        server.createContext("/v1/campaigns", Main::handleCampaigns);
        server.createContext("/v1/phb/spell-slots", Main::handleSpellSlots);
        server.createContext("/v1/phb/rests/long", Main::handleLongRest);
        server.createContext("/v1/phb/equipment-load", Main::handleEquipmentLoad);
        server.createContext("/v1/dm/encounter-builder", Main::handleEncounterBuilder);
        server.createContext("/v1/dm/loot-parcel", Main::handleLootParcel);
        server.createContext("/v1/dm/session-recap", Main::handleSessionRecap);
        server.createContext("/v1/play/campaigns", Main::handlePlayCampaigns);
        server.createContext("/v1/schema", Main::handleSchema);
        server.createContext("/healthz", Main::handleLiveness);
        server.createContext("/readyz", Main::handleReadiness);
        server.setExecutor(null);
        server.start();
        System.out.println("Listening on 127.0.0.1:" + port);
    }

    // ---------- SQLite mirror (best-effort, not read on the request path) ----------
    //
    // game.db exists so operators can inspect schema/state with the sqlite3 CLI,
    // but every handler below reads and writes the in-memory maps declared next
    // to it (COMBAT_SESSIONS, USERS, MONSTERS, ITEMS, CAMPAIGNS). initStorage()
    // and resetStorage() shell out to the sqlite3 binary to keep game.db's
    // schema in sync; if that binary is unavailable, storage falls back to an
    // empty placeholder file and the in-memory maps remain fully authoritative.

    private static final String DB_PATH = "game.db";
    private static final int SCHEMA_VERSION = 1;
    private static final AtomicBoolean STORAGE_INITIALIZED = new AtomicBoolean(false);
    private static final AtomicBoolean MAINTENANCE_MODE = new AtomicBoolean(false);

    private static final String SCHEMA_SQL =
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);\n"
            + "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT, password_hash TEXT, salt TEXT);\n"
            + "CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, round INTEGER, turn_index INTEGER, data TEXT);\n"
            + "CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, data TEXT);\n"
            + "CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, data TEXT);\n"
            + "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, data TEXT);\n"
            + "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '" + SCHEMA_VERSION + "');\n";

    private static final String RESET_SQL =
            "DROP TABLE IF EXISTS users;\n"
            + "DROP TABLE IF EXISTS combat_sessions;\n"
            + "DROP TABLE IF EXISTS monsters;\n"
            + "DROP TABLE IF EXISTS items;\n"
            + "DROP TABLE IF EXISTS campaigns;\n"
            + "DROP TABLE IF EXISTS schema_meta;\n"
            + SCHEMA_SQL;

    private static void initStorage() {
        try {
            runSqlite(SCHEMA_SQL);
        } catch (Exception e) {
            try {
                if (!Files.exists(Path.of(DB_PATH))) {
                    Files.createFile(Path.of(DB_PATH));
                }
            } catch (IOException ignored) {
                // best effort
            }
        } finally {
            STORAGE_INITIALIZED.set(true);
        }
    }

    private static void resetStorage() throws Exception {
        runSqlite(RESET_SQL);
    }

    private static void runSqlite(String sql) throws Exception {
        ProcessBuilder pb = new ProcessBuilder("sqlite3", DB_PATH);
        pb.redirectErrorStream(true);
        Process process = pb.start();
        try (OutputStream os = process.getOutputStream()) {
            os.write(sql.getBytes(StandardCharsets.UTF_8));
        }
        try (InputStream is = process.getInputStream()) {
            is.readAllBytes();
        }
        boolean finished = process.waitFor(10, java.util.concurrent.TimeUnit.SECONDS);
        if (!finished) {
            process.destroyForcibly();
            throw new IOException("sqlite3 timed out");
        }
        if (process.exitValue() != 0) {
            throw new IOException("sqlite3 exited with code " + process.exitValue());
        }
    }

    private static void handleStorageStatus(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) {
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("driver", "sqlite");
        resp.put("schema_version", SCHEMA_VERSION);
        resp.put("initialized", STORAGE_INITIALIZED.get());
        sendJson(exchange, 200, resp);
    }

    private static void handleStorageReset(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        COMBAT_SESSIONS.clear();
        MONSTERS.clear();
        ITEMS.clear();
        CAMPAIGNS.clear();
        try {
            resetStorage();
        } catch (Exception e) {
            // best effort; in-memory state has already been cleared
        }
        STORAGE_INITIALIZED.set(true);
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("ok", true);
        resp.put("schema_version", SCHEMA_VERSION);
        sendJson(exchange, 200, resp);
    }

    // ---------- Handlers ----------

    private static void handleHealth(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) {
            return;
        }
        sendJson(exchange, 200, mapOf("ok", true));
    }

    private static void handleSchema(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) {
            return;
        }
        List<Object> endpoints = new ArrayList<>();
        endpoints.add(schemaEndpoint("GET", "/v1/play/campaigns/{id}/rng-ledger", "member"));
        endpoints.add(schemaEndpoint("GET", "/v1/schema", "public"));
        endpoints.add(schemaEndpoint("POST", "/v1/play/campaigns", "dm"));
        endpoints.add(schemaEndpoint("POST", "/v1/play/campaigns/{id}/fixture-seeds", "dm"));
        endpoints.add(schemaEndpoint("POST", "/v1/play/campaigns/{id}/members", "member"));
        endpoints.add(schemaEndpoint("POST", "/v1/play/campaigns/{id}/moderation/reports", "member"));
        endpoints.add(schemaEndpoint("POST", "/v1/play/campaigns/{id}/rng-rolls", "member"));
        endpoints.add(schemaEndpoint("PUT", "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", "dm"));
        endpoints.add(schemaEndpoint("PUT", "/v1/play/campaigns/{id}/rng-seed", "dm"));
        endpoints.add(schemaEndpoint("PUT", "/v1/play/campaigns/{id}/safety-boundaries", "dm"));
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("version", "2026-07-29");
        resp.put("endpoints", endpoints);
        sendJson(exchange, 200, resp);
    }

    private static Map<String, Object> schemaEndpoint(String method, String path, String auth) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("method", method);
        item.put("path", path);
        item.put("auth", auth);
        return item;
    }

    private static void handleLiveness(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) {
            return;
        }
        sendJson(exchange, 200, mapOf("status", "ok"));
    }

    private static void handleReadiness(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) {
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        if (MAINTENANCE_MODE.get()) {
            resp.put("status", "maintenance");
            resp.put("schema_version", 2);
            sendJson(exchange, 503, resp);
        } else {
            resp.put("status", "ready");
            resp.put("schema_version", 2);
            sendJson(exchange, 200, resp);
        }
    }

    private static final Pattern DICE_PATTERN =
            Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

    private static void handleDiceStats(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object exprObj = obj.get("expression");
            if (!(exprObj instanceof String)) {
                sendJson(exchange, 400, mapOf("error", "invalid expression"));
                return;
            }
            String expr = ((String) exprObj).trim();
            Matcher m = DICE_PATTERN.matcher(expr);
            if (!m.matches()) {
                sendJson(exchange, 400, mapOf("error", "invalid expression"));
                return;
            }
            long count = Long.parseLong(m.group(1));
            long sides = Long.parseLong(m.group(2));
            long modifier = 0;
            if (m.group(3) != null) {
                long modVal = Long.parseLong(m.group(4));
                modifier = "-".equals(m.group(3)) ? -modVal : modVal;
            }
            if (count <= 0 || sides <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid expression"));
                return;
            }
            long min = count * 1 + modifier;
            long max = count * sides + modifier;
            double average = (count * (sides + 1) / 2.0) + modifier;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("dice_count", count);
            resp.put("sides", sides);
            resp.put("modifier", modifier);
            resp.put("min", min);
            resp.put("max", max);
            resp.put("average", numeric(average));
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAbilityCheck(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            if (!(obj.get("roll") instanceof Number)
                    || !(obj.get("modifier") instanceof Number)
                    || !(obj.get("dc") instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            double roll = ((Number) obj.get("roll")).doubleValue();
            double modifier = ((Number) obj.get("modifier")).doubleValue();
            double dc = ((Number) obj.get("dc")).doubleValue();

            double total = roll + modifier;
            boolean success = total >= dc;
            double margin = total - dc;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("total", numeric(total));
            resp.put("success", success);
            resp.put("margin", numeric(margin));
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static final Map<String, Integer> CR_XP = new LinkedHashMap<>();
    static {
        CR_XP.put("0", 10);
        CR_XP.put("1/8", 25);
        CR_XP.put("1/4", 50);
        CR_XP.put("1/2", 100);
        CR_XP.put("1", 200);
        CR_XP.put("2", 450);
        CR_XP.put("3", 700);
        CR_XP.put("4", 1100);
        CR_XP.put("5", 1800);
    }

    private static final Map<Integer, int[]> LEVEL_THRESHOLDS = new LinkedHashMap<>();
    static {
        // level -> [easy, medium, hard, deadly]
        LEVEL_THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
    }

    private static double multiplierFor(long monsterCount) {
        if (monsterCount <= 1) return 1.0;
        if (monsterCount == 2) return 1.5;
        if (monsterCount <= 6) return 2.0;
        if (monsterCount <= 10) return 2.5;
        if (monsterCount <= 14) return 3.0;
        return 4.0;
    }

    private static void handleAdjustedXp(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object partyObj = obj.get("party");
            Object monstersObj = obj.get("monsters");
            if (!(partyObj instanceof List) || !(monstersObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            List<?> party = (List<?>) partyObj;
            List<?> monsters = (List<?>) monstersObj;

            int[] thresholdSum = new int[]{0, 0, 0, 0};
            for (Object p : party) {
                if (!(p instanceof Map)) {
                    sendJson(exchange, 400, mapOf("error", "invalid party entry"));
                    return;
                }
                Object levelObj = ((Map<?, ?>) p).get("level");
                if (!(levelObj instanceof Number)) {
                    sendJson(exchange, 400, mapOf("error", "invalid party entry"));
                    return;
                }
                int level = ((Number) levelObj).intValue();
                int[] th = LEVEL_THRESHOLDS.get(level);
                if (th == null) {
                    sendJson(exchange, 400, mapOf("error", "unsupported level"));
                    return;
                }
                for (int i = 0; i < 4; i++) thresholdSum[i] += th[i];
            }

            long baseXp = 0;
            long monsterCount = 0;
            for (Object m : monsters) {
                if (!(m instanceof Map)) {
                    sendJson(exchange, 400, mapOf("error", "invalid monster entry"));
                    return;
                }
                Map<?, ?> mm = (Map<?, ?>) m;
                Object crObj = mm.get("cr");
                Object countObj = mm.get("count");
                if (!(crObj instanceof String) || !(countObj instanceof Number)) {
                    sendJson(exchange, 400, mapOf("error", "invalid monster entry"));
                    return;
                }
                String cr = (String) crObj;
                long count = ((Number) countObj).longValue();
                Integer xp = CR_XP.get(cr);
                if (xp == null || count <= 0) {
                    sendJson(exchange, 400, mapOf("error", "unsupported cr"));
                    return;
                }
                baseXp += (long) xp * count;
                monsterCount += count;
            }

            double multiplier = multiplierFor(monsterCount);
            double adjustedXp = baseXp * multiplier;

            String difficulty = "trivial";
            if (adjustedXp >= thresholdSum[3]) difficulty = "deadly";
            else if (adjustedXp >= thresholdSum[2]) difficulty = "hard";
            else if (adjustedXp >= thresholdSum[1]) difficulty = "medium";
            else if (adjustedXp >= thresholdSum[0]) difficulty = "easy";

            Map<String, Object> thresholds = new LinkedHashMap<>();
            thresholds.put("easy", thresholdSum[0]);
            thresholds.put("medium", thresholdSum[1]);
            thresholds.put("hard", thresholdSum[2]);
            thresholds.put("deadly", thresholdSum[3]);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("base_xp", baseXp);
            resp.put("monster_count", monsterCount);
            resp.put("multiplier", numeric(multiplier));
            resp.put("adjusted_xp", numeric(adjustedXp));
            resp.put("difficulty", difficulty);
            resp.put("thresholds", thresholds);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleInitiativeOrder(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object combatantsObj = obj.get("combatants");
            if (!(combatantsObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            List<?> combatants = (List<?>) combatantsObj;

            List<Map<String, Object>> parsed = new ArrayList<>();
            for (Object c : combatants) {
                if (!(c instanceof Map)) {
                    sendJson(exchange, 400, mapOf("error", "invalid combatant"));
                    return;
                }
                Map<?, ?> cm = (Map<?, ?>) c;
                Object nameObj = cm.get("name");
                Object dexObj = cm.get("dex");
                Object rollObj = cm.get("roll");
                if (!(nameObj instanceof String) || !(dexObj instanceof Number) || !(rollObj instanceof Number)) {
                    sendJson(exchange, 400, mapOf("error", "invalid combatant"));
                    return;
                }
                String name = (String) nameObj;
                double dex = ((Number) dexObj).doubleValue();
                double roll = ((Number) rollObj).doubleValue();
                double score = roll + dex;

                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("name", name);
                entry.put("dex", dex);
                entry.put("score", score);
                parsed.add(entry);
            }

            parsed.sort((a, b) -> {
                double scoreA = (double) a.get("score");
                double scoreB = (double) b.get("score");
                if (scoreA != scoreB) return Double.compare(scoreB, scoreA);
                double dexA = (double) a.get("dex");
                double dexB = (double) b.get("dex");
                if (dexA != dexB) return Double.compare(dexB, dexA);
                String nameA = (String) a.get("name");
                String nameB = (String) b.get("name");
                return nameA.compareTo(nameB);
            });

            List<Object> order = new ArrayList<>();
            for (Map<String, Object> entry : parsed) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("name", entry.get("name"));
                item.put("score", numeric((double) entry.get("score")));
                order.add(item);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("order", order);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    // ---------- Combat handlers ----------

    private static final class Condition {
        String condition;
        long remainingRounds;

        Condition(String condition, long remainingRounds) {
            this.condition = condition;
            this.remainingRounds = remainingRounds;
        }
    }

    private static final class Combatant {
        String name;
        double dex;
        double roll;
        double score;
        List<Condition> conditions = new ArrayList<>();

        Combatant(String name, double dex, double roll) {
            this.name = name;
            this.dex = dex;
            this.roll = roll;
            this.score = dex + roll;
        }
    }

    private static final class CombatSession {
        String id;
        long round = 1;
        long turnIndex = 0;
        List<Combatant> order = new ArrayList<>();
    }

    private static final Map<String, CombatSession> COMBAT_SESSIONS = new ConcurrentHashMap<>();

    private static final Pattern COMBAT_CONDITIONS_PATH =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/conditions$");
    private static final Pattern COMBAT_ADVANCE_PATH =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/advance$");

    private static Map<String, Object> combatantSummary(Combatant c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", c.name);
        m.put("score", numeric(c.score));
        return m;
    }

    private static void handleCombat(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        if (path.equals("/v1/combat/sessions") || path.equals("/v1/combat/sessions/")) {
            handleCreateCombatSession(exchange);
            return;
        }
        Matcher condMatcher = COMBAT_CONDITIONS_PATH.matcher(path);
        if (condMatcher.matches()) {
            handleAddCondition(exchange, condMatcher.group(1));
            return;
        }
        Matcher advMatcher = COMBAT_ADVANCE_PATH.matcher(path);
        if (advMatcher.matches()) {
            handleAdvanceTurn(exchange, advMatcher.group(1));
            return;
        }
        sendJson(exchange, 404, mapOf("error", "not found"));
    }

    private static void handleCreateCombatSession(HttpExchange exchange) throws IOException {
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            String id = (String) idObj;
            if (COMBAT_SESSIONS.containsKey(id)) {
                sendJson(exchange, 400, mapOf("error", "session already exists"));
                return;
            }
            Object combatantsObj = obj.get("combatants");
            if (!(combatantsObj instanceof List) || ((List<?>) combatantsObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid combatants"));
                return;
            }
            List<?> combatants = (List<?>) combatantsObj;

            CombatSession session = new CombatSession();
            session.id = id;
            for (Object c : combatants) {
                if (!(c instanceof Map)) {
                    sendJson(exchange, 400, mapOf("error", "invalid combatant"));
                    return;
                }
                Map<?, ?> cm = (Map<?, ?>) c;
                Object nameObj = cm.get("name");
                Object dexObj = cm.get("dex");
                Object rollObj = cm.get("roll");
                if (!(nameObj instanceof String) || !(dexObj instanceof Number) || !(rollObj instanceof Number)) {
                    sendJson(exchange, 400, mapOf("error", "invalid combatant"));
                    return;
                }
                session.order.add(new Combatant((String) nameObj,
                        ((Number) dexObj).doubleValue(), ((Number) rollObj).doubleValue()));
            }

            session.order.sort(Comparator
                    .comparingDouble((Combatant c) -> c.score).reversed()
                    .thenComparing(Comparator.comparingDouble((Combatant c) -> c.dex).reversed())
                    .thenComparing(c -> c.name));

            COMBAT_SESSIONS.put(id, session);

            sendJson(exchange, 200, combatSessionCreateResponse(session));
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static Map<String, Object> combatSessionCreateResponse(CombatSession session) {
        List<Object> order = new ArrayList<>();
        for (Combatant c : session.order) {
            order.add(combatantSummary(c));
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", session.id);
        resp.put("round", session.round);
        resp.put("turn_index", session.turnIndex);
        resp.put("active", combatantSummary(session.order.get((int) session.turnIndex)));
        resp.put("order", order);
        return resp;
    }

    private static void handleAddCondition(HttpExchange exchange, String id) throws IOException {
        CombatSession session = COMBAT_SESSIONS.get(id);
        if (session == null) {
            sendJson(exchange, 404, mapOf("error", "session not found"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object targetObj = obj.get("target");
            Object conditionObj = obj.get("condition");
            Object durationObj = obj.get("duration_rounds");
            if (!(targetObj instanceof String) || !(conditionObj instanceof String)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (!(durationObj instanceof Number) || !isIntegral(durationObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid duration_rounds"));
                return;
            }
            long duration = ((Number) durationObj).longValue();
            if (duration <= 0) {
                sendJson(exchange, 400, mapOf("error", "duration_rounds must be positive"));
                return;
            }
            String target = (String) targetObj;
            Combatant combatant = null;
            for (Combatant c : session.order) {
                if (c.name.equals(target)) {
                    combatant = c;
                    break;
                }
            }
            if (combatant == null) {
                sendJson(exchange, 400, mapOf("error", "unknown target"));
                return;
            }
            combatant.conditions.add(new Condition((String) conditionObj, duration));

            List<Object> conditions = new ArrayList<>();
            for (Condition cond : combatant.conditions) {
                Map<String, Object> cm = new LinkedHashMap<>();
                cm.put("condition", cond.condition);
                cm.put("remaining_rounds", cond.remainingRounds);
                conditions.add(cm);
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("target", combatant.name);
            resp.put("conditions", conditions);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAdvanceTurn(HttpExchange exchange, String id) throws IOException {
        CombatSession session = COMBAT_SESSIONS.get(id);
        if (session == null) {
            sendJson(exchange, 404, mapOf("error", "session not found"));
            return;
        }
        int size = session.order.size();
        long nextIndex = session.turnIndex + 1;
        if (nextIndex >= size) {
            // Wrapping back to the first combatant starts a new round.
            nextIndex = 0;
            session.round += 1;
        }
        session.turnIndex = nextIndex;

        Combatant active = session.order.get((int) session.turnIndex);
        List<Condition> remaining = new ArrayList<>();
        for (Condition cond : active.conditions) {
            cond.remainingRounds -= 1;
            if (cond.remainingRounds > 0) {
                remaining.add(cond);
            }
        }
        active.conditions = remaining;

        Map<String, Object> conditionsMap = new LinkedHashMap<>();
        for (Combatant c : session.order) {
            if (c.conditions.isEmpty() && c != active) continue;
            List<Object> conds = new ArrayList<>();
            for (Condition cond : c.conditions) {
                Map<String, Object> cm = new LinkedHashMap<>();
                cm.put("condition", cond.condition);
                cm.put("remaining_rounds", cond.remainingRounds);
                conds.add(cm);
            }
            conditionsMap.put(c.name, conds);
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", session.id);
        resp.put("round", session.round);
        resp.put("turn_index", session.turnIndex);
        resp.put("active", combatantSummary(active));
        resp.put("conditions", conditionsMap);
        sendJson(exchange, 200, resp);
    }

    // ---------- Character handlers ----------

    private static int abilityModifier(long score) {
        return (int) Math.floor((score - 10) / 2.0);
    }

    private static int proficiencyBonus(long level) {
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    private static void handleAbilityModifier(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object scoreObj = obj.get("score");
            if (!(scoreObj instanceof Number) || !isIntegral(scoreObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid score"));
                return;
            }
            long score = ((Number) scoreObj).longValue();
            if (score < 1 || score > 30) {
                sendJson(exchange, 400, mapOf("error", "score out of range"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("score", score);
            resp.put("modifier", abilityModifier(score));
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleProficiency(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object levelObj = obj.get("level");
            if (!(levelObj instanceof Number) || !isIntegral(levelObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid level"));
                return;
            }
            long level = ((Number) levelObj).longValue();
            if (level < 1 || level > 20) {
                sendJson(exchange, 400, mapOf("error", "level out of range"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("level", level);
            resp.put("proficiency_bonus", proficiencyBonus(level));
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static final List<String> ABILITY_KEYS =
            List.of("str", "dex", "con", "int", "wis", "cha");

    private static void handleDerivedStats(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }

            Object levelObj = obj.get("level");
            if (!(levelObj instanceof Number) || !isIntegral(levelObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid level"));
                return;
            }
            long level = ((Number) levelObj).longValue();
            if (level < 1 || level > 20) {
                sendJson(exchange, 400, mapOf("error", "level out of range"));
                return;
            }

            Object abilitiesObj = obj.get("abilities");
            if (!(abilitiesObj instanceof Map)) {
                sendJson(exchange, 400, mapOf("error", "invalid abilities"));
                return;
            }
            Map<?, ?> abilities = (Map<?, ?>) abilitiesObj;
            Map<String, Integer> modifiers = new LinkedHashMap<>();
            for (String key : ABILITY_KEYS) {
                Object scoreObj = abilities.get(key);
                if (!(scoreObj instanceof Number) || !isIntegral(scoreObj)) {
                    sendJson(exchange, 400, mapOf("error", "invalid ability " + key));
                    return;
                }
                long score = ((Number) scoreObj).longValue();
                if (score < 1 || score > 30) {
                    sendJson(exchange, 400, mapOf("error", "ability out of range"));
                    return;
                }
                modifiers.put(key, abilityModifier(score));
            }

            Object armorObj = obj.get("armor");
            if (!(armorObj instanceof Map)) {
                sendJson(exchange, 400, mapOf("error", "invalid armor"));
                return;
            }
            Map<?, ?> armor = (Map<?, ?>) armorObj;
            Object baseObj = armor.get("base");
            Object dexCapObj = armor.get("dex_cap");
            Object shieldObj = armor.get("shield");
            if (!(baseObj instanceof Number) || !(dexCapObj instanceof Number) || !(shieldObj instanceof Boolean)) {
                sendJson(exchange, 400, mapOf("error", "invalid armor"));
                return;
            }
            long armorBase = ((Number) baseObj).longValue();
            double dexCap = ((Number) dexCapObj).doubleValue();
            boolean shield = (Boolean) shieldObj;

            int proficiencyBonus = proficiencyBonus(level);
            int conModifier = modifiers.get("con");
            int dexModifier = modifiers.get("dex");
            long hpMax = level * (6 + conModifier);
            double shieldBonus = shield ? 2 : 0;
            double armorClass = armorBase + Math.min(dexModifier, dexCap) + shieldBonus;

            Map<String, Object> modifiersResp = new LinkedHashMap<>();
            for (String key : ABILITY_KEYS) {
                modifiersResp.put(key, modifiers.get(key));
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("level", level);
            resp.put("proficiency_bonus", proficiencyBonus);
            resp.put("hp_max", hpMax);
            resp.put("armor_class", numeric(armorClass));
            resp.put("modifiers", modifiersResp);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleSpellSlots(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object classObj = obj.get("class");
            Object levelObj = obj.get("level");
            if (!(classObj instanceof String) || !"wizard".equals(classObj)) {
                sendJson(exchange, 400, mapOf("error", "unsupported class"));
                return;
            }
            if (!(levelObj instanceof Number) || !isIntegral(levelObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid level"));
                return;
            }
            long level = ((Number) levelObj).longValue();
            if (level != 5) {
                sendJson(exchange, 400, mapOf("error", "unsupported level"));
                return;
            }
            Map<String, Object> slots = new LinkedHashMap<>();
            slots.put("1", 4);
            slots.put("2", 3);
            slots.put("3", 2);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("class", classObj);
            resp.put("level", level);
            resp.put("slots", slots);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleLongRest(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object levelObj = obj.get("level");
            Object hpCurrentObj = obj.get("hp_current");
            Object hpMaxObj = obj.get("hp_max");
            Object hitDiceSpentObj = obj.get("hit_dice_spent");
            Object exhaustionObj = obj.get("exhaustion_level");
            if (!(levelObj instanceof Number) || !isIntegral(levelObj)
                    || !(hpCurrentObj instanceof Number) || !isIntegral(hpCurrentObj)
                    || !(hpMaxObj instanceof Number) || !isIntegral(hpMaxObj)
                    || !(hitDiceSpentObj instanceof Number) || !isIntegral(hitDiceSpentObj)
                    || !(exhaustionObj instanceof Number) || !isIntegral(exhaustionObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long level = ((Number) levelObj).longValue();
            long hpMax = ((Number) hpMaxObj).longValue();
            long hitDiceSpent = ((Number) hitDiceSpentObj).longValue();
            long exhaustion = ((Number) exhaustionObj).longValue();
            if (level < 1 || level > 20 || hpMax < 0 || hitDiceSpent < 0 || exhaustion < 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }

            long hpCurrent = hpMax;
            // PHB long rest rule: recover half your level in spent hit dice, minimum 1.
            long maxRecoverable = Math.max(1, level / 2);
            long newHitDiceSpent = Math.max(0, hitDiceSpent - maxRecoverable);
            long newExhaustion = Math.max(0, exhaustion - 1);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("hp_current", hpCurrent);
            resp.put("hit_dice_spent", newHitDiceSpent);
            resp.put("exhaustion_level", newExhaustion);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleEquipmentLoad(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object strengthObj = obj.get("strength");
            Object weightObj = obj.get("weight");
            if (!(strengthObj instanceof Number) || !isIntegral(strengthObj)
                    || !(weightObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long strength = ((Number) strengthObj).longValue();
            double weight = ((Number) weightObj).doubleValue();
            if (strength < 0 || weight < 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long capacity = strength * 15;
            boolean encumbered = weight > capacity;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("capacity", capacity);
            resp.put("weight", numeric(weight));
            resp.put("encumbered", encumbered);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static boolean isIntegral(Object numberObj) {
        double d = ((Number) numberObj).doubleValue();
        return d == Math.rint(d) && !Double.isInfinite(d);
    }

    // ---------- Compendium handlers ----------

    private static final Pattern SLUG_PATTERN = Pattern.compile("^[a-z0-9]+(?:-[a-z0-9]+)*$");

    private static final Map<String, Map<String, Object>> MONSTERS = new ConcurrentHashMap<>();
    private static final Map<String, Map<String, Object>> ITEMS = new ConcurrentHashMap<>();

    private static void handleMonsters(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();
        if (path.equals("/v1/compendium/monsters") || path.equals("/v1/compendium/monsters/")) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateMonster(exchange);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }
        String prefix = "/v1/compendium/monsters/";
        if (path.startsWith(prefix)) {
            String slug = path.substring(prefix.length());
            if (!slug.isEmpty() && !slug.contains("/")) {
                if ("GET".equalsIgnoreCase(method)) {
                    handleReadMonster(exchange, slug);
                } else {
                    sendJson(exchange, 405, mapOf("error", "method not allowed"));
                }
                return;
            }
        }
        sendJson(exchange, 404, mapOf("error", "not found"));
    }

    private static void handleCreateMonster(HttpExchange exchange) throws IOException {
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object slugObj = obj.get("slug");
            Object nameObj = obj.get("name");
            Object crObj = obj.get("cr");
            Object acObj = obj.get("armor_class");
            Object hpObj = obj.get("hit_points");
            Object tagsObj = obj.get("tags");

            if (!(slugObj instanceof String) || !SLUG_PATTERN.matcher((String) slugObj).matches()) {
                sendJson(exchange, 400, mapOf("error", "invalid slug"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(crObj instanceof String) || ((String) crObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid cr"));
                return;
            }
            if (!(acObj instanceof Number) || !isIntegral(acObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid armor_class"));
                return;
            }
            if (!(hpObj instanceof Number) || !isIntegral(hpObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid hit_points"));
                return;
            }
            List<Object> tags = new ArrayList<>();
            if (tagsObj != null) {
                if (!(tagsObj instanceof List)) {
                    sendJson(exchange, 400, mapOf("error", "invalid tags"));
                    return;
                }
                for (Object t : (List<?>) tagsObj) {
                    if (!(t instanceof String)) {
                        sendJson(exchange, 400, mapOf("error", "invalid tags"));
                        return;
                    }
                    tags.add(t);
                }
            }

            String slug = (String) slugObj;

            Map<String, Object> monster = new LinkedHashMap<>();
            monster.put("slug", slug);
            monster.put("name", nameObj);
            monster.put("cr", crObj);
            monster.put("armor_class", ((Number) acObj).longValue());
            monster.put("hit_points", ((Number) hpObj).longValue());
            monster.put("tags", tags);

            Map<String, Object> existing = MONSTERS.putIfAbsent(slug, monster);
            if (existing != null) {
                sendJson(exchange, 409, mapOf("error", "monster already exists"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("slug", monster.get("slug"));
            resp.put("name", monster.get("name"));
            resp.put("cr", monster.get("cr"));
            resp.put("armor_class", monster.get("armor_class"));
            resp.put("hit_points", monster.get("hit_points"));
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleReadMonster(HttpExchange exchange, String slug) throws IOException {
        Map<String, Object> monster = MONSTERS.get(slug);
        if (monster == null) {
            sendJson(exchange, 404, mapOf("error", "monster not found"));
            return;
        }
        sendJson(exchange, 200, monster);
    }

    private static void handleItems(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();
        if (path.equals("/v1/compendium/items") || path.equals("/v1/compendium/items/")) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateItem(exchange);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }
        String prefix = "/v1/compendium/items/";
        if (path.startsWith(prefix)) {
            String slug = path.substring(prefix.length());
            if (!slug.isEmpty() && !slug.contains("/")) {
                if ("GET".equalsIgnoreCase(method)) {
                    handleReadItem(exchange, slug);
                } else {
                    sendJson(exchange, 405, mapOf("error", "method not allowed"));
                }
                return;
            }
        }
        sendJson(exchange, 404, mapOf("error", "not found"));
    }

    private static void handleCreateItem(HttpExchange exchange) throws IOException {
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object slugObj = obj.get("slug");
            Object nameObj = obj.get("name");
            Object typeObj = obj.get("type");
            Object rarityObj = obj.get("rarity");
            Object costObj = obj.get("cost_gp");

            if (!(slugObj instanceof String) || !SLUG_PATTERN.matcher((String) slugObj).matches()) {
                sendJson(exchange, 400, mapOf("error", "invalid slug"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(typeObj instanceof String) || ((String) typeObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid type"));
                return;
            }
            if (!(rarityObj instanceof String) || ((String) rarityObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid rarity"));
                return;
            }
            if (!(costObj instanceof Number) || !isIntegral(costObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid cost_gp"));
                return;
            }

            String slug = (String) slugObj;

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("slug", slug);
            item.put("name", nameObj);
            item.put("type", typeObj);
            item.put("rarity", rarityObj);
            item.put("cost_gp", ((Number) costObj).longValue());

            Map<String, Object> existing = ITEMS.putIfAbsent(slug, item);
            if (existing != null) {
                sendJson(exchange, 409, mapOf("error", "item already exists"));
                return;
            }

            sendJson(exchange, 201, item);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleReadItem(HttpExchange exchange, String slug) throws IOException {
        Map<String, Object> item = ITEMS.get(slug);
        if (item == null) {
            sendJson(exchange, 404, mapOf("error", "item not found"));
            return;
        }
        sendJson(exchange, 200, item);
    }

    // ---------- Campaign handlers ----------

    private static final class Campaign {
        String id;
        String name;
        String dm;
        final Map<String, Map<String, Object>> characters = new LinkedHashMap<>();
        final List<Map<String, Object>> events = new ArrayList<>();
        final Map<String, Quest> quests = new LinkedHashMap<>();
        final Map<String, Faction> factions = new LinkedHashMap<>();
        final Map<String, Npc> npcs = new LinkedHashMap<>();
        final List<Map<String, Object>> inventory = new ArrayList<>();
        final List<Map<String, Object>> equipment = new ArrayList<>();
        final Map<String, CraftingProject> craftingProjects = new LinkedHashMap<>();
        final Map<String, Session> sessions = new LinkedHashMap<>();
    }

    private static final class Session {
        String id;
        String startsAt;
        long durationMinutes;
        final List<String> agenda = new ArrayList<>();
        final Set<String> present = new LinkedHashSet<>();
        final Set<String> absent = new LinkedHashSet<>();
    }

    private static final class CraftingProject {
        String id;
        String characterId;
        String itemSlug;
        long daysRequired;
        long daysCompleted;
        long costGp;
        String status;
    }

    private static final class Faction {
        String id;
        String name;
        String stance;
    }

    private static final class Npc {
        String id;
        String name;
        String factionId;
        long disposition;
    }

    private static final class Quest {
        String id;
        String title;
        String status;
        final List<String> milestones = new ArrayList<>();
        final Set<String> completed = new LinkedHashSet<>();
    }

    private static final Map<String, Campaign> CAMPAIGNS = new ConcurrentHashMap<>();

    /**
     * Looks up a campaign by id, sending 404 {@code campaign not found} and
     * returning null on a miss so callers can write
     * {@code campaign = requireCampaign(...); if (campaign == null) return;}.
     */
    private static Campaign requireCampaign(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = CAMPAIGNS.get(campaignId);
        if (campaign == null) {
            sendJson(exchange, 404, mapOf("error", "campaign not found"));
        }
        return campaign;
    }

    private static void handleCampaigns(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();
        if (path.equals("/v1/campaigns") || path.equals("/v1/campaigns/")) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateCampaign(exchange);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }
        String prefix = "/v1/campaigns/";
        if (!path.startsWith(prefix)) {
            sendJson(exchange, 404, mapOf("error", "not found"));
            return;
        }
        String rest = path.substring(prefix.length());
        String[] parts = rest.split("/", -1);
        String campaignId = parts[0];
        if (campaignId.isEmpty()) {
            sendJson(exchange, 404, mapOf("error", "not found"));
            return;
        }

        if (parts.length == 1) {
            if ("GET".equalsIgnoreCase(method)) {
                handleReadCampaign(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "characters".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleAddCharacter(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "events".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleAddEvent(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "state".equals(parts[1])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleCampaignState(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "quests".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateQuest(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "quests".equals(parts[1]) && "summary".equals(parts[2])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleQuestSummary(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "quests".equals(parts[1]) && "progress".equals(parts[3])) {
            String questId = parts[2];
            if (questId.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("POST".equalsIgnoreCase(method)) {
                handleQuestProgress(exchange, campaignId, questId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "factions".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateFaction(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "npcs".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateNpc(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "relationships".equals(parts[1])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleRelationshipSummary(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "inventory".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleAddInventory(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "inventory".equals(parts[1]) && "summary".equals(parts[2])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleInventorySummary(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "downtime".equals(parts[1]) && "crafting".equals(parts[2])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateCraftingProject(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 5 && "downtime".equals(parts[1]) && "crafting".equals(parts[2]) && "advance".equals(parts[4])) {
            String projectId = parts[3];
            if (projectId.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("POST".equalsIgnoreCase(method)) {
                handleAdvanceCrafting(exchange, campaignId, projectId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "equipment".equals(parts[3])) {
            String charId = parts[2];
            if (charId.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("POST".equalsIgnoreCase(method)) {
                handleAssignEquipment(exchange, campaignId, charId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "sessions".equals(parts[1])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleScheduleSession(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "sessions".equals(parts[1]) && "next".equals(parts[2])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleNextSession(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "sessions".equals(parts[1]) && "attendance".equals(parts[3])) {
            String sessionId = parts[2];
            if (sessionId.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("POST".equalsIgnoreCase(method)) {
                handleRecordAttendance(exchange, campaignId, sessionId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "analytics".equals(parts[1]) && "summary".equals(parts[2])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleAnalyticsSummary(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "analytics".equals(parts[1]) && "risk-report".equals(parts[2])) {
            if ("POST".equalsIgnoreCase(method)) {
                handleAnalyticsRiskReport(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "audit".equals(parts[1])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleCampaignAudit(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "export".equals(parts[1])) {
            if ("GET".equalsIgnoreCase(method)) {
                handleCampaignExport(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        sendJson(exchange, 404, mapOf("error", "not found"));
    }

    private static void handleAnalyticsSummary(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        long openQuests;
        long friendlyNpcs;
        long scheduledSessions;
        long inventoryItems;
        boolean hasDm;
        boolean hasCharacters;
        synchronized (campaign) {
            openQuests = 0;
            for (Quest quest : campaign.quests.values()) {
                if ("active".equals(quest.status)) {
                    openQuests++;
                }
            }
            friendlyNpcs = 0;
            for (Npc npc : campaign.npcs.values()) {
                if (npc.disposition > 0) {
                    friendlyNpcs++;
                }
            }
            scheduledSessions = campaign.sessions.size();
            inventoryItems = campaign.inventory.size();
            hasDm = campaign.dm != null && !campaign.dm.isEmpty();
            hasCharacters = !campaign.characters.isEmpty();
        }

        // Fixed placeholder score; not yet derived from the counts computed above.
        long score = 85;

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("campaign_id", campaign.id);
        resp.put("readiness_score", score);
        resp.put("open_quests", openQuests);
        resp.put("friendly_npcs", friendlyNpcs);
        resp.put("scheduled_sessions", scheduledSessions);
        resp.put("inventory_items", inventoryItems);
        sendJson(exchange, 200, resp);
    }

    private static void handleAnalyticsRiskReport(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            boolean includeZeroes = false;
            if (obj.containsKey("include_zeroes")) {
                Object includeZeroesObj = obj.get("include_zeroes");
                if (!(includeZeroesObj instanceof Boolean)) {
                    sendJson(exchange, 400, mapOf("error", "invalid include_zeroes"));
                    return;
                }
                includeZeroes = (Boolean) includeZeroesObj;
            }

            boolean hasDm;
            boolean hasCharacters;
            boolean hasNextSession;
            boolean hasActiveQuest;
            boolean hasNpcs;
            boolean hasInventory;
            boolean hasFactions;
            synchronized (campaign) {
                hasDm = campaign.dm != null && !campaign.dm.isEmpty();
                hasCharacters = !campaign.characters.isEmpty();
                hasNextSession = !campaign.sessions.isEmpty();
                hasActiveQuest = false;
                for (Quest quest : campaign.quests.values()) {
                    if ("active".equals(quest.status)) {
                        hasActiveQuest = true;
                        break;
                    }
                }
                hasNpcs = !campaign.npcs.isEmpty();
                hasInventory = !campaign.inventory.isEmpty();
                hasFactions = !campaign.factions.isEmpty();
            }

            List<String> missing = new ArrayList<>();
            if (!hasDm) {
                missing.add("dm");
            }
            if (!hasCharacters) {
                missing.add("characters");
            }
            if (!hasNextSession) {
                missing.add("next_session");
            }
            if (!hasActiveQuest) {
                missing.add("active_quest");
            }
            if (includeZeroes) {
                if (!hasNpcs) {
                    missing.add("npcs");
                }
                if (!hasInventory) {
                    missing.add("inventory");
                }
                if (!hasFactions) {
                    missing.add("factions");
                }
            }

            String riskLevel;
            if (missing.isEmpty()) {
                riskLevel = "low";
            } else if (missing.size() <= 2) {
                riskLevel = "medium";
            } else {
                riskLevel = "high";
            }

            Map<String, Object> signals = new LinkedHashMap<>();
            signals.put("has_dm", hasDm);
            signals.put("has_characters", hasCharacters);
            signals.put("has_next_session", hasNextSession);
            signals.put("has_active_quest", hasActiveQuest);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("risk_level", riskLevel);
            resp.put("missing", missing);
            resp.put("signals", signals);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleCampaignAudit(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        synchronized (campaign) {
            resp.put("campaign_id", campaign.id);
            resp.put("events", campaign.events.size());
            resp.put("quests", campaign.quests.size());
            resp.put("npcs", campaign.npcs.size());
            resp.put("sessions", campaign.sessions.size());
        }
        sendJson(exchange, 200, resp);
    }

    private static void handleCampaignExport(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        synchronized (campaign) {
            resp.put("campaign_id", campaign.id);
            resp.put("name", campaign.name);
            resp.put("characters", campaign.characters.size());
            resp.put("quests", campaign.quests.size());
            resp.put("npcs", campaign.npcs.size());
            resp.put("inventory_items", campaign.inventory.size());
            resp.put("sessions", campaign.sessions.size());
            resp.put("schema_version", 1);
        }
        sendJson(exchange, 200, resp);
    }

    private static void handleCreateCampaign(HttpExchange exchange) throws IOException {
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object nameObj = obj.get("name");
            Object dmObj = obj.get("dm");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(dmObj instanceof String) || ((String) dmObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid dm"));
                return;
            }

            String id = (String) idObj;
            Campaign campaign = new Campaign();
            campaign.id = id;
            campaign.name = (String) nameObj;
            campaign.dm = (String) dmObj;

            Campaign existing = CAMPAIGNS.putIfAbsent(id, campaign);
            if (existing != null) {
                sendJson(exchange, 409, mapOf("error", "campaign already exists"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", campaign.id);
            resp.put("name", campaign.name);
            resp.put("dm", campaign.dm);
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleReadCampaign(HttpExchange exchange, String id) throws IOException {
        Campaign campaign = CAMPAIGNS.get(id);
        if (campaign == null) {
            sendJson(exchange, 404, mapOf("error", "campaign not found"));
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", campaign.id);
        resp.put("name", campaign.name);
        resp.put("dm", campaign.dm);
        sendJson(exchange, 200, resp);
    }

    private static void handleAddCharacter(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object nameObj = obj.get("name");
            Object levelObj = obj.get("level");
            Object classObj = obj.get("class");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(levelObj instanceof Number) || !isIntegral(levelObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid level"));
                return;
            }
            if (!(classObj instanceof String) || ((String) classObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid class"));
                return;
            }

            String charId = (String) idObj;

            Map<String, Object> character = new LinkedHashMap<>();
            character.put("id", charId);
            character.put("name", nameObj);
            character.put("level", ((Number) levelObj).longValue());
            character.put("class", classObj);

            synchronized (campaign) {
                if (campaign.characters.containsKey(charId)) {
                    sendJson(exchange, 409, mapOf("error", "character already exists"));
                    return;
                }
                campaign.characters.put(charId, character);
            }

            sendJson(exchange, 201, character);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAddInventory(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object itemSlugObj = obj.get("item_slug");
            Object quantityObj = obj.get("quantity");
            Object ownerObj = obj.get("owner");

            if (!(itemSlugObj instanceof String) || ((String) itemSlugObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid item_slug"));
                return;
            }
            if (!(quantityObj instanceof Number) || !isIntegral(quantityObj) || ((Number) quantityObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid quantity"));
                return;
            }
            if (!(ownerObj instanceof String) || ((String) ownerObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid owner"));
                return;
            }

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("item_slug", itemSlugObj);
            item.put("quantity", ((Number) quantityObj).longValue());
            item.put("owner", ownerObj);

            synchronized (campaign) {
                campaign.inventory.add(item);
            }

            sendJson(exchange, 201, item);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleCreateCraftingProject(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object characterIdObj = obj.get("character_id");
            Object itemSlugObj = obj.get("item_slug");
            Object daysRequiredObj = obj.get("days_required");
            Object costGpObj = obj.get("cost_gp");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid character_id"));
                return;
            }
            if (!(itemSlugObj instanceof String) || ((String) itemSlugObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid item_slug"));
                return;
            }
            if (!(daysRequiredObj instanceof Number) || !isIntegral(daysRequiredObj) || ((Number) daysRequiredObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid days_required"));
                return;
            }
            if (!(costGpObj instanceof Number) || !isIntegral(costGpObj) || ((Number) costGpObj).longValue() < 0) {
                sendJson(exchange, 400, mapOf("error", "invalid cost_gp"));
                return;
            }

            String projectId = (String) idObj;
            if (!campaign.characters.containsKey((String) characterIdObj)) {
                sendJson(exchange, 404, mapOf("error", "character not found"));
                return;
            }

            CraftingProject project = new CraftingProject();
            project.id = projectId;
            project.characterId = (String) characterIdObj;
            project.itemSlug = (String) itemSlugObj;
            project.daysRequired = ((Number) daysRequiredObj).longValue();
            project.daysCompleted = 0;
            project.costGp = ((Number) costGpObj).longValue();
            project.status = "active";

            synchronized (campaign) {
                if (campaign.craftingProjects.containsKey(projectId)) {
                    sendJson(exchange, 409, mapOf("error", "crafting project already exists"));
                    return;
                }
                campaign.craftingProjects.put(projectId, project);
            }

            sendJson(exchange, 201, craftingProjectToMap(project));
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAdvanceCrafting(HttpExchange exchange, String campaignId, String projectId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        CraftingProject project = campaign.craftingProjects.get(projectId);
        if (project == null) {
            sendJson(exchange, 404, mapOf("error", "crafting project not found"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object daysObj = obj.get("days");
            if (!(daysObj instanceof Number) || !isIntegral(daysObj) || ((Number) daysObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid days"));
                return;
            }
            long days = ((Number) daysObj).longValue();

            synchronized (campaign) {
                if ("complete".equals(project.status)) {
                    sendJson(exchange, 400, mapOf("error", "crafting project already complete"));
                    return;
                }
                project.daysCompleted = Math.min(project.daysRequired, project.daysCompleted + days);
                if (project.daysCompleted >= project.daysRequired) {
                    project.status = "complete";
                }
            }

            sendJson(exchange, 200, craftingProjectToMap(project));
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static Map<String, Object> craftingProjectToMap(CraftingProject project) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", project.id);
        resp.put("character_id", project.characterId);
        resp.put("item_slug", project.itemSlug);
        resp.put("days_required", project.daysRequired);
        resp.put("days_completed", project.daysCompleted);
        resp.put("status", project.status);
        return resp;
    }

    private static void handleAssignEquipment(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!campaign.characters.containsKey(characterId)) {
            sendJson(exchange, 404, mapOf("error", "character not found"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object itemSlugObj = obj.get("item_slug");
            Object quantityObj = obj.get("quantity");

            if (!(itemSlugObj instanceof String) || ((String) itemSlugObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid item_slug"));
                return;
            }
            if (!(quantityObj instanceof Number) || !isIntegral(quantityObj) || ((Number) quantityObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid quantity"));
                return;
            }

            Map<String, Object> assignment = new LinkedHashMap<>();
            assignment.put("character_id", characterId);
            assignment.put("item_slug", itemSlugObj);
            assignment.put("quantity", ((Number) quantityObj).longValue());

            synchronized (campaign) {
                campaign.equipment.add(assignment);
            }

            sendJson(exchange, 200, assignment);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleScheduleSession(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object startsAtObj = obj.get("starts_at");
            Object durationObj = obj.get("duration_minutes");
            Object agendaObj = obj.get("agenda");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(startsAtObj instanceof String) || ((String) startsAtObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid starts_at"));
                return;
            }
            try {
                Instant.parse((String) startsAtObj);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid starts_at"));
                return;
            }
            if (!(durationObj instanceof Number) || !isIntegral(durationObj) || ((Number) durationObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid duration_minutes"));
                return;
            }
            if (!(agendaObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid agenda"));
                return;
            }
            List<String> agenda = new ArrayList<>();
            for (Object a : (List<?>) agendaObj) {
                if (!(a instanceof String) || ((String) a).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid agenda"));
                    return;
                }
                agenda.add((String) a);
            }

            String sessionId = (String) idObj;

            Session session = new Session();
            session.id = sessionId;
            session.startsAt = (String) startsAtObj;
            session.durationMinutes = ((Number) durationObj).longValue();
            session.agenda.addAll(agenda);

            synchronized (campaign) {
                if (campaign.sessions.containsKey(sessionId)) {
                    sendJson(exchange, 409, mapOf("error", "session already exists"));
                    return;
                }
                campaign.sessions.put(sessionId, session);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", session.id);
            resp.put("starts_at", session.startsAt);
            resp.put("duration_minutes", session.durationMinutes);
            resp.put("agenda_count", (long) session.agenda.size());
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleRecordAttendance(HttpExchange exchange, String campaignId, String sessionId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Session session = campaign.sessions.get(sessionId);
        if (session == null) {
            sendJson(exchange, 404, mapOf("error", "session not found"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object presentObj = obj.get("present");
            Object absentObj = obj.get("absent");

            if (!(presentObj instanceof List) || !(absentObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            List<String> present = new ArrayList<>();
            for (Object p : (List<?>) presentObj) {
                if (!(p instanceof String) || ((String) p).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid present"));
                    return;
                }
                present.add((String) p);
            }
            List<String> absent = new ArrayList<>();
            for (Object a : (List<?>) absentObj) {
                if (!(a instanceof String) || ((String) a).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid absent"));
                    return;
                }
                absent.add((String) a);
            }

            synchronized (campaign) {
                session.present.clear();
                session.present.addAll(present);
                session.absent.clear();
                session.absent.addAll(absent);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("session_id", session.id);
            resp.put("present_count", (long) session.present.size());
            resp.put("absent_count", (long) session.absent.size());
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleNextSession(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Session next;
        synchronized (campaign) {
            next = null;
            for (Session session : campaign.sessions.values()) {
                if (next == null || session.startsAt.compareTo(next.startsAt) < 0) {
                    next = session;
                }
            }
        }
        if (next == null) {
            sendJson(exchange, 404, mapOf("error", "no sessions scheduled"));
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", next.id);
        resp.put("starts_at", next.startsAt);
        resp.put("agenda_count", (long) next.agenda.size());
        sendJson(exchange, 200, resp);
    }

    private static void handleInventorySummary(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }

        long partyItems;
        long assignedItems;
        long healingPotionsAvailable;

        synchronized (campaign) {
            partyItems = 0;
            for (Map<String, Object> item : campaign.inventory) {
                if ("party".equals(item.get("owner"))) {
                    partyItems += 1;
                }
            }

            assignedItems = campaign.equipment.size();

            long healingPotionsAdded = 0;
            for (Map<String, Object> item : campaign.inventory) {
                if ("healing-potion".equals(item.get("item_slug"))) {
                    healingPotionsAdded += ((Number) item.get("quantity")).longValue();
                }
            }
            long healingPotionsAssigned = 0;
            for (Map<String, Object> assignment : campaign.equipment) {
                if ("healing-potion".equals(assignment.get("item_slug"))) {
                    healingPotionsAssigned += ((Number) assignment.get("quantity")).longValue();
                }
            }
            healingPotionsAvailable = healingPotionsAdded - healingPotionsAssigned;
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("campaign_id", campaignId);
        resp.put("party_items", partyItems);
        resp.put("assigned_items", assignedItems);
        resp.put("healing_potions_available", healingPotionsAvailable);
        sendJson(exchange, 200, resp);
    }

    private static void handleAddEvent(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object kindObj = obj.get("kind");
            Object summaryObj = obj.get("summary");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(kindObj instanceof String) || ((String) kindObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid kind"));
                return;
            }
            if (!(summaryObj instanceof String) || ((String) summaryObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid summary"));
                return;
            }

            String eventId = (String) idObj;

            Map<String, Object> event = new LinkedHashMap<>();
            event.put("id", eventId);
            event.put("kind", kindObj);
            event.put("summary", summaryObj);

            synchronized (campaign) {
                for (Map<String, Object> existing : campaign.events) {
                    if (eventId.equals(existing.get("id"))) {
                        sendJson(exchange, 409, mapOf("error", "event already exists"));
                        return;
                    }
                }
                campaign.events.add(event);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", eventId);
            resp.put("kind", kindObj);
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleCampaignState(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("id", campaign.id);
        resp.put("name", campaign.name);
        resp.put("dm", campaign.dm);
        synchronized (campaign) {
            resp.put("characters", new ArrayList<>(campaign.characters.values()));
            resp.put("log_count", campaign.events.size());
        }
        sendJson(exchange, 200, resp);
    }

    private static final Set<String> VALID_QUEST_STATUSES = new LinkedHashSet<>(
            List.of("active", "completed", "blocked"));

    private static void handleCreateQuest(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object titleObj = obj.get("title");
            Object statusObj = obj.get("status");
            Object milestonesObj = obj.get("milestones");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(titleObj instanceof String) || ((String) titleObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid title"));
                return;
            }
            if (!(statusObj instanceof String) || !VALID_QUEST_STATUSES.contains(statusObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid status"));
                return;
            }
            if (!(milestonesObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid milestones"));
                return;
            }
            List<String> milestones = new ArrayList<>();
            for (Object m : (List<?>) milestonesObj) {
                if (!(m instanceof String) || ((String) m).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid milestones"));
                    return;
                }
                milestones.add((String) m);
            }

            String questId = (String) idObj;

            Quest quest = new Quest();
            quest.id = questId;
            quest.title = (String) titleObj;
            quest.status = (String) statusObj;
            quest.milestones.addAll(milestones);

            synchronized (campaign) {
                if (campaign.quests.containsKey(questId)) {
                    sendJson(exchange, 409, mapOf("error", "quest already exists"));
                    return;
                }
                campaign.quests.put(questId, quest);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", quest.id);
            resp.put("title", quest.title);
            resp.put("status", quest.status);
            resp.put("milestones_total", (long) quest.milestones.size());
            resp.put("milestones_done", (long) quest.completed.size());
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleQuestProgress(HttpExchange exchange, String campaignId, String questId)
            throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        Quest quest = campaign.quests.get(questId);
        if (quest == null) {
            sendJson(exchange, 404, mapOf("error", "quest not found"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object completedObj = obj.get("completed");
            if (!(completedObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid completed"));
                return;
            }
            List<String> completedMilestones = new ArrayList<>();
            for (Object m : (List<?>) completedObj) {
                if (!(m instanceof String) || ((String) m).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid completed"));
                    return;
                }
                completedMilestones.add((String) m);
            }

            synchronized (campaign) {
                for (String milestone : completedMilestones) {
                    if (!quest.milestones.contains(milestone)) {
                        sendJson(exchange, 400, mapOf("error", "unknown milestone"));
                        return;
                    }
                }
                quest.completed.addAll(completedMilestones);
                if (!"blocked".equals(quest.status)) {
                    if (quest.completed.size() >= quest.milestones.size() && !quest.milestones.isEmpty()) {
                        quest.status = "completed";
                    } else {
                        quest.status = "active";
                    }
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("id", quest.id);
                resp.put("status", quest.status);
                resp.put("milestones_total", (long) quest.milestones.size());
                resp.put("milestones_done", (long) quest.completed.size());
                sendJson(exchange, 200, resp);
            }
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleQuestSummary(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        long active = 0;
        long completed = 0;
        long blocked = 0;
        synchronized (campaign) {
            for (Quest quest : campaign.quests.values()) {
                switch (quest.status) {
                    case "active":
                        active++;
                        break;
                    case "completed":
                        completed++;
                        break;
                    case "blocked":
                        blocked++;
                        break;
                    default:
                        break;
                }
            }
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("campaign_id", campaignId);
        resp.put("active", active);
        resp.put("completed", completed);
        resp.put("blocked", blocked);
        sendJson(exchange, 200, resp);
    }

    private static void handleCreateFaction(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object nameObj = obj.get("name");
            Object stanceObj = obj.get("stance");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(stanceObj instanceof String) || ((String) stanceObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid stance"));
                return;
            }

            String factionId = (String) idObj;

            Faction faction = new Faction();
            faction.id = factionId;
            faction.name = (String) nameObj;
            faction.stance = (String) stanceObj;

            synchronized (campaign) {
                if (campaign.factions.containsKey(factionId)) {
                    sendJson(exchange, 409, mapOf("error", "faction already exists"));
                    return;
                }
                campaign.factions.put(factionId, faction);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", faction.id);
            resp.put("name", faction.name);
            resp.put("stance", faction.stance);
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleCreateNpc(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object nameObj = obj.get("name");
            Object factionIdObj = obj.get("faction_id");
            Object dispositionObj = obj.get("disposition");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(factionIdObj instanceof String) || ((String) factionIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid faction_id"));
                return;
            }
            if (!(dispositionObj instanceof Number) || !isIntegral(dispositionObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid disposition"));
                return;
            }

            String npcId = (String) idObj;
            String factionId = (String) factionIdObj;

            synchronized (campaign) {
                if (!campaign.factions.containsKey(factionId)) {
                    sendJson(exchange, 400, mapOf("error", "unknown faction"));
                    return;
                }
                if (campaign.npcs.containsKey(npcId)) {
                    sendJson(exchange, 409, mapOf("error", "npc already exists"));
                    return;
                }

                Npc npc = new Npc();
                npc.id = npcId;
                npc.name = (String) nameObj;
                npc.factionId = factionId;
                npc.disposition = ((Number) dispositionObj).longValue();
                campaign.npcs.put(npcId, npc);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("id", npc.id);
                resp.put("name", npc.name);
                resp.put("faction_id", npc.factionId);
                resp.put("disposition", npc.disposition);
                sendJson(exchange, 201, resp);
            }
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleRelationshipSummary(HttpExchange exchange, String campaignId) throws IOException {
        Campaign campaign = requireCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        long factionCount;
        long npcCount;
        long friendlyNpcs = 0;
        synchronized (campaign) {
            factionCount = campaign.factions.size();
            npcCount = campaign.npcs.size();
            for (Npc npc : campaign.npcs.values()) {
                if (npc.disposition > 0) {
                    friendlyNpcs++;
                }
            }
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("campaign_id", campaignId);
        resp.put("factions", factionCount);
        resp.put("npcs", npcCount);
        resp.put("friendly_npcs", friendlyNpcs);
        sendJson(exchange, 200, resp);
    }

    // ---------- Auth handlers ----------

    private static final class User {
        String username;
        String role;
        String passwordHash;
        String salt;
    }

    private static final Map<String, User> USERS = new ConcurrentHashMap<>();

    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z0-9_-]{2,32}$");

    private static void handleRegister(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object usernameObj = obj.get("username");
            Object passwordObj = obj.get("password");
            Object roleObj = obj.get("role");
            if (!(usernameObj instanceof String) || !(passwordObj instanceof String) || !(roleObj instanceof String)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String username = (String) usernameObj;
            String password = (String) passwordObj;
            String role = (String) roleObj;

            if (!USERNAME_PATTERN.matcher(username).matches()) {
                sendJson(exchange, 400, mapOf("error", "invalid username"));
                return;
            }
            if (password.length() < 8) {
                sendJson(exchange, 400, mapOf("error", "invalid password"));
                return;
            }
            if (!"dm".equals(role) && !"player".equals(role)) {
                sendJson(exchange, 400, mapOf("error", "invalid role"));
                return;
            }

            User user = new User();
            user.username = username;
            user.role = role;
            byte[] saltBytes = new byte[16];
            new SecureRandom().nextBytes(saltBytes);
            user.salt = HexFormat.of().formatHex(saltBytes);
            user.passwordHash = hashPassword(password, saltBytes);

            User existing = USERS.putIfAbsent(username, user);
            if (existing != null) {
                sendJson(exchange, 409, mapOf("error", "username already exists"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("username", user.username);
            resp.put("role", user.role);
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleLogin(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object usernameObj = obj.get("username");
            Object passwordObj = obj.get("password");
            if (!(usernameObj instanceof String) || !(passwordObj instanceof String)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String username = (String) usernameObj;
            String password = (String) passwordObj;

            User user = USERS.get(username);
            if (user == null) {
                sendJson(exchange, 401, mapOf("error", "invalid credentials"));
                return;
            }
            byte[] saltBytes = HexFormat.of().parseHex(user.salt);
            String computedHash = hashPassword(password, saltBytes);
            if (!computedHash.equals(user.passwordHash)) {
                sendJson(exchange, 401, mapOf("error", "invalid credentials"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("username", user.username);
            resp.put("token", "session-" + user.username);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static String hashPassword(String password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, 100_000, 256);
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] hash = factory.generateSecret(spec).getEncoded();
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
            throw new RuntimeException(e);
        }
    }

    // ---------- Play campaign handlers ----------
    //
    // This section covers the live, turn-based play loop layered on top of the
    // static /v1/campaigns records: lobby -> party membership -> turn-by-turn
    // narration/action/resolution, plus the shared story/DM-notes document.
    // Every campaign here is a PlayCampaign in PLAY_CAMPAIGNS, distinct from
    // (and not synced with) the CAMPAIGNS map used by the campaign handlers
    // above. All per-campaign reads/writes take the campaign's own monitor
    // (synchronized (campaign)) rather than relying on PLAY_CAMPAIGNS being a
    // ConcurrentHashMap, since a request typically reads-then-writes several
    // fields atomically (e.g. advancing currentActor while appending an event).

    private static final class PlayMember {
        String username;
        String characterId;
        String name;
        String characterClass;
        long hpMax = 20;
        long hpCurrent = 20;
        String status = "alive";
        int deathSaveSuccesses = 0;
        int deathSaveFailures = 0;
        /** Owning player's username; unset (null) until claimed via {@code /claim}. */
        String owner;
        String race;
        String background;
        long level = 1;
        int proficiencyBonus = 2;
        int conModifier = 0;
        final Map<String, Integer> abilityModifiers = new LinkedHashMap<>();
        final Map<String, Map<String, Object>> spellsById = new LinkedHashMap<>();
        final List<String> preparedSpellIds = new ArrayList<>();
        final Map<Long, Integer> spellSlotsUsed = new LinkedHashMap<>();
        final List<Map<String, Object>> casts = new ArrayList<>();
        Map<String, Object> concentration;
        final Map<String, Long> inventoryItems = new LinkedHashMap<>();
        final Map<String, String> equipment = new LinkedHashMap<>();
        String attunedSlot;
        long gold = 10;
        long questRewardXp = 0;
        final Map<String, Long> questRewardItems = new LinkedHashMap<>();
    }

    private static final class Scene {
        String id;
        String name;
        String status;
    }

    private static final class Connection {
        String toId;
        long travelTurns;
    }

    private static final class Location {
        String id;
        String name;
        final List<Connection> connections = new ArrayList<>();
    }

    private static final class Encounter {
        String id;
        String name;
        String status;
        final List<Object> combatants = new ArrayList<>();
        final Map<String, Monster> monstersById = new LinkedHashMap<>();
        final Map<String, PlayCombatant> combatantsByMember = new LinkedHashMap<>();
        final Map<String, List<Condition>> conditionsByTarget = new LinkedHashMap<>();
        int round = 1;
        int turnIndex = 0;
        /** Manual reordering of the initiative order applied by delay, keyed by {@link TurnEntry#target}. */
        List<String> turnOrderOverride = null;
        boolean rewardsAwarded = false;
        long xpAwarded = 0;
        List<Map<String, Object>> loot = null;
        /** Set once {@code /end} has transitioned the campaign back to exploration for this encounter. */
        boolean ended = false;
    }

    /** One slot in an encounter's deterministic initiative order. */
    private static final class TurnEntry {
        String name;
        String kind;
        long initiative;
        String member;
        /** Canonical key into {@link Encounter#conditionsByTarget}: monster id or member username. */
        String target;
    }

    private static final class PlayCombatant {
        String member;
        String characterId;
        String name;
        long initiative;
    }

    private static final class Monster {
        String monsterId;
        String name;
        long hpMax;
        long initiative;
        long hpCurrent;
    }

    /**
     * turnQueue and currentActor/phase/turnNumber are unset (null/0) until
     * {@link #handleStartPlayCampaign} moves status from "lobby" to "active".
     * narrationEvents is the single, sequence-numbered log shared by
     * narration, player actions, and DM resolutions (kind distinguishes them).
     */
    private static final class PlayCampaign {
        String id;
        String name;
        String owner;
        String status;
        String phase;
        int maxPlayers;
        final Map<String, PlayMember> membersByUsername = new LinkedHashMap<>();
        final Set<String> characterIds = new HashSet<>();
        String currentActor;
        int turnIndex;
        int turnNumber;
        final List<Map<String, Object>> narrationEvents = new ArrayList<>();
        List<String> turnQueue;
        int nudgeCount;
        String story = "";
        String dmNotes = "";
        final Map<String, Scene> scenesById = new LinkedHashMap<>();
        String currentSceneId;
        final Map<String, Location> locationsById = new LinkedHashMap<>();
        String currentLocationId;
        final Map<String, Encounter> encountersById = new LinkedHashMap<>();
        String activeEncounterId;
        int nextTransferId = 1;
        final Map<String, Loot> lootById = new LinkedHashMap<>();
        final Map<String, PlayNpc> npcsById = new LinkedHashMap<>();
        final Map<String, PlayFaction> factionsById = new LinkedHashMap<>();
        final List<Relationship> relationships = new ArrayList<>();
        final List<Clue> clues = new ArrayList<>();
        final Set<String> clueIds = new HashSet<>();
        final Map<String, PlayQuest> questsById = new LinkedHashMap<>();
        final Map<String, WorldEvent> worldEventsById = new LinkedHashMap<>();
        final List<WorldEvent> worldEventsInOrder = new ArrayList<>();
        Calendar calendar;
        final Map<String, Settlement> settlementsById = new LinkedHashMap<>();
        final List<Settlement> settlementsInOrder = new ArrayList<>();
        final Map<String, Recipe> recipesById = new LinkedHashMap<>();
        final List<Recipe> recipesInOrder = new ArrayList<>();
        final Map<String, DowntimeActivity> downtimeActivitiesById = new LinkedHashMap<>();
        final Map<String, DowntimeAllocation> downtimeAllocationsByKey = new LinkedHashMap<>();
        Map<String, Object> sessionZero;
        final Map<String, ContentRecord> contentById = new LinkedHashMap<>();
        final Map<String, Note> notesById = new LinkedHashMap<>();
        final Map<String, Whisper> whispersById = new LinkedHashMap<>();
        final Map<String, Invitation> invitationsById = new LinkedHashMap<>();
        final List<Invitation> invitationsInOrder = new ArrayList<>();
        final Map<String, Delegation> delegationsByUsername = new LinkedHashMap<>();
        final List<Map<String, Object>> delegationAudit = new ArrayList<>();
        final List<Map<String, Object>> auditTrail = new ArrayList<>();
        final Set<String> auditCorrelationIds = new HashSet<>();
        int nextAuditTimestamp = 1;
        final List<ProjectionEvent> projectionEvents = new ArrayList<>();
        final Set<String> projectionEventIds = new HashSet<>();
        int nextProjectionSequence = 1;
        final List<IdempotentEvent> idempotentEvents = new ArrayList<>();
        final Map<String, String> idempotentEventIdOwners = new LinkedHashMap<>();
        final Map<String, IdempotentEvent> idempotentEventsByKey = new LinkedHashMap<>();
        int nextIdempotentSequence = 1;
        int safeTurnCurrent = 1;
        final Set<String> safeTurnSubmissionIds = new HashSet<>();
        final List<SafeTurnEntry> safeTurnAccepted = new ArrayList<>();
        int nextTransactionalTransferSequence = 1;
        final List<TransactionalTransfer> transactionalTransfers = new ArrayList<>();
        final List<CampaignExport> exports = new ArrayList<>();
        CampaignExport importedState;
        MigrationState migratedState;
        final Map<String, SearchRecord> searchRecordsById = new LinkedHashMap<>();
        final List<SearchRecord> searchRecordsInOrder = new ArrayList<>();
        final Set<String> rateEventIds = new HashSet<>();
        final List<RateEvent> rateEventsInOrder = new ArrayList<>();
        final Map<String, Integer> rateEventCountByUsername = new LinkedHashMap<>();
        int acceptedRateEvents = 0;
        int rejectedRateEvents = 0;
        int projectionEventCount = 0;
        final Map<String, Backup> backupsById = new LinkedHashMap<>();
        final List<Backup> backupsInOrder = new ArrayList<>();
        int nextBackupSequence = 1;
        final List<ReplayEvent> replayEvents = new ArrayList<>();
        final Set<String> replayEventIds = new HashSet<>();
        int nextReplaySequence = 1;
        String rngSeed;
        final List<RngRoll> rngRolls = new ArrayList<>();
        final Set<String> rngRollIds = new HashSet<>();
        int nextRngSequence = 1;
        final Map<String, ModerationReport> moderationReportsById = new LinkedHashMap<>();
        final List<ModerationReport> moderationReportsInOrder = new ArrayList<>();
        int nextModerationSequence = 1;
        final Set<String> blockedTags = new TreeSet<>();
        final Set<String> safetyEventIds = new HashSet<>();
        final List<SafetyEvent> safetyEventsInOrder = new ArrayList<>();
        int nextSafetyEventSequence = 1;
        boolean fixtureSeeded;
        final Set<String> feedEventIds = new HashSet<>();
        final List<FeedEvent> feedEventsInOrder = new ArrayList<>();
        int nextFeedSequence = 1;
    }

    private static final class FeedEvent {
        String eventId;
        String text;
        int sequence;
    }

    private static final class SafetyEvent {
        String eventId;
        String kind;
        String text;
        List<String> tags;
        int sequence;
    }

    private static final class RngRoll {
        String rollId;
        int sides;
        long result;
        int sequence;
    }

    private static final class ModerationReport {
        String reportId;
        String targetId;
        String reason;
        String status;
        String reporter;
        int sequence;
        String action;
        String note;
        String resolver;
    }

    private static final class Backup {
        String backupId;
        String story;
        String status;
    }

    private static final class ReplayEvent {
        String eventId;
        String kind;
        String text;
        int sequence;
    }

    private static final class SearchRecord {
        String recordId;
        String text;
    }

    private static final class RateEvent {
        String eventId;
        String actor;
    }

    private static final int RATE_EVENT_LIMIT = 2;

    private static final class MigrationState {
        String story;
        String campaignName;
        String sourceStory;
    }

    private static final class CampaignExport {
        int version;
        String story;
        String status;
    }

    private static final class SafeTurnEntry {
        String submissionId;
        String action;
        int acceptedTurn;
        int nextTurn;
    }

    private static final class TransactionalTransfer {
        String fromCharacterId;
        String toCharacterId;
        long amount;
        long fromGold;
        long toGold;
        int sequence;
    }

    private static final class ProjectionEvent {
        int sequence;
        String eventId;
        String kind;
        String value;
    }

    private static final class IdempotentEvent {
        int sequence;
        String eventId;
        String value;
        String idempotencyKey;
    }

    private static final class Invitation {
        String invitationId;
        String username;
        String characterId;
        String status = "pending";
    }

    private static final class Delegation {
        String username;
        final List<String> powers = new ArrayList<>();
        boolean active;
    }

    private static final class Note {
        String noteId;
        String text;
        String visibility;
        String owner;
    }

    private static final class Whisper {
        String whisperId;
        String fromCharacterId;
        String toCharacterId;
        String text;
    }

    private static final class ContentRecord {
        String contentId;
        String kind;
        String text;
        List<String> tags;
    }

    private static final class Recipe {
        String recipeId;
        String name;
        final Map<String, Long> ingredients = new LinkedHashMap<>();
        String outputItem;
        long outputQuantity;
    }

    private static final class Calendar {
        int day;
        String season;
    }

    private static final class WorldEvent {
        String eventId;
        int turnNumber;
        String title;
        String text;
        String status = "scheduled";
        Integer resolutionTurnNumber;
        String resolutionText;
    }

    private static final class Settlement {
        String settlementId;
        String name;
        List<String> services;
        String availability;
        final List<String> discoveredBy = new ArrayList<>();
        final Map<String, Shop> shopsById = new LinkedHashMap<>();
    }

    private static final class Shop {
        String shopId;
        String name;
        final Map<String, Long> stock = new LinkedHashMap<>();
        long buyPrice;
        long sellPrice;
    }

    private static final class DowntimeActivity {
        String activityId;
        String name;
        long cyclesRequired;
    }

    private static final class DowntimeAllocation {
        String characterId;
        String activityId;
        long cyclesCompleted;
        long completions;
    }

    private static final class PlayQuest {
        String questId;
        String title;
        List<String> dependsOn;
        String state;
        Long rewardXp;
        Map<String, Long> rewardItems;
        boolean rewardsAwarded = false;
    }

    private static final class Relationship {
        String sourceId;
        String targetId;
        String kind;
        long score;
    }

    private static final class Clue {
        String clueId;
        String text;
        String audience;
        String characterId;
    }

    private static final class PlayNpc {
        String npcId;
        String name;
        String agenda;
        String publicStatus;
        final List<DialogueEntry> dialogueHistory = new ArrayList<>();
    }

    private static final class DialogueEntry {
        String dialogueId;
        String speaker;
        String text;
        String visibility;
    }

    private static final class PlayFaction {
        String factionId;
        String name;
        /** character id -> total reputation, bounded to [-100,100]. */
        final Map<String, Long> reputationByCharacter = new LinkedHashMap<>();
        final List<ReputationEntry> history = new ArrayList<>();
    }

    private static final class ReputationEntry {
        String factionId;
        String characterId;
        long reputation;
        long delta;
        String reason;
    }

    private static final class Loot {
        String lootId;
        String itemId;
        long quantity;
        String status = "open";
        /** voter username -> recipient character id. */
        final Map<String, String> votesByVoter = new LinkedHashMap<>();
        String recipientCharacterId;
    }

    private static List<String> buildTurnQueue(int playerCount) {
        List<String> queue = new ArrayList<>();
        for (int i = 0; i < playerCount; i++) {
            char letter = (char) ('a' + i);
            queue.add("player-" + letter);
            queue.add("dm");
        }
        return queue;
    }

    private static final Map<String, PlayCampaign> PLAY_CAMPAIGNS = new ConcurrentHashMap<>();

    /**
     * Spectator id -> owning campaign id. Global (not per-campaign) because
     * spectator ids must be unique across all campaigns: the bearer token is
     * derived solely from the spectator id, with no campaign disambiguator.
     */
    private static final Map<String, String> SPECTATOR_CAMPAIGN_BY_ID = new ConcurrentHashMap<>();

    /**
     * Resolves the bearer token to a known user. Returns null after sending a
     * response when the header is missing/malformed (401) or the referenced
     * user doesn't exist (403, since a syntactically valid session token with
     * an unknown username is a valid actor identity with no campaign
     * permissions); callers must check for null and return without sending
     * again.
     */
    private static User requireSessionUser(HttpExchange exchange) throws IOException {
        String header = exchange.getRequestHeaders().getFirst("Authorization");
        if (header == null || !header.startsWith("Bearer session-")) {
            sendJson(exchange, 401, mapOf("error", "unauthorized"));
            return null;
        }
        String username = header.substring("Bearer session-".length());
        User user = USERS.get(username);
        if (user == null) {
            sendJson(exchange, 403, mapOf("error", "not a campaign member"));
            return null;
        }
        return user;
    }

    /**
     * Looks up a play campaign by id, sending 404 {@code not found} and
     * returning null on a miss so callers can write
     * {@code campaign = requirePlayCampaign(...); if (campaign == null) return;}.
     */
    private static PlayCampaign requirePlayCampaign(HttpExchange exchange, String campaignId) throws IOException {
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) {
            sendJson(exchange, 404, mapOf("error", "not found"));
        }
        return campaign;
    }

    /**
     * Sends 403 {@code not a campaign member} and returns false unless
     * {@code user} is the owner or a joined member. Caller must hold the
     * campaign's monitor and return immediately on a false result.
     */
    private static boolean requireCampaignMember(HttpExchange exchange, PlayCampaign campaign, User user) throws IOException {
        boolean isMember = user.username.equals(campaign.owner) || campaign.membersByUsername.containsKey(user.username);
        if (!isMember) {
            sendJson(exchange, 403, mapOf("error", "not a campaign member"));
        }
        return isMember;
    }

    /**
     * Sends 403 {@code forbidden} and returns false unless {@code user} owns
     * (is the DM of) {@code campaign}. Caller must return immediately on a
     * false result.
     */
    private static boolean requireCampaignOwner(HttpExchange exchange, PlayCampaign campaign, User user) throws IOException {
        boolean isOwner = user.username.equals(campaign.owner);
        if (!isOwner) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
        }
        return isOwner;
    }

    /**
     * Looks up an encounter within a play campaign, sending 404 {@code not
     * found} and returning null on a miss. Caller must hold the campaign's
     * monitor and return immediately on a null result.
     */
    private static Encounter requireEncounter(HttpExchange exchange, PlayCampaign campaign, String encounterId) throws IOException {
        Encounter encounter = campaign.encountersById.get(encounterId);
        if (encounter == null) {
            sendJson(exchange, 404, mapOf("error", "not found"));
        }
        return encounter;
    }

    private static void handlePlayCampaigns(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        if (path.equals("/v1/play/campaigns") || path.equals("/v1/play/campaigns/")) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreatePlayCampaign(exchange);
            return;
        }

        String prefix = "/v1/play/campaigns/";
        if (!path.startsWith(prefix)) {
            sendJson(exchange, 404, mapOf("error", "not found"));
            return;
        }
        String rest = path.substring(prefix.length());
        String[] parts = rest.split("/", -1);
        String campaignId = parts[0];
        if (campaignId.isEmpty()) {
            sendJson(exchange, 404, mapOf("error", "not found"));
            return;
        }

        if (parts.length == 2 && "members".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleJoinPlayCampaign(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "onboarding".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetOnboarding(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "start".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleStartPlayCampaign(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "narrations".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddNarration(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "actions".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddPlayerAction(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "messages".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddMessage(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "resolutions".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddResolution(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "turn".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetPlayCampaignTurn(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "turn".equals(parts[1]) && "nudge".equals(parts[2])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleNudgeTurn(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "turn".equals(parts[1]) && "travel".equals(parts[2])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleTravelTurn(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "turn".equals(parts[1]) && "rest".equals(parts[2])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleRestTurn(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "my-turn".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetMyTurn(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "gm".equals(parts[1]) && "status".equals(parts[2])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetGmStatus(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "document".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("GET".equalsIgnoreCase(method)) {
                handleGetCampaignDocument(exchange, campaignId);
            } else if ("PUT".equalsIgnoreCase(method)) {
                handlePutCampaignDocument(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "backups".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateBackup(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListBackups(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "backups".equals(parts[1]) && "restore".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleRestoreBackup(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "session-zero".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("GET".equalsIgnoreCase(method)) {
                handleGetSessionZero(exchange, campaignId);
            } else if ("PUT".equalsIgnoreCase(method)) {
                handlePutSessionZero(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "content".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateContent(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetContentList(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "content".equals(parts[1]) && "tags".equals(parts[3])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handlePutContentTags(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "scenes".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateScene(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "encounters".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateEncounter(exchange, campaignId);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "monsters".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddMonster(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "encounters".equals(parts[1]) && "monsters".equals(parts[3])) {
            if (!requireMethod(exchange, "DELETE")) {
                return;
            }
            handleRemoveMonster(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "combatants".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleBindCombatant(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "encounters".equals(parts[1]) && "combatants".equals(parts[3])) {
            if (!requireMethod(exchange, "DELETE")) {
                return;
            }
            handleUnbindCombatant(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "turn".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetEncounterTurn(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "encounters".equals(parts[1]) && "turn".equals(parts[3]) && "advance".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAdvanceEncounterTurn(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "encounters".equals(parts[1]) && "turn".equals(parts[3]) && "delay".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleDelayEncounterTurn(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "encounters".equals(parts[1]) && "turn".equals(parts[3]) && "ready".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleReadyEncounterTurn(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "actions".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddCombatAction(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "damage".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleEncounterDamage(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "heal".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleEncounterHeal(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "conditions".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAddEncounterCondition(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "status".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetEncounterStatus(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "rewards".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAwardEncounterRewards(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "close".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCloseEncounter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "encounters".equals(parts[1]) && "end".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleEndEncounter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 3 && "scenes".equals(parts[1]) && "current".equals(parts[2])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCurrentScene(exchange, campaignId);
            return;
        }

        if (parts.length == 4 && "scenes".equals(parts[1]) && "enter".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleEnterScene(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "scenes".equals(parts[1]) && "close".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCloseScene(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "locations".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateLocation(exchange, campaignId);
            return;
        }

        if (parts.length == 4 && "locations".equals(parts[1]) && "connections".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateConnection(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "locations".equals(parts[1]) && "travel".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetTravel(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "damage".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCharacterDamage(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "death-saves".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleDeathSave(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "status".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCharacterStatus(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "owner".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCharacterOwner(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "claim".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleClaimCharacter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "transfer".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleTransferCharacter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "build".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleBuildCharacter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "level-up".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleLevelUpCharacter(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "skill-check".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleSkillCheck(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "spells".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleAddSpell(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetSpells(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "prepared-spells".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("PUT".equalsIgnoreCase(method)) {
                handlePutPreparedSpells(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetPreparedSpells(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "casts".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCastSpell(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetCasts(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 5 && "characters".equals(parts[1]) && "concentration".equals(parts[3])
                && "advance-turn".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAdvanceConcentrationTurn(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "concentration".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("PUT".equalsIgnoreCase(method)) {
                handlePutConcentration(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetConcentration(exchange, campaignId, parts[2]);
            } else if ("DELETE".equalsIgnoreCase(method)) {
                handleDeleteConcentration(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 5 && "characters".equals(parts[1]) && "inventory".equals(parts[3])
                && "items".equals(parts[4])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleAddInventoryItem(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetInventoryItems(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 6 && "characters".equals(parts[1]) && "inventory".equals(parts[3])
                && "items".equals(parts[4])) {
            if (!requireMethod(exchange, "DELETE")) {
                return;
            }
            handleRemoveInventoryItem(exchange, campaignId, parts[2], parts[5]);
            return;
        }

        if (parts.length == 7 && "characters".equals(parts[1]) && "inventory".equals(parts[3])
                && "items".equals(parts[4]) && "consume".equals(parts[6])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleConsumeInventoryItem(exchange, campaignId, parts[2], parts[5]);
            return;
        }

        if (parts.length == 6 && "characters".equals(parts[1]) && "equipment".equals(parts[3])
                && "attune".equals(parts[5])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAttuneEquipment(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 5 && "characters".equals(parts[1]) && "equipment".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("PUT".equalsIgnoreCase(method)) {
                handlePutEquipment(exchange, campaignId, parts[2], parts[4]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetEquipment(exchange, campaignId, parts[2], parts[4]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "currency".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCurrency(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "characters".equals(parts[1]) && "currency".equals(parts[3])
                && "transfers".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleTransferCurrency(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "loot".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateLoot(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "loot".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetLoot(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "loot".equals(parts[1]) && "votes".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleVoteLoot(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "loot".equals(parts[1]) && "assign".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAssignLoot(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "npcs".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreatePlayNpc(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "npcs".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetPlayNpc(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "npcs".equals(parts[1]) && "agenda".equals(parts[3])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleUpdatePlayNpcAgenda(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "npcs".equals(parts[1]) && "dialogue".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateNpcDialogue(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetNpcDialogue(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "factions".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreatePlayFaction(exchange, campaignId);
            return;
        }

        if (parts.length == 4 && "factions".equals(parts[1]) && "reputation".equals(parts[3])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleChangeFactionReputation(exchange, campaignId, parts[2]);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetFactionReputation(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "relationships".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateRelationship(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetRelationships(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 5 && "relationships".equals(parts[1])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleUpdateRelationship(exchange, campaignId, parts[2], parts[3], parts[4]);
            return;
        }

        if (parts.length == 2 && "clues".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateClue(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetClues(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "quests".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreatePlayQuest(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetPlayQuests(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "quests".equals(parts[1]) && "state".equals(parts[3])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleUpdatePlayQuestState(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "quests".equals(parts[1]) && "rewards".equals(parts[3])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleConfigureQuestRewards(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "quests".equals(parts[1]) && "rewards".equals(parts[3]) && "award".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAwardQuestRewards(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "rewards".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCharacterRewards(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "world-events".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateWorldEvent(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetWorldEvents(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "world-events".equals(parts[1]) && "resolve".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleResolveWorldEvent(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "calendar".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleInitCalendar(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetCalendar(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "calendar".equals(parts[1]) && "advance".equals(parts[2])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAdvanceCalendar(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "settlements".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateSettlement(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetSettlements(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "settlements".equals(parts[1])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleUpdateSettlement(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "settlements".equals(parts[1]) && "discover".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleDiscoverSettlement(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 4 && "settlements".equals(parts[1]) && "shops".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateShop(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 5 && "settlements".equals(parts[1]) && "shops".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetShop(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 6 && "settlements".equals(parts[1]) && "shops".equals(parts[3])
                && "buy".equals(parts[5])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleShopBuy(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 6 && "settlements".equals(parts[1]) && "shops".equals(parts[3])
                && "sell".equals(parts[5])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleShopSell(exchange, campaignId, parts[2], parts[4]);
            return;
        }

        if (parts.length == 2 && "recipes".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateRecipe(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetRecipes(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "recipes".equals(parts[1]) && "craft".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCraftRecipe(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 3 && "downtime".equals(parts[1]) && "activities".equals(parts[2])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateDowntimeActivity(exchange, campaignId);
            return;
        }

        if (parts.length == 5 && "characters".equals(parts[1]) && "downtime".equals(parts[3])
                && "allocations".equals(parts[4])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateDowntimeAllocation(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 7 && "characters".equals(parts[1]) && "downtime".equals(parts[3])
                && "allocations".equals(parts[4]) && "progress".equals(parts[6])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleProgressDowntimeAllocation(exchange, campaignId, parts[2], parts[5]);
            return;
        }

        if (parts.length == 6 && "characters".equals(parts[1]) && "downtime".equals(parts[3])
                && "allocations".equals(parts[4])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetDowntimeAllocation(exchange, campaignId, parts[2], parts[5]);
            return;
        }

        if (parts.length == 2 && "notes".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateNote(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListNotes(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "notes".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("GET".equalsIgnoreCase(method)) {
                handleGetNote(exchange, campaignId, parts[2]);
            } else if ("PUT".equalsIgnoreCase(method)) {
                handleUpdateNote(exchange, campaignId, parts[2]);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "whispers".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateWhisper(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListWhispers(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "characters".equals(parts[1]) && "sheet".equals(parts[3])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetCharacterSheet(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "invitations".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateInvitation(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListInvitations(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 4 && "invitations".equals(parts[1]) && "accept".equals(parts[3])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAcceptInvitation(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "delegations".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleGrantDelegation(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "delegations".equals(parts[1]) && "audit".equals(parts[2])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetDelegationAudit(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "delegations".equals(parts[1])) {
            if (!requireMethod(exchange, "DELETE")) {
                return;
            }
            handleRevokeDelegation(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "audit-events".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateAuditEvent(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListAuditEvents(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "projection-events".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAppendProjectionEvent(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "projection".equals(parts[1]) && "rebuild".equals(parts[2])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetProjection(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "projection".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetProjection(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "idempotent-events".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateIdempotentEvent(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListIdempotentEvents(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "safe-turns".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleSubmitSafeTurn(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListSafeTurns(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "transactional-transfers".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateTransactionalTransfer(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListTransactionalTransfers(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "exports".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateExport(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListExports(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 3 && "exports".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetExport(exchange, campaignId, parts[2]);
            return;
        }

        if (parts.length == 2 && "imports".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateImport(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "import-state".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetImportState(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "migrations".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateMigration(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "migration-state".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetMigrationState(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "search-records".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateSearchRecord(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListSearchRecords(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "rate-events".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("POST".equalsIgnoreCase(method)) {
                handleCreateRateEvent(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleListRateEvents(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "metrics".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetServiceMetrics(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "service-mode".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleSetServiceMode(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "replay-events".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAppendReplayEvent(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "replay".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetReplay(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "replay".equals(parts[1]) && "check".equals(parts[2])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetReplay(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "rng-seed".equals(parts[1])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleSetRngSeed(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "rng-rolls".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAppendRngRoll(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "rng-ledger".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetRngLedger(exchange, campaignId);
            return;
        }

        if (parts.length == 3 && "moderation".equals(parts[1]) && "reports".equals(parts[2])) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handleSubmitModerationReport(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handleGetModerationReports(exchange, campaignId);
                return;
            }
            sendJson(exchange, 405, mapOf("error", "method not allowed"));
            return;
        }

        if (parts.length == 5 && "moderation".equals(parts[1]) && "reports".equals(parts[2]) && "resolution".equals(parts[4])) {
            if (!requireMethod(exchange, "PUT")) {
                return;
            }
            handleResolveModerationReport(exchange, campaignId, parts[3]);
            return;
        }

        if (parts.length == 2 && "safety-boundaries".equals(parts[1])) {
            String method = exchange.getRequestMethod();
            if ("PUT".equalsIgnoreCase(method)) {
                handleReplaceSafetyBoundaries(exchange, campaignId);
            } else if ("GET".equalsIgnoreCase(method)) {
                handleGetSafetyBoundaries(exchange, campaignId);
            } else {
                sendJson(exchange, 405, mapOf("error", "method not allowed"));
            }
            return;
        }

        if (parts.length == 2 && "safety-checks".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleSubmitSafetyCheck(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "safety-events".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetSafetyEvents(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "fixture-seeds".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleSeedFixture(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "fixture-state".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetFixtureState(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "spectators".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleCreateSpectator(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "spectator-view".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetSpectatorView(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "feed-events".equals(parts[1])) {
            if (!requireMethod(exchange, "POST")) {
                return;
            }
            handleAppendFeedEvent(exchange, campaignId);
            return;
        }

        if (parts.length == 2 && "event-feed".equals(parts[1])) {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            handleGetEventFeed(exchange, campaignId);
            return;
        }

        sendJson(exchange, 404, mapOf("error", "not found"));
    }

    private static Map<String, Object> canonicalFixtureState() {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("fixture_id", "canonical-v1");
        resp.put("status", "seeded");
        List<Map<String, Object>> characters = new ArrayList<>();
        Map<String, Object> hero = new LinkedHashMap<>();
        hero.put("character_id", "fixture-hero");
        hero.put("name", "Ari");
        hero.put("class", "fighter");
        characters.add(hero);
        Map<String, Object> mage = new LinkedHashMap<>();
        mage.put("character_id", "fixture-mage");
        mage.put("name", "Bea");
        mage.put("class", "wizard");
        characters.add(mage);
        resp.put("characters", characters);
        resp.put("story", "The lantern is lit.");
        resp.put("event_ids", new ArrayList<>(java.util.Arrays.asList("fixture-event-1", "fixture-event-2")));
        return resp;
    }

    private static void handleSeedFixture(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object fixtureIdObj = obj.get("fixture_id");
            if (!(fixtureIdObj instanceof String) || !"canonical-v1".equals(fixtureIdObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            int status = campaign.fixtureSeeded ? 200 : 201;
            campaign.fixtureSeeded = true;
            sendJson(exchange, status, canonicalFixtureState());
        }
    }

    private static void handleGetFixtureState(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!campaign.fixtureSeeded) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, canonicalFixtureState());
        }
    }

    private static void handleCreateSpectator(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object spectatorIdObj = obj.get("spectator_id");
        if (!(spectatorIdObj instanceof String) || ((String) spectatorIdObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid spectator_id"));
            return;
        }
        String spectatorId = (String) spectatorIdObj;
        String existingCampaignId = SPECTATOR_CAMPAIGN_BY_ID.putIfAbsent(spectatorId, campaignId);
        if (existingCampaignId != null) {
            sendJson(exchange, 409, mapOf("error", "spectator already exists"));
            return;
        }
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("spectator_id", spectatorId);
        resp.put("token", "spectator-" + spectatorId);
        sendJson(exchange, 201, resp);
    }

    /**
     * Serves the read-only spectator projection. Authentication here is
     * exclusively a {@code Bearer spectator-<id>} ticket minted by
     * {@link #handleCreateSpectator}, so this intentionally bypasses
     * {@link #requireSessionUser}: normal DM/player session tokens are
     * rejected with 403 rather than accepted.
     */
    private static void handleGetSpectatorView(HttpExchange exchange, String campaignId) throws IOException {
        String header = exchange.getRequestHeaders().getFirst("Authorization");
        boolean isSessionToken = header != null && header.startsWith("Bearer session-");
        String spectatorId = null;
        if (header != null && header.startsWith("Bearer spectator-")) {
            String candidate = header.substring("Bearer spectator-".length());
            if (!candidate.isEmpty()) {
                spectatorId = candidate;
            }
        }
        if (!isSessionToken && spectatorId == null) {
            sendJson(exchange, 401, mapOf("error", "unauthorized"));
            return;
        }
        PlayCampaign campaign = PLAY_CAMPAIGNS.get(campaignId);
        if (campaign == null) {
            sendJson(exchange, 404, mapOf("error", "not found"));
            return;
        }
        if (isSessionToken) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        String spectatorCampaignId = SPECTATOR_CAMPAIGN_BY_ID.get(spectatorId);
        if (spectatorCampaignId == null) {
            sendJson(exchange, 401, mapOf("error", "unauthorized"));
            return;
        }
        if (!spectatorCampaignId.equals(campaignId)) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        synchronized (campaign) {
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("name", campaign.name);
            resp.put("status", campaign.status);
            resp.put("party_size", campaign.membersByUsername.size());
            resp.put("story", campaign.story);
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> safetyBoundariesResponse(PlayCampaign campaign) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("blocked_tags", new ArrayList<>(campaign.blockedTags));
        return resp;
    }

    private static void handleReplaceSafetyBoundaries(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            List<String> tags = validateTags(obj.get("blocked_tags"), true);
            if (tags == null) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            campaign.blockedTags.clear();
            campaign.blockedTags.addAll(tags);
            sendJson(exchange, 200, safetyBoundariesResponse(campaign));
        }
    }

    private static void handleGetSafetyBoundaries(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            sendJson(exchange, 200, safetyBoundariesResponse(campaign));
        }
    }

    private static Map<String, Object> safetyEventResponse(SafetyEvent event) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("event_id", event.eventId);
        r.put("kind", event.kind);
        r.put("text", event.text);
        r.put("tags", event.tags);
        r.put("sequence", event.sequence);
        return r;
    }

    private static void handleSubmitSafetyCheck(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object eventIdObj = obj.get("event_id");
            Object kindObj = obj.get("kind");
            Object textObj = obj.get("text");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                    || !(textObj instanceof String) || ((String) textObj).isEmpty()
                    || !(kindObj instanceof String) || !("narration".equals(kindObj) || "chat".equals(kindObj))) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            List<String> tags = validateTags(obj.get("tags"), true);
            if (tags == null) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String eventId = (String) eventIdObj;
            if (campaign.safetyEventIds.contains(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event_id already accepted"));
                return;
            }
            for (String tag : tags) {
                if (campaign.blockedTags.contains(tag)) {
                    sendJson(exchange, 409, mapOf("error", "blocked tag"));
                    return;
                }
            }

            SafetyEvent event = new SafetyEvent();
            event.eventId = eventId;
            event.kind = (String) kindObj;
            event.text = (String) textObj;
            event.tags = tags;
            event.sequence = campaign.nextSafetyEventSequence++;
            campaign.safetyEventIds.add(eventId);
            campaign.safetyEventsInOrder.add(event);

            sendJson(exchange, 201, safetyEventResponse(event));
        }
    }

    private static void handleGetSafetyEvents(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> events = new ArrayList<>();
            for (SafetyEvent event : campaign.safetyEventsInOrder) {
                events.add(safetyEventResponse(event));
            }
            sendJson(exchange, 200, mapOf("events", events));
        }
    }

    private static Map<String, Object> moderationReportResponse(ModerationReport report) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("report_id", report.reportId);
        r.put("target_id", report.targetId);
        r.put("reason", report.reason);
        r.put("status", report.status);
        r.put("reporter", report.reporter);
        r.put("sequence", report.sequence);
        if ("resolved".equals(report.status)) {
            r.put("action", report.action);
            r.put("note", report.note);
            r.put("resolver", report.resolver);
        }
        return r;
    }

    private static void handleSubmitModerationReport(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object reportIdObj = obj.get("report_id");
            Object targetIdObj = obj.get("target_id");
            Object reasonObj = obj.get("reason");
            if (!(reportIdObj instanceof String) || ((String) reportIdObj).isEmpty()
                    || !(targetIdObj instanceof String) || ((String) targetIdObj).isEmpty()
                    || !(reasonObj instanceof String) || ((String) reasonObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String reportId = (String) reportIdObj;
            if (campaign.moderationReportsById.containsKey(reportId)) {
                sendJson(exchange, 409, mapOf("error", "report_id already exists"));
                return;
            }

            ModerationReport report = new ModerationReport();
            report.reportId = reportId;
            report.targetId = (String) targetIdObj;
            report.reason = (String) reasonObj;
            report.status = "open";
            report.reporter = user.username;
            report.sequence = campaign.nextModerationSequence++;
            campaign.moderationReportsById.put(reportId, report);
            campaign.moderationReportsInOrder.add(report);

            sendJson(exchange, 201, moderationReportResponse(report));
        }
    }

    private static void handleGetModerationReports(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> reports = new ArrayList<>();
            for (ModerationReport report : campaign.moderationReportsInOrder) {
                reports.add(moderationReportResponse(report));
            }
            sendJson(exchange, 200, mapOf("reports", reports));
        }
    }

    private static void handleResolveModerationReport(HttpExchange exchange, String campaignId, String reportId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            ModerationReport report = campaign.moderationReportsById.get(reportId);
            if (report == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object actionObj = obj.get("action");
            Object noteObj = obj.get("note");
            if (!(actionObj instanceof String) || !("allow".equals(actionObj) || "remove".equals(actionObj))
                    || !(noteObj instanceof String) || ((String) noteObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            if ("resolved".equals(report.status)) {
                sendJson(exchange, 409, mapOf("error", "already resolved"));
                return;
            }

            report.status = "resolved";
            report.action = (String) actionObj;
            report.note = (String) noteObj;
            report.resolver = user.username;

            sendJson(exchange, 200, moderationReportResponse(report));
        }
    }

    private static Map<String, Object> rngLedgerResponse(PlayCampaign campaign) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("seed", campaign.rngSeed);
        List<Map<String, Object>> rolls = new ArrayList<>();
        for (RngRoll roll : campaign.rngRolls) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("roll_id", roll.rollId);
            r.put("sides", roll.sides);
            r.put("result", roll.result);
            r.put("sequence", roll.sequence);
            rolls.add(r);
        }
        resp.put("rolls", rolls);
        return resp;
    }

    private static long computeRngResult(String seed, int sequence, String rollId, int sides) {
        String s = seed + "|" + sequence + "|" + rollId + "|" + sides;
        byte[] bytes = s.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        long acc = 0L;
        for (byte b : bytes) {
            int ub = b & 0xFF;
            acc = (acc * 31L + ub) & 0xFFFFFFFFL;
        }
        return (acc % sides) + 1;
    }

    private static void handleSetRngSeed(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object seedObj = obj.get("seed");
            if (!(seedObj instanceof String) || ((String) seedObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid seed"));
                return;
            }
            if (campaign.rngSeed != null) {
                sendJson(exchange, 409, mapOf("error", "seed already configured"));
                return;
            }
            campaign.rngSeed = (String) seedObj;
            sendJson(exchange, 200, rngLedgerResponse(campaign));
        }
    }

    private static void handleAppendRngRoll(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            if (campaign.rngSeed == null) {
                sendJson(exchange, 409, mapOf("error", "no seed configured"));
                return;
            }
            Object rollIdObj = obj.get("roll_id");
            Object sidesObj = obj.get("sides");
            if (!(rollIdObj instanceof String) || ((String) rollIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid roll_id"));
                return;
            }
            if (!(sidesObj instanceof Number) || !isIntegral(sidesObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid sides"));
                return;
            }
            int sides = ((Number) sidesObj).intValue();
            if (sides < 2 || sides > 100) {
                sendJson(exchange, 400, mapOf("error", "invalid sides"));
                return;
            }
            String rollId = (String) rollIdObj;
            if (campaign.rngRollIds.contains(rollId)) {
                sendJson(exchange, 409, mapOf("error", "roll_id already exists"));
                return;
            }

            int sequence = campaign.nextRngSequence++;
            long result = computeRngResult(campaign.rngSeed, sequence, rollId, sides);

            RngRoll roll = new RngRoll();
            roll.rollId = rollId;
            roll.sides = sides;
            roll.result = result;
            roll.sequence = sequence;
            campaign.rngRolls.add(roll);
            campaign.rngRollIds.add(rollId);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("roll_id", roll.rollId);
            resp.put("sides", roll.sides);
            resp.put("result", roll.result);
            resp.put("sequence", roll.sequence);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetRngLedger(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            sendJson(exchange, 200, rngLedgerResponse(campaign));
        }
    }

    private static Map<String, Object> feedEventJson(FeedEvent event) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("event_id", event.eventId);
        resp.put("text", event.text);
        resp.put("sequence", event.sequence);
        return resp;
    }

    private static void handleAppendFeedEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object eventIdObj = obj.get("event_id");
            Object textObj = obj.get("text");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                    || !(textObj instanceof String) || ((String) textObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String eventId = (String) eventIdObj;
            String text = (String) textObj;
            if (campaign.feedEventIds.contains(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event_id already exists"));
                return;
            }
            FeedEvent event = new FeedEvent();
            event.eventId = eventId;
            event.text = text;
            event.sequence = campaign.nextFeedSequence++;
            campaign.feedEventIds.add(eventId);
            campaign.feedEventsInOrder.add(event);
            sendJson(exchange, 201, feedEventJson(event));
        }
    }

    private static void handleGetEventFeed(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Integer limitParam = null;
        Integer cursorParam = null;
        String rawQuery = exchange.getRequestURI().getRawQuery();
        if (rawQuery != null) {
            for (String param : rawQuery.split("&")) {
                if (param.isEmpty()) {
                    continue;
                }
                int eq = param.indexOf('=');
                String key = eq < 0 ? param : param.substring(0, eq);
                String value = eq < 0 ? "" : param.substring(eq + 1);
                try {
                    value = URLDecoder.decode(value, "UTF-8");
                } catch (IOException e) {
                    // keep raw value
                }
                if ("limit".equals(key)) {
                    try {
                        limitParam = Integer.parseInt(value);
                    } catch (NumberFormatException e) {
                        sendJson(exchange, 400, mapOf("error", "invalid limit"));
                        return;
                    }
                } else if ("cursor".equals(key)) {
                    try {
                        cursorParam = Integer.parseInt(value);
                    } catch (NumberFormatException e) {
                        sendJson(exchange, 400, mapOf("error", "invalid cursor"));
                        return;
                    }
                }
            }
        }
        int limit = limitParam == null ? 2 : limitParam;
        int cursor = cursorParam == null ? 0 : cursorParam;
        if (limit < 1 || limit > 3) {
            sendJson(exchange, 400, mapOf("error", "invalid limit"));
            return;
        }
        if (cursor < 0) {
            sendJson(exchange, 400, mapOf("error", "invalid cursor"));
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> page = new ArrayList<>();
            int end = Math.min(campaign.feedEventsInOrder.size(), cursor + limit);
            for (int i = cursor; i < end; i++) {
                page.add(feedEventJson(campaign.feedEventsInOrder.get(i)));
            }
            int nextCursor = cursor >= campaign.feedEventsInOrder.size() ? cursor : end;
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("events", page);
            resp.put("next_cursor", nextCursor);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleSetServiceMode(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object maintenanceObj = obj.get("maintenance");
        if (!(maintenanceObj instanceof Boolean)) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        MAINTENANCE_MODE.set((Boolean) maintenanceObj);
        sendJson(exchange, 200, mapOf("maintenance", MAINTENANCE_MODE.get()));
    }

    private static void handleAppendReplayEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object eventIdObj = obj.get("event_id");
            Object kindObj = obj.get("kind");
            Object textObj = obj.get("text");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                    || !(textObj instanceof String) || ((String) textObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            if (!(kindObj instanceof String) || !"append".equals(kindObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String eventId = (String) eventIdObj;
            String text = (String) textObj;

            if (campaign.replayEventIds.contains(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event_id already exists"));
                return;
            }

            ReplayEvent event = new ReplayEvent();
            event.eventId = eventId;
            event.kind = "append";
            event.text = text;
            event.sequence = campaign.nextReplaySequence++;

            campaign.replayEvents.add(event);
            campaign.replayEventIds.add(eventId);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("event_id", event.eventId);
            resp.put("kind", event.kind);
            resp.put("text", event.text);
            resp.put("sequence", event.sequence);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetReplay(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            StringBuilder story = new StringBuilder();
            List<String> eventIds = new ArrayList<>();
            for (ReplayEvent event : campaign.replayEvents) {
                story.append(event.text);
                eventIds.add(event.eventId);
            }
            String digest = String.join(",", eventIds) + "|" + story;
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("story", story.toString());
            resp.put("event_ids", eventIds);
            resp.put("digest", digest);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleSubmitSafeTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object submissionIdObj = obj.get("submission_id");
            Object expectedTurnObj = obj.get("expected_turn");
            Object actionObj = obj.get("action");
            if (!(submissionIdObj instanceof String) || ((String) submissionIdObj).isEmpty()
                    || !(actionObj instanceof String) || ((String) actionObj).isEmpty()
                    || !(expectedTurnObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            double expectedTurnRaw = ((Number) expectedTurnObj).doubleValue();
            if (expectedTurnRaw != Math.floor(expectedTurnRaw) || expectedTurnRaw <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            int expectedTurn = (int) expectedTurnRaw;
            String submissionId = (String) submissionIdObj;
            String action = (String) actionObj;

            if (campaign.safeTurnSubmissionIds.contains(submissionId)) {
                sendJson(exchange, 409, mapOf("error", "duplicate submission_id"));
                return;
            }

            if (expectedTurn != campaign.safeTurnCurrent) {
                sendJson(exchange, 409, mapOf("current_turn", campaign.safeTurnCurrent));
                return;
            }

            SafeTurnEntry entry = new SafeTurnEntry();
            entry.submissionId = submissionId;
            entry.action = action;
            entry.acceptedTurn = campaign.safeTurnCurrent;
            campaign.safeTurnCurrent++;
            entry.nextTurn = campaign.safeTurnCurrent;

            campaign.safeTurnSubmissionIds.add(submissionId);
            campaign.safeTurnAccepted.add(entry);

            sendJson(exchange, 201, safeTurnEntryJson(entry));
        }
    }

    private static void handleListSafeTurns(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> accepted = new ArrayList<>();
            for (SafeTurnEntry entry : campaign.safeTurnAccepted) {
                accepted.add(safeTurnEntryJson(entry));
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("current_turn", campaign.safeTurnCurrent);
            resp.put("accepted", accepted);
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> safeTurnEntryJson(SafeTurnEntry entry) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("submission_id", entry.submissionId);
        resp.put("action", entry.action);
        resp.put("accepted_turn", entry.acceptedTurn);
        resp.put("next_turn", entry.nextTurn);
        return resp;
    }

    private static void handleCreateTransactionalTransfer(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        synchronized (campaign) {
            Object fromObj = obj.get("from_character_id");
            Object toObj = obj.get("to_character_id");
            Object amountObj = obj.get("amount");
            Object simulateObj = obj.get("simulate_failure");

            if (!(fromObj instanceof String) || ((String) fromObj).isEmpty()
                    || !(toObj instanceof String) || ((String) toObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String fromCharacterId = (String) fromObj;
            String toCharacterId = (String) toObj;

            boolean simulateFailure = false;
            if (simulateObj != null) {
                if (!(simulateObj instanceof Boolean)) {
                    sendJson(exchange, 400, mapOf("error", "invalid request"));
                    return;
                }
                simulateFailure = (Boolean) simulateObj;
            }

            PlayMember source = findMemberByCharacterId(campaign, fromCharacterId);
            if (source == null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (source.owner == null || !source.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (toCharacterId.equals(fromCharacterId)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            PlayMember dest = findMemberByCharacterId(campaign, toCharacterId);
            if (dest == null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (!(amountObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            double amountRaw = ((Number) amountObj).doubleValue();
            if (amountRaw != Math.floor(amountRaw) || amountRaw <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long amount = (long) amountRaw;
            if (source.gold < amount) {
                sendJson(exchange, 409, mapOf("error", "insufficient gold"));
                return;
            }

            if (simulateFailure) {
                sendJson(exchange, 500, mapOf("error", "simulated failure"));
                return;
            }

            source.gold -= amount;
            dest.gold += amount;

            TransactionalTransfer record = new TransactionalTransfer();
            record.fromCharacterId = source.characterId;
            record.toCharacterId = dest.characterId;
            record.amount = amount;
            record.fromGold = source.gold;
            record.toGold = dest.gold;
            record.sequence = campaign.nextTransactionalTransferSequence++;
            campaign.transactionalTransfers.add(record);

            sendJson(exchange, 201, transactionalTransferJson(record));
        }
    }

    private static void handleListTransactionalTransfers(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> transfers = new ArrayList<>();
            for (TransactionalTransfer record : campaign.transactionalTransfers) {
                transfers.add(transactionalTransferJson(record));
            }
            sendJson(exchange, 200, mapOf("transfers", transfers));
        }
    }

    private static Map<String, Object> transactionalTransferJson(TransactionalTransfer record) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("from_character_id", record.fromCharacterId);
        resp.put("to_character_id", record.toCharacterId);
        resp.put("amount", record.amount);
        resp.put("from_gold", record.fromGold);
        resp.put("to_gold", record.toGold);
        resp.put("sequence", record.sequence);
        return resp;
    }

    private static void handleCreateExport(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            CampaignExport record = new CampaignExport();
            record.version = campaign.exports.size() + 1;
            record.story = campaign.story;
            record.status = campaign.status;
            campaign.exports.add(record);
            sendJson(exchange, 201, campaignExportJson(record));
        }
    }

    private static void handleListExports(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> exports = new ArrayList<>();
            for (CampaignExport record : campaign.exports) {
                exports.add(campaignExportJson(record));
            }
            sendJson(exchange, 200, mapOf("exports", exports));
        }
    }

    private static void handleGetExport(HttpExchange exchange, String campaignId, String versionRaw) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            int version;
            try {
                version = Integer.parseInt(versionRaw);
            } catch (NumberFormatException e) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (version < 1 || version > campaign.exports.size()) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            CampaignExport record = campaign.exports.get(version - 1);
            sendJson(exchange, 200, campaignExportJson(record));
        }
    }

    private static Map<String, Object> campaignExportJson(CampaignExport record) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("version", record.version);
        resp.put("story", record.story);
        resp.put("status", record.status);
        return resp;
    }

    private static void handleCreateImport(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        synchronized (campaign) {
            Object versionObj = obj.get("version");
            Object storyObj = obj.get("story");
            Object statusObj = obj.get("status");

            if (!(versionObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid import"));
                return;
            }
            double versionRaw = ((Number) versionObj).doubleValue();
            if (versionRaw != Math.floor(versionRaw) || (int) versionRaw != 1) {
                sendJson(exchange, 400, mapOf("error", "invalid import"));
                return;
            }
            if (!(storyObj instanceof String) || ((String) storyObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid import"));
                return;
            }
            if (!(statusObj instanceof String)
                    || !("lobby".equals(statusObj) || "started".equals(statusObj))) {
                sendJson(exchange, 400, mapOf("error", "invalid import"));
                return;
            }

            String story = (String) storyObj;
            String status = (String) statusObj;

            campaign.story = story;
            campaign.status = status;

            CampaignExport record = new CampaignExport();
            record.version = 1;
            record.story = story;
            record.status = status;
            campaign.importedState = record;

            sendJson(exchange, 200, campaignExportJson(record));
        }
    }

    private static void handleGetImportState(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (campaign.importedState == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, campaignExportJson(campaign.importedState));
        }
    }

    private static void handleCreateMigration(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        synchronized (campaign) {
            Object schemaVersionObj = obj.get("schema_version");
            Object storyObj = obj.get("story");

            if (!(schemaVersionObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid migration"));
                return;
            }
            double schemaVersionRaw = ((Number) schemaVersionObj).doubleValue();
            if (schemaVersionRaw != Math.floor(schemaVersionRaw) || (int) schemaVersionRaw != 1) {
                sendJson(exchange, 400, mapOf("error", "invalid migration"));
                return;
            }
            if (!(storyObj instanceof String) || ((String) storyObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid migration"));
                return;
            }

            String story = (String) storyObj;

            if (campaign.migratedState != null && campaign.migratedState.sourceStory.equals(story)) {
                sendJson(exchange, 200, migrationStateJson(campaign.migratedState));
                return;
            }

            MigrationState state = new MigrationState();
            state.sourceStory = story;
            state.story = story;
            state.campaignName = campaign.name;
            campaign.migratedState = state;

            sendJson(exchange, 201, migrationStateJson(state));
        }
    }

    private static void handleGetMigrationState(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (campaign.migratedState == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, migrationStateJson(campaign.migratedState));
        }
    }

    private static Map<String, Object> migrationStateJson(MigrationState state) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("schema_version", 2);
        resp.put("story", state.story);
        resp.put("campaign_name", state.campaignName);
        return resp;
    }

    private static Map<String, Object> searchRecordJson(SearchRecord record) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("record_id", record.recordId);
        resp.put("text", record.text);
        return resp;
    }

    private static void handleCreateSearchRecord(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object recordIdObj = obj.get("record_id");
        Object textObj = obj.get("text");
        if (!(recordIdObj instanceof String) || ((String) recordIdObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String recordId = (String) recordIdObj;
        String text = (String) textObj;
        synchronized (campaign) {
            if (campaign.searchRecordsById.containsKey(recordId)) {
                sendJson(exchange, 400, mapOf("error", "record_id already exists"));
                return;
            }
            for (SearchRecord existing : campaign.searchRecordsInOrder) {
                if (existing.text.equals(text)) {
                    sendJson(exchange, 400, mapOf("error", "text already exists"));
                    return;
                }
            }
            SearchRecord record = new SearchRecord();
            record.recordId = recordId;
            record.text = text;
            campaign.searchRecordsById.put(recordId, record);
            campaign.searchRecordsInOrder.add(record);
            sendJson(exchange, 201, searchRecordJson(record));
        }
    }

    private static void handleListSearchRecords(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        String q = null;
        Integer limitParam = null;
        Integer cursorParam = null;
        String rawQuery = exchange.getRequestURI().getRawQuery();
        if (rawQuery != null) {
            for (String param : rawQuery.split("&")) {
                if (param.isEmpty()) {
                    continue;
                }
                int eq = param.indexOf('=');
                String key = eq < 0 ? param : param.substring(0, eq);
                String value = eq < 0 ? "" : param.substring(eq + 1);
                try {
                    value = URLDecoder.decode(value, "UTF-8");
                } catch (IOException e) {
                    // keep raw value
                }
                if ("q".equals(key)) {
                    q = value;
                } else if ("limit".equals(key)) {
                    try {
                        limitParam = Integer.parseInt(value);
                    } catch (NumberFormatException e) {
                        sendJson(exchange, 400, mapOf("error", "invalid limit"));
                        return;
                    }
                } else if ("cursor".equals(key)) {
                    try {
                        cursorParam = Integer.parseInt(value);
                    } catch (NumberFormatException e) {
                        sendJson(exchange, 400, mapOf("error", "invalid cursor"));
                        return;
                    }
                }
            }
        }
        int limit = limitParam == null ? 2 : limitParam;
        int cursor = cursorParam == null ? 0 : cursorParam;
        if (limit < 1 || limit > 3) {
            sendJson(exchange, 400, mapOf("error", "invalid limit"));
            return;
        }
        if (cursor < 0) {
            sendJson(exchange, 400, mapOf("error", "invalid cursor"));
            return;
        }
        synchronized (campaign) {
            List<SearchRecord> filtered = new ArrayList<>();
            String needle = q == null ? null : q.toLowerCase(Locale.ROOT);
            for (SearchRecord record : campaign.searchRecordsInOrder) {
                if (needle != null && !record.text.toLowerCase(Locale.ROOT).contains(needle)) {
                    continue;
                }
                filtered.add(record);
            }
            List<Map<String, Object>> page = new ArrayList<>();
            int end = Math.min(filtered.size(), cursor + limit);
            for (int i = cursor; i < end; i++) {
                page.add(searchRecordJson(filtered.get(i)));
            }
            Object nextCursor = end < filtered.size() ? end : null;
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("records", page);
            resp.put("next_cursor", nextCursor);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreateRateEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object eventIdObj = obj.get("event_id");
        if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String eventId = (String) eventIdObj;
        synchronized (campaign) {
            if (campaign.rateEventIds.contains(eventId)) {
                sendJson(exchange, 400, mapOf("error", "event_id already exists"));
                return;
            }
            int used = campaign.rateEventCountByUsername.getOrDefault(user.username, 0);
            if (used >= RATE_EVENT_LIMIT) {
                campaign.rejectedRateEvents++;
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("limit", RATE_EVENT_LIMIT);
                resp.put("remaining", 0);
                sendJson(exchange, 429, resp);
                return;
            }
            RateEvent event = new RateEvent();
            event.eventId = eventId;
            event.actor = user.username;
            campaign.rateEventIds.add(eventId);
            campaign.rateEventsInOrder.add(event);
            campaign.acceptedRateEvents++;
            int newUsed = used + 1;
            campaign.rateEventCountByUsername.put(user.username, newUsed);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("event_id", event.eventId);
            resp.put("actor", event.actor);
            resp.put("remaining", RATE_EVENT_LIMIT - newUsed);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleListRateEvents(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> events = new ArrayList<>();
            for (RateEvent event : campaign.rateEventsInOrder) {
                Map<String, Object> eventJson = new LinkedHashMap<>();
                eventJson.put("event_id", event.eventId);
                eventJson.put("actor", event.actor);
                events.add(eventJson);
            }
            int used = campaign.rateEventCountByUsername.getOrDefault(user.username, 0);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("events", events);
            resp.put("remaining", RATE_EVENT_LIMIT - used);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetServiceMetrics(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("accepted_rate_events", campaign.acceptedRateEvents);
            resp.put("rejected_rate_events", campaign.rejectedRateEvents);
            resp.put("projection_events", campaign.projectionEventCount);
            resp.put("uptime_ticks", 1);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetCurrency(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("gold", member.gold);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleTransferCurrency(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object toCharacterIdObj = obj.get("to_character_id");
        Object goldObj = obj.get("gold");

        synchronized (campaign) {
            PlayMember source = findMemberByCharacterId(campaign, characterId);
            if (source == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (source.owner == null || !source.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (!(toCharacterIdObj instanceof String) || ((String) toCharacterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String toCharacterId = (String) toCharacterIdObj;
            if (toCharacterId.equals(characterId)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            PlayMember dest = findMemberByCharacterId(campaign, toCharacterId);
            if (dest == null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (!(goldObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long gold = ((Number) goldObj).longValue();
            if (gold <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (source.gold < gold) {
                sendJson(exchange, 409, mapOf("error", "insufficient gold"));
                return;
            }

            source.gold -= gold;
            dest.gold += gold;
            int transferId = campaign.nextTransferId++;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("from_character_id", source.characterId);
            resp.put("to_character_id", dest.characterId);
            resp.put("gold", gold);
            resp.put("from_gold", source.gold);
            resp.put("to_gold", dest.gold);
            resp.put("transfer_id", transferId);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleCreateLoot(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object lootIdObj = obj.get("loot_id");
        Object itemIdObj = obj.get("item_id");
        Object quantityObj = obj.get("quantity");
        if (!(lootIdObj instanceof String) || ((String) lootIdObj).isEmpty()
                || !(itemIdObj instanceof String) || !INVENTORY_ITEM_CATALOG.contains(itemIdObj)
                || !(quantityObj instanceof Number) || !isIntegral(quantityObj)
                || ((Number) quantityObj).longValue() <= 0) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String lootId = (String) lootIdObj;
        String itemId = (String) itemIdObj;
        long quantity = ((Number) quantityObj).longValue();

        synchronized (campaign) {
            if (campaign.lootById.containsKey(lootId)) {
                sendJson(exchange, 409, mapOf("error", "loot already exists"));
                return;
            }
            Loot loot = new Loot();
            loot.lootId = lootId;
            loot.itemId = itemId;
            loot.quantity = quantity;
            campaign.lootById.put(lootId, loot);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("loot_id", loot.lootId);
            resp.put("item_id", loot.itemId);
            resp.put("quantity", loot.quantity);
            resp.put("status", loot.status);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetLoot(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Loot loot = campaign.lootById.get(lootId);
            if (loot == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, lootToMap(loot));
        }
    }

    private static void handleVoteLoot(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        if (!campaign.membersByUsername.containsKey(user.username)) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object recipientObj = obj.get("recipient_character_id");
        if (!(recipientObj instanceof String) || ((String) recipientObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String recipientCharacterId = (String) recipientObj;

        synchronized (campaign) {
            Loot loot = campaign.lootById.get(lootId);
            if (loot == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            PlayMember recipient = findMemberByCharacterId(campaign, recipientCharacterId);
            if (recipient == null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (loot.votesByVoter.containsKey(user.username)) {
                sendJson(exchange, 409, mapOf("error", "already voted"));
                return;
            }
            loot.votesByVoter.put(user.username, recipientCharacterId);
            long votesForRecipient = loot.votesByVoter.values().stream()
                    .filter(recipientCharacterId::equals).count();

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("loot_id", loot.lootId);
            resp.put("voter", user.username);
            resp.put("recipient_character_id", recipientCharacterId);
            resp.put("votes_for_recipient", votesForRecipient);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleAssignLoot(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Loot loot = campaign.lootById.get(lootId);
            if (loot == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!"open".equals(loot.status)) {
                sendJson(exchange, 409, mapOf("error", "loot not open"));
                return;
            }
            Map<String, Long> tally = new LinkedHashMap<>();
            for (String recipientCharacterId : loot.votesByVoter.values()) {
                tally.merge(recipientCharacterId, 1L, Long::sum);
            }
            if (tally.isEmpty()) {
                sendJson(exchange, 409, mapOf("error", "no votes"));
                return;
            }
            String winner = null;
            long winnerVotes = -1;
            boolean tie = false;
            for (Map.Entry<String, Long> entry : tally.entrySet()) {
                if (entry.getValue() > winnerVotes) {
                    winner = entry.getKey();
                    winnerVotes = entry.getValue();
                    tie = false;
                } else if (entry.getValue() == winnerVotes) {
                    tie = true;
                }
            }
            if (tie) {
                sendJson(exchange, 409, mapOf("error", "tied vote"));
                return;
            }
            PlayMember recipient = findMemberByCharacterId(campaign, winner);
            if (recipient == null) {
                sendJson(exchange, 409, mapOf("error", "invalid recipient"));
                return;
            }
            long total = recipient.inventoryItems.getOrDefault(loot.itemId, 0L) + loot.quantity;
            recipient.inventoryItems.put(loot.itemId, total);
            loot.recipientCharacterId = winner;
            loot.status = "assigned";

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("loot_id", loot.lootId);
            resp.put("recipient_character_id", winner);
            resp.put("item_id", loot.itemId);
            resp.put("quantity", loot.quantity);
            resp.put("votes", winnerVotes);
            resp.put("status", loot.status);
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> lootToMap(Loot loot) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("loot_id", loot.lootId);
        resp.put("item_id", loot.itemId);
        resp.put("quantity", loot.quantity);
        resp.put("status", loot.status);
        resp.put("recipient_character_id", loot.recipientCharacterId);
        Map<String, Long> tally = new LinkedHashMap<>();
        for (String recipientCharacterId : loot.votesByVoter.values()) {
            tally.merge(recipientCharacterId, 1L, Long::sum);
        }
        resp.put("votes", tally);
        return resp;
    }

    private static void handleCreatePlayNpc(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object npcIdObj = obj.get("npc_id");
        Object nameObj = obj.get("name");
        Object agendaObj = obj.get("agenda");
        Object publicStatusObj = obj.get("public_status");
        if (!(npcIdObj instanceof String) || ((String) npcIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(agendaObj instanceof String) || ((String) agendaObj).isEmpty()
                || !(publicStatusObj instanceof String) || ((String) publicStatusObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String npcId = (String) npcIdObj;

        synchronized (campaign) {
            if (campaign.npcsById.containsKey(npcId)) {
                sendJson(exchange, 409, mapOf("error", "npc already exists"));
                return;
            }
            PlayNpc npc = new PlayNpc();
            npc.npcId = npcId;
            npc.name = (String) nameObj;
            npc.agenda = (String) agendaObj;
            npc.publicStatus = (String) publicStatusObj;
            campaign.npcsById.put(npcId, npc);
            sendJson(exchange, 201, npcToDmMap(npc));
        }
    }

    private static void handleUpdatePlayNpcAgenda(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object agendaObj = obj.get("agenda");
        Object publicStatusObj = obj.get("public_status");
        if (!(agendaObj instanceof String) || ((String) agendaObj).isEmpty()
                || !(publicStatusObj instanceof String) || ((String) publicStatusObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            PlayNpc npc = campaign.npcsById.get(npcId);
            if (npc == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            npc.agenda = (String) agendaObj;
            npc.publicStatus = (String) publicStatusObj;
            sendJson(exchange, 200, npcToDmMap(npc));
        }
    }

    private static void handleGetPlayNpc(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayNpc npc = campaign.npcsById.get(npcId);
            if (npc == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            boolean isDm = user.username.equals(campaign.owner);
            sendJson(exchange, 200, isDm ? npcToDmMap(npc) : npcToPlayerMap(npc));
        }
    }

    private static Map<String, Object> npcToDmMap(PlayNpc npc) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("npc_id", npc.npcId);
        resp.put("name", npc.name);
        resp.put("agenda", npc.agenda);
        resp.put("public_status", npc.publicStatus);
        return resp;
    }

    private static Map<String, Object> npcToPlayerMap(PlayNpc npc) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("npc_id", npc.npcId);
        resp.put("name", npc.name);
        resp.put("public_status", npc.publicStatus);
        return resp;
    }

    private static void handleCreateNpcDialogue(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object dialogueIdObj = obj.get("dialogue_id");
        Object speakerObj = obj.get("speaker");
        Object textObj = obj.get("text");
        Object visibilityObj = obj.get("visibility");
        if (!(dialogueIdObj instanceof String) || ((String) dialogueIdObj).isEmpty()
                || !(speakerObj instanceof String) || ((String) speakerObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()
                || !(visibilityObj instanceof String)
                || !("public".equals(visibilityObj) || "private".equals(visibilityObj))) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String dialogueId = (String) dialogueIdObj;

        synchronized (campaign) {
            PlayNpc npc = campaign.npcsById.get(npcId);
            if (npc == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            for (DialogueEntry existing : npc.dialogueHistory) {
                if (existing.dialogueId.equals(dialogueId)) {
                    sendJson(exchange, 409, mapOf("error", "dialogue already exists"));
                    return;
                }
            }
            DialogueEntry entry = new DialogueEntry();
            entry.dialogueId = dialogueId;
            entry.speaker = (String) speakerObj;
            entry.text = (String) textObj;
            entry.visibility = (String) visibilityObj;
            npc.dialogueHistory.add(entry);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("dialogue_id", entry.dialogueId);
            resp.put("speaker", entry.speaker);
            resp.put("text", entry.text);
            resp.put("visibility", entry.visibility);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetNpcDialogue(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayNpc npc = campaign.npcsById.get(npcId);
            if (npc == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            boolean isDm = user.username.equals(campaign.owner);
            List<Map<String, Object>> entries = new ArrayList<>();
            for (DialogueEntry entry : npc.dialogueHistory) {
                if (!isDm && !"public".equals(entry.visibility)) {
                    continue;
                }
                Map<String, Object> entryMap = new LinkedHashMap<>();
                entryMap.put("dialogue_id", entry.dialogueId);
                entryMap.put("speaker", entry.speaker);
                entryMap.put("text", entry.text);
                entryMap.put("visibility", entry.visibility);
                entries.add(entryMap);
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("npc_id", npc.npcId);
            resp.put("entries", entries);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreatePlayFaction(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object factionIdObj = obj.get("faction_id");
        Object nameObj = obj.get("name");
        if (!(factionIdObj instanceof String) || ((String) factionIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String factionId = (String) factionIdObj;

        synchronized (campaign) {
            if (campaign.factionsById.containsKey(factionId)) {
                sendJson(exchange, 409, mapOf("error", "faction already exists"));
                return;
            }
            PlayFaction faction = new PlayFaction();
            faction.factionId = factionId;
            faction.name = (String) nameObj;
            campaign.factionsById.put(factionId, faction);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("faction_id", faction.factionId);
            resp.put("name", faction.name);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleChangeFactionReputation(HttpExchange exchange, String campaignId, String factionId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object characterIdObj = obj.get("character_id");
        Object deltaObj = obj.get("delta");
        Object reasonObj = obj.get("reason");
        if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()
                || !(deltaObj instanceof Number) || !isIntegral(deltaObj)
                || !(reasonObj instanceof String) || ((String) reasonObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long delta = ((Number) deltaObj).longValue();
        if (delta == 0 || delta < -25 || delta > 25) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String characterId = (String) characterIdObj;

        synchronized (campaign) {
            PlayFaction faction = campaign.factionsById.get(factionId);
            if (faction == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long before = faction.reputationByCharacter.getOrDefault(characterId, 0L);
            long after = Math.max(-100, Math.min(100, before + delta));
            faction.reputationByCharacter.put(characterId, after);

            ReputationEntry entry = new ReputationEntry();
            entry.factionId = factionId;
            entry.characterId = characterId;
            entry.reputation = after;
            entry.delta = delta;
            entry.reason = (String) reasonObj;
            faction.history.add(entry);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("faction_id", faction.factionId);
            resp.put("character_id", characterId);
            resp.put("reputation", after);
            resp.put("delta", delta);
            resp.put("reason", entry.reason);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetFactionReputation(HttpExchange exchange, String campaignId, String factionId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayFaction faction = campaign.factionsById.get(factionId);
            if (faction == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            boolean isDm = user.username.equals(campaign.owner);
            String ownCharacterId = null;
            if (!isDm) {
                PlayMember self = campaign.membersByUsername.get(user.username);
                ownCharacterId = self == null ? null : self.characterId;
            }
            List<Map<String, Object>> entries = new ArrayList<>();
            for (ReputationEntry entry : faction.history) {
                if (!isDm && !entry.characterId.equals(ownCharacterId)) {
                    continue;
                }
                Map<String, Object> entryMap = new LinkedHashMap<>();
                entryMap.put("faction_id", entry.factionId);
                entryMap.put("character_id", entry.characterId);
                entryMap.put("reputation", entry.reputation);
                entryMap.put("delta", entry.delta);
                entryMap.put("reason", entry.reason);
                entries.add(entryMap);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("faction_id", faction.factionId);
            resp.put("entries", entries);
            sendJson(exchange, 200, resp);
        }
    }

    /** True if {@code entityId} names an existing campaign member character or NPC. */
    private static boolean isCampaignEntity(PlayCampaign campaign, String entityId) {
        return campaign.characterIds.contains(entityId) || campaign.npcsById.containsKey(entityId);
    }

    private static Map<String, Object> relationshipToMap(Relationship relationship) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("source_id", relationship.sourceId);
        map.put("target_id", relationship.targetId);
        map.put("kind", relationship.kind);
        map.put("score", relationship.score);
        return map;
    }

    private static void handleCreateRelationship(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object sourceIdObj = obj.get("source_id");
        Object targetIdObj = obj.get("target_id");
        Object kindObj = obj.get("kind");
        Object scoreObj = obj.get("score");
        if (!(sourceIdObj instanceof String) || ((String) sourceIdObj).isEmpty()
                || !(targetIdObj instanceof String) || ((String) targetIdObj).isEmpty()
                || !(kindObj instanceof String) || ((String) kindObj).isEmpty()
                || !(scoreObj instanceof Number) || !isIntegral(scoreObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String sourceId = (String) sourceIdObj;
        String targetId = (String) targetIdObj;
        String kind = (String) kindObj;
        long score = ((Number) scoreObj).longValue();
        if (sourceId.equals(targetId) || score < -100 || score > 100) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            if (!isCampaignEntity(campaign, sourceId) || !isCampaignEntity(campaign, targetId)) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            for (Relationship existing : campaign.relationships) {
                if (existing.sourceId.equals(sourceId) && existing.targetId.equals(targetId)
                        && existing.kind.equals(kind)) {
                    sendJson(exchange, 409, mapOf("error", "relationship already exists"));
                    return;
                }
            }
            Relationship relationship = new Relationship();
            relationship.sourceId = sourceId;
            relationship.targetId = targetId;
            relationship.kind = kind;
            relationship.score = score;
            campaign.relationships.add(relationship);
            sendJson(exchange, 201, relationshipToMap(relationship));
        }
    }

    private static void handleUpdateRelationship(HttpExchange exchange, String campaignId, String sourceId,
            String targetId, String kind) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object scoreObj = obj.get("score");
        if (!(scoreObj instanceof Number) || !isIntegral(scoreObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long score = ((Number) scoreObj).longValue();
        if (score < -100 || score > 100) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            for (Relationship existing : campaign.relationships) {
                if (existing.sourceId.equals(sourceId) && existing.targetId.equals(targetId)
                        && existing.kind.equals(kind)) {
                    existing.score = score;
                    sendJson(exchange, 200, relationshipToMap(existing));
                    return;
                }
            }
            sendJson(exchange, 404, mapOf("error", "not found"));
        }
    }

    private static void handleGetRelationships(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> edges = new ArrayList<>();
            for (Relationship relationship : campaign.relationships) {
                edges.add(relationshipToMap(relationship));
            }
            sendJson(exchange, 200, mapOf("edges", edges));
        }
    }

    private static Map<String, Object> clueToMap(Clue clue) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("clue_id", clue.clueId);
        map.put("text", clue.text);
        map.put("audience", clue.audience);
        if ("character".equals(clue.audience)) {
            map.put("character_id", clue.characterId);
        }
        return map;
    }

    private static void handleCreateClue(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object clueIdObj = obj.get("clue_id");
        Object textObj = obj.get("text");
        Object audienceObj = obj.get("audience");
        Object characterIdObj = obj.get("character_id");
        if (!(clueIdObj instanceof String) || ((String) clueIdObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()
                || !(audienceObj instanceof String)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String audience = (String) audienceObj;
        if (!"character".equals(audience) && !"party".equals(audience) && !"hidden".equals(audience)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String clueId = (String) clueIdObj;
        String text = (String) textObj;

        synchronized (campaign) {
            if ("character".equals(audience)) {
                if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid request"));
                    return;
                }
                String characterId = (String) characterIdObj;
                if (!campaign.characterIds.contains(characterId)) {
                    sendJson(exchange, 400, mapOf("error", "invalid request"));
                    return;
                }
                if (campaign.clueIds.contains(clueId)) {
                    sendJson(exchange, 409, mapOf("error", "clue already exists"));
                    return;
                }
                Clue clue = new Clue();
                clue.clueId = clueId;
                clue.text = text;
                clue.audience = audience;
                clue.characterId = characterId;
                campaign.clues.add(clue);
                campaign.clueIds.add(clueId);
                sendJson(exchange, 201, clueToMap(clue));
                return;
            }

            if (characterIdObj != null) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (campaign.clueIds.contains(clueId)) {
                sendJson(exchange, 409, mapOf("error", "clue already exists"));
                return;
            }
            Clue clue = new Clue();
            clue.clueId = clueId;
            clue.text = text;
            clue.audience = audience;
            campaign.clues.add(clue);
            campaign.clueIds.add(clueId);
            sendJson(exchange, 201, clueToMap(clue));
        }
    }

    private static void handleGetClues(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            String ownCharacterId = null;
            if (!isDm) {
                PlayMember self = campaign.membersByUsername.get(user.username);
                ownCharacterId = self == null ? null : self.characterId;
            }
            List<Map<String, Object>> clues = new ArrayList<>();
            for (Clue clue : campaign.clues) {
                if (!isDm) {
                    if ("hidden".equals(clue.audience)) {
                        continue;
                    }
                    if ("character".equals(clue.audience)
                            && (ownCharacterId == null || !ownCharacterId.equals(clue.characterId))) {
                        continue;
                    }
                }
                clues.add(clueToMap(clue));
            }
            sendJson(exchange, 200, mapOf("clues", clues));
        }
    }

    private static Map<String, Object> playQuestToMap(PlayQuest quest) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("quest_id", quest.questId);
        map.put("title", quest.title);
        map.put("depends_on", new ArrayList<>(quest.dependsOn));
        map.put("state", quest.state);
        if (quest.rewardXp != null) {
            Map<String, Object> rewards = new LinkedHashMap<>();
            rewards.put("xp", quest.rewardXp);
            rewards.put("items", new LinkedHashMap<>(quest.rewardItems));
            map.put("rewards", rewards);
        }
        return map;
    }

    private static void handleCreatePlayQuest(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object questIdObj = obj.get("quest_id");
        Object titleObj = obj.get("title");
        Object dependsOnObj = obj.get("depends_on");
        if (!(questIdObj instanceof String) || ((String) questIdObj).isEmpty()
                || !(titleObj instanceof String) || ((String) titleObj).isEmpty()
                || !(dependsOnObj instanceof List)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String questId = (String) questIdObj;
        String title = (String) titleObj;
        List<?> dependsOnRaw = (List<?>) dependsOnObj;
        List<String> dependsOn = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object item : dependsOnRaw) {
            if (!(item instanceof String) || ((String) item).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid depends_on"));
                return;
            }
            String depId = (String) item;
            if (depId.equals(questId) || !seen.add(depId)) {
                sendJson(exchange, 400, mapOf("error", "invalid depends_on"));
                return;
            }
            dependsOn.add(depId);
        }

        synchronized (campaign) {
            if (campaign.questsById.containsKey(questId)) {
                sendJson(exchange, 409, mapOf("error", "quest already exists"));
                return;
            }
            for (String depId : dependsOn) {
                if (!campaign.questsById.containsKey(depId)) {
                    sendJson(exchange, 400, mapOf("error", "invalid depends_on"));
                    return;
                }
            }
            PlayQuest quest = new PlayQuest();
            quest.questId = questId;
            quest.title = title;
            quest.dependsOn = dependsOn;
            quest.state = "locked";
            campaign.questsById.put(questId, quest);
            sendJson(exchange, 201, playQuestToMap(quest));
        }
    }

    private static void handleGetPlayQuests(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> quests = new ArrayList<>();
            for (PlayQuest quest : campaign.questsById.values()) {
                quests.add(playQuestToMap(quest));
            }
            sendJson(exchange, 200, mapOf("quests", quests));
        }
    }

    private static void handleUpdatePlayQuestState(HttpExchange exchange, String campaignId, String questId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object stateObj = obj.get("state");
        if (!(stateObj instanceof String)
                || (!"active".equals(stateObj) && !"completed".equals(stateObj))) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String newState = (String) stateObj;

        synchronized (campaign) {
            PlayQuest quest = campaign.questsById.get(questId);
            if (quest == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("active".equals(newState)) {
                if (!"locked".equals(quest.state)) {
                    sendJson(exchange, 409, mapOf("error", "invalid transition"));
                    return;
                }
                for (String depId : quest.dependsOn) {
                    PlayQuest dep = campaign.questsById.get(depId);
                    if (dep == null || !"completed".equals(dep.state)) {
                        sendJson(exchange, 409, mapOf("error", "prerequisites not met"));
                        return;
                    }
                }
                quest.state = "active";
            } else {
                if (!"active".equals(quest.state)) {
                    sendJson(exchange, 409, mapOf("error", "invalid transition"));
                    return;
                }
                quest.state = "completed";
            }
            sendJson(exchange, 200, playQuestToMap(quest));
        }
    }

    private static void handleConfigureQuestRewards(HttpExchange exchange, String campaignId, String questId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        synchronized (campaign) {
            PlayQuest quest = campaign.questsById.get(questId);
            if (quest == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!"locked".equals(quest.state) && !"active".equals(quest.state)) {
                sendJson(exchange, 409, mapOf("error", "quest already completed"));
                return;
            }
            Object xpObj = obj.get("xp");
            Object itemsObj = obj.get("items");
            if (!(xpObj instanceof Number) || !isIntegral(xpObj) || ((Number) xpObj).longValue() < 0
                    || !(itemsObj instanceof Map)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            long xp = ((Number) xpObj).longValue();
            Map<String, Long> items = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) itemsObj).entrySet()) {
                if (!(entry.getKey() instanceof String)) {
                    sendJson(exchange, 400, mapOf("error", "invalid items"));
                    return;
                }
                String itemId = (String) entry.getKey();
                Object quantityObj = entry.getValue();
                if (!INVENTORY_ITEM_CATALOG.contains(itemId) || !(quantityObj instanceof Number)
                        || !isIntegral(quantityObj) || ((Number) quantityObj).longValue() <= 0) {
                    sendJson(exchange, 400, mapOf("error", "invalid items"));
                    return;
                }
                items.put(itemId, ((Number) quantityObj).longValue());
            }
            quest.rewardXp = xp;
            quest.rewardItems = items;
            sendJson(exchange, 200, playQuestToMap(quest));
        }
    }

    private static void handleAwardQuestRewards(HttpExchange exchange, String campaignId, String questId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayQuest quest = campaign.questsById.get(questId);
            if (quest == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!"completed".equals(quest.state) || quest.rewardXp == null || quest.rewardsAwarded) {
                sendJson(exchange, 409, mapOf("error", "rewards not available"));
                return;
            }
            quest.rewardsAwarded = true;
            for (PlayMember member : campaign.membersByUsername.values()) {
                member.questRewardXp += quest.rewardXp;
                for (Map.Entry<String, Long> item : quest.rewardItems.entrySet()) {
                    member.questRewardItems.merge(item.getKey(), item.getValue(), Long::sum);
                    member.inventoryItems.merge(item.getKey(), item.getValue(), Long::sum);
                }
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("quest_id", quest.questId);
            resp.put("awarded", true);
            resp.put("xp", quest.rewardXp);
            resp.put("items", new LinkedHashMap<>(quest.rewardItems));
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetCharacterRewards(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", characterId);
            resp.put("xp", member.questRewardXp);
            resp.put("items", new LinkedHashMap<>(member.questRewardItems));
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> worldEventToMap(WorldEvent event) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("event_id", event.eventId);
        map.put("turn_number", event.turnNumber);
        map.put("title", event.title);
        map.put("text", event.text);
        map.put("status", event.status);
        if ("resolved".equals(event.status)) {
            Map<String, Object> resolution = new LinkedHashMap<>();
            resolution.put("turn_number", event.resolutionTurnNumber);
            resolution.put("text", event.resolutionText);
            map.put("resolution", resolution);
        }
        return map;
    }

    private static void handleCreateWorldEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object eventIdObj = obj.get("event_id");
        Object turnNumberObj = obj.get("turn_number");
        Object titleObj = obj.get("title");
        Object textObj = obj.get("text");
        if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                || !(titleObj instanceof String) || ((String) titleObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()
                || !(turnNumberObj instanceof Number) || !isIntegral(turnNumberObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String eventId = (String) eventIdObj;
        String title = (String) titleObj;
        String text = (String) textObj;
        int turnNumber = ((Number) turnNumberObj).intValue();

        synchronized (campaign) {
            if (turnNumber < campaign.turnNumber) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (campaign.worldEventsById.containsKey(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event already exists"));
                return;
            }
            WorldEvent event = new WorldEvent();
            event.eventId = eventId;
            event.turnNumber = turnNumber;
            event.title = title;
            event.text = text;
            event.status = "scheduled";
            campaign.worldEventsById.put(eventId, event);
            campaign.worldEventsInOrder.add(event);
            sendJson(exchange, 201, worldEventToMap(event));
        }
    }

    private static void handleGetWorldEvents(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<WorldEvent> sorted = new ArrayList<>(campaign.worldEventsInOrder);
            sorted.sort((a, b) -> Integer.compare(a.turnNumber, b.turnNumber));
            List<Map<String, Object>> events = new ArrayList<>();
            for (WorldEvent event : sorted) {
                events.add(worldEventToMap(event));
            }
            sendJson(exchange, 200, mapOf("events", events));
        }
    }

    private static void handleResolveWorldEvent(HttpExchange exchange, String campaignId, String eventId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object textObj = obj.get("text");
        if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String text = (String) textObj;

        synchronized (campaign) {
            WorldEvent event = campaign.worldEventsById.get(eventId);
            if (event == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("resolved".equals(event.status)) {
                sendJson(exchange, 409, mapOf("error", "already resolved"));
                return;
            }
            if (campaign.turnNumber != event.turnNumber) {
                sendJson(exchange, 409, mapOf("error", "turn mismatch"));
                return;
            }
            event.status = "resolved";
            event.resolutionTurnNumber = campaign.turnNumber;
            event.resolutionText = text;
            sendJson(exchange, 201, worldEventToMap(event));
        }
    }

    private static final Map<String, Integer> SEASON_OFFSETS = mapOfInt(
            "spring", 0, "summer", 1, "autumn", 2, "winter", 3);

    private static Map<String, Integer> mapOfInt(String k1, int v1, String k2, int v2, String k3, int v3, String k4, int v4) {
        Map<String, Integer> map = new LinkedHashMap<>();
        map.put(k1, v1);
        map.put(k2, v2);
        map.put(k3, v3);
        map.put(k4, v4);
        return map;
    }

    private static String computeWeather(int day, String season) {
        int offset = SEASON_OFFSETS.get(season);
        int index = (day + offset) % 4;
        switch (index) {
            case 0: return "clear";
            case 1: return "rain";
            case 2: return "wind";
            default: return "snow";
        }
    }

    private static Map<String, Object> calendarToMap(Calendar calendar) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("day", calendar.day);
        map.put("season", calendar.season);
        map.put("weather", computeWeather(calendar.day, calendar.season));
        return map;
    }

    private static void handleInitCalendar(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object dayObj = obj.get("day");
        Object seasonObj = obj.get("season");
        if (!(dayObj instanceof Number) || !isIntegral(dayObj) || ((Number) dayObj).intValue() < 1
                || !(seasonObj instanceof String) || !SEASON_OFFSETS.containsKey(seasonObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        int day = ((Number) dayObj).intValue();
        String season = (String) seasonObj;

        synchronized (campaign) {
            if (campaign.calendar != null) {
                sendJson(exchange, 409, mapOf("error", "calendar already initialized"));
                return;
            }
            Calendar calendar = new Calendar();
            calendar.day = day;
            calendar.season = season;
            campaign.calendar = calendar;
            sendJson(exchange, 201, calendarToMap(calendar));
        }
    }

    private static void handleGetCalendar(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (campaign.calendar == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, calendarToMap(campaign.calendar));
        }
    }

    private static void handleAdvanceCalendar(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object daysObj = obj.get("days");
        if (!(daysObj instanceof Number) || !isIntegral(daysObj)
                || ((Number) daysObj).intValue() < 1 || ((Number) daysObj).intValue() > 30) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        int days = ((Number) daysObj).intValue();

        synchronized (campaign) {
            if (campaign.calendar == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            campaign.calendar.day += days;
            sendJson(exchange, 200, calendarToMap(campaign.calendar));
        }
    }

    private static final Set<String> SETTLEMENT_AVAILABILITIES = Set.of("open", "limited", "closed");

    /**
     * Validates a services payload, returning trimmed, duplicate-free values
     * in request order, or null if the payload is not a nonempty array of
     * nonempty strings with unique normalized values.
     */
    private static List<String> validateSettlementServices(Object servicesObj) {
        if (!(servicesObj instanceof List)) {
            return null;
        }
        List<?> raw = (List<?>) servicesObj;
        if (raw.isEmpty()) {
            return null;
        }
        List<String> normalized = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object item : raw) {
            if (!(item instanceof String)) {
                return null;
            }
            String trimmed = ((String) item).trim();
            if (trimmed.isEmpty() || !seen.add(trimmed)) {
                return null;
            }
            normalized.add(trimmed);
        }
        return normalized;
    }

    private static Map<String, Object> settlementToMap(Settlement settlement, List<String> discoveredByView) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("settlement_id", settlement.settlementId);
        map.put("name", settlement.name);
        map.put("services", new ArrayList<>(settlement.services));
        map.put("availability", settlement.availability);
        map.put("discovered_by", discoveredByView);
        return map;
    }

    private static void handleCreateSettlement(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object settlementIdObj = obj.get("settlement_id");
        Object nameObj = obj.get("name");
        Object availabilityObj = obj.get("availability");
        if (!(settlementIdObj instanceof String) || ((String) settlementIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(availabilityObj instanceof String) || !SETTLEMENT_AVAILABILITIES.contains(availabilityObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        List<String> services = validateSettlementServices(obj.get("services"));
        if (services == null) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String settlementId = (String) settlementIdObj;

        synchronized (campaign) {
            if (campaign.settlementsById.containsKey(settlementId)) {
                sendJson(exchange, 409, mapOf("error", "settlement already exists"));
                return;
            }
            Settlement settlement = new Settlement();
            settlement.settlementId = settlementId;
            settlement.name = (String) nameObj;
            settlement.services = services;
            settlement.availability = (String) availabilityObj;
            campaign.settlementsById.put(settlementId, settlement);
            campaign.settlementsInOrder.add(settlement);
            sendJson(exchange, 201, settlementToMap(settlement, new ArrayList<>(settlement.discoveredBy)));
        }
    }

    private static void handleUpdateSettlement(HttpExchange exchange, String campaignId, String settlementId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object nameObj = obj.get("name");
        Object availabilityObj = obj.get("availability");
        if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(availabilityObj instanceof String) || !SETTLEMENT_AVAILABILITIES.contains(availabilityObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        List<String> services = validateSettlementServices(obj.get("services"));
        if (services == null) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            settlement.name = (String) nameObj;
            settlement.services = services;
            settlement.availability = (String) availabilityObj;
            sendJson(exchange, 200, settlementToMap(settlement, new ArrayList<>(settlement.discoveredBy)));
        }
    }

    private static void handleDiscoverSettlement(HttpExchange exchange, String campaignId, String settlementId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            if (isDm) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            PlayMember self = campaign.membersByUsername.get(user.username);
            if (self == null) {
                sendJson(exchange, 403, mapOf("error", "not a campaign member"));
                return;
            }
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            String characterId = self.characterId;
            int status;
            if (settlement.discoveredBy.contains(characterId)) {
                status = 200;
            } else {
                settlement.discoveredBy.add(characterId);
                status = 201;
            }
            sendJson(exchange, status, settlementToMap(settlement, List.of(characterId)));
        }
    }

    private static void handleGetSettlements(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            String ownCharacterId = null;
            if (!isDm) {
                PlayMember self = campaign.membersByUsername.get(user.username);
                ownCharacterId = self == null ? null : self.characterId;
            }
            List<Map<String, Object>> settlements = new ArrayList<>();
            for (Settlement settlement : campaign.settlementsInOrder) {
                if (isDm) {
                    settlements.add(settlementToMap(settlement, new ArrayList<>(settlement.discoveredBy)));
                } else if (ownCharacterId != null && settlement.discoveredBy.contains(ownCharacterId)) {
                    settlements.add(settlementToMap(settlement, List.of(ownCharacterId)));
                }
            }
            sendJson(exchange, 200, mapOf("settlements", settlements));
        }
    }

    private static Map<String, Object> shopToMap(Shop shop) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("shop_id", shop.shopId);
        map.put("name", shop.name);
        map.put("stock", new LinkedHashMap<>(shop.stock));
        map.put("buy_price", shop.buyPrice);
        map.put("sell_price", shop.sellPrice);
        return map;
    }

    /**
     * Validates a shop stock payload, returning a nonempty ordered map of
     * catalog item id -> positive quantity, or null if the payload is not a
     * nonempty object of valid catalog ids mapped to positive integers.
     */
    private static Map<String, Long> validateShopStock(Object stockObj) {
        if (!(stockObj instanceof Map)) {
            return null;
        }
        Map<?, ?> raw = (Map<?, ?>) stockObj;
        if (raw.isEmpty()) {
            return null;
        }
        Map<String, Long> normalized = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String)) {
                return null;
            }
            String itemId = (String) entry.getKey();
            Object quantityObj = entry.getValue();
            if (!INVENTORY_ITEM_CATALOG.contains(itemId) || !(quantityObj instanceof Number)
                    || !isIntegral(quantityObj) || ((Number) quantityObj).longValue() <= 0) {
                return null;
            }
            normalized.put(itemId, ((Number) quantityObj).longValue());
        }
        return normalized;
    }

    private static Map<String, Object> recipeToMap(Recipe recipe) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("recipe_id", recipe.recipeId);
        map.put("name", recipe.name);
        map.put("ingredients", new LinkedHashMap<>(recipe.ingredients));
        map.put("output_item", recipe.outputItem);
        map.put("output_quantity", recipe.outputQuantity);
        return map;
    }

    /**
     * Validates a recipe ingredients payload, returning a nonempty ordered map
     * of catalog item id -> positive quantity, or null if the payload is not a
     * nonempty object of valid catalog ids mapped to positive integers.
     */
    private static Map<String, Long> validateIngredients(Object ingredientsObj) {
        if (!(ingredientsObj instanceof Map)) {
            return null;
        }
        Map<?, ?> raw = (Map<?, ?>) ingredientsObj;
        if (raw.isEmpty()) {
            return null;
        }
        Map<String, Long> normalized = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String)) {
                return null;
            }
            String itemId = (String) entry.getKey();
            Object quantityObj = entry.getValue();
            if (!INVENTORY_ITEM_CATALOG.contains(itemId) || !(quantityObj instanceof Number)
                    || !isIntegral(quantityObj) || ((Number) quantityObj).longValue() <= 0) {
                return null;
            }
            normalized.put(itemId, ((Number) quantityObj).longValue());
        }
        return normalized;
    }

    private static void handleCreateRecipe(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object recipeIdObj = obj.get("recipe_id");
        Object nameObj = obj.get("name");
        Object outputItemObj = obj.get("output_item");
        Object outputQuantityObj = obj.get("output_quantity");
        if (!(recipeIdObj instanceof String) || ((String) recipeIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(outputItemObj instanceof String) || !INVENTORY_ITEM_CATALOG.contains(outputItemObj)
                || !(outputQuantityObj instanceof Number) || !isIntegral(outputQuantityObj)
                || ((Number) outputQuantityObj).longValue() <= 0) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        Map<String, Long> ingredients = validateIngredients(obj.get("ingredients"));
        if (ingredients == null) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String recipeId = (String) recipeIdObj;

        synchronized (campaign) {
            if (campaign.recipesById.containsKey(recipeId)) {
                sendJson(exchange, 409, mapOf("error", "recipe already exists"));
                return;
            }
            Recipe recipe = new Recipe();
            recipe.recipeId = recipeId;
            recipe.name = (String) nameObj;
            recipe.ingredients.putAll(ingredients);
            recipe.outputItem = (String) outputItemObj;
            recipe.outputQuantity = ((Number) outputQuantityObj).longValue();
            campaign.recipesById.put(recipeId, recipe);
            campaign.recipesInOrder.add(recipe);
            sendJson(exchange, 201, recipeToMap(recipe));
        }
    }

    private static void handleGetRecipes(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> recipes = new ArrayList<>();
            for (Recipe recipe : campaign.recipesInOrder) {
                recipes.add(recipeToMap(recipe));
            }
            sendJson(exchange, 200, mapOf("recipes", recipes));
        }
    }

    private static void handleCraftRecipe(HttpExchange exchange, String campaignId, String recipeId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object characterIdObj = obj.get("character_id");

        synchronized (campaign) {
            Recipe recipe = campaign.recipesById.get(recipeId);
            if (recipe == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String characterId = (String) characterIdObj;
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            for (Map.Entry<String, Long> entry : recipe.ingredients.entrySet()) {
                long held = member.inventoryItems.getOrDefault(entry.getKey(), 0L);
                if (held < entry.getValue()) {
                    sendJson(exchange, 409, mapOf("error", "insufficient ingredients"));
                    return;
                }
            }
            for (Map.Entry<String, Long> entry : recipe.ingredients.entrySet()) {
                long remaining = member.inventoryItems.getOrDefault(entry.getKey(), 0L) - entry.getValue();
                if (remaining <= 0) {
                    member.inventoryItems.remove(entry.getKey());
                } else {
                    member.inventoryItems.put(entry.getKey(), remaining);
                }
            }
            member.inventoryItems.merge(recipe.outputItem, recipe.outputQuantity, Long::sum);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("recipe_id", recipe.recipeId);
            resp.put("output_item", recipe.outputItem);
            resp.put("output_quantity", recipe.outputQuantity);
            sendJson(exchange, 201, resp);
        }
    }

    private static Map<String, Object> downtimeActivityToMap(DowntimeActivity activity) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("activity_id", activity.activityId);
        map.put("name", activity.name);
        map.put("cycles_required", activity.cyclesRequired);
        return map;
    }

    private static Map<String, Object> downtimeAllocationToMap(DowntimeAllocation allocation) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("character_id", allocation.characterId);
        map.put("activity_id", allocation.activityId);
        map.put("cycles_completed", allocation.cyclesCompleted);
        map.put("completions", allocation.completions);
        return map;
    }

    private static String downtimeAllocationKey(String characterId, String activityId) {
        return characterId + "|" + activityId;
    }

    private static void handleCreateDowntimeActivity(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object activityIdObj = obj.get("activity_id");
        Object nameObj = obj.get("name");
        Object cyclesRequiredObj = obj.get("cycles_required");
        if (!(activityIdObj instanceof String) || ((String) activityIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(cyclesRequiredObj instanceof Number) || !isIntegral(cyclesRequiredObj)
                || ((Number) cyclesRequiredObj).longValue() < 1
                || ((Number) cyclesRequiredObj).longValue() > 10) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String activityId = (String) activityIdObj;

        synchronized (campaign) {
            if (campaign.downtimeActivitiesById.containsKey(activityId)) {
                sendJson(exchange, 409, mapOf("error", "activity already exists"));
                return;
            }
            DowntimeActivity activity = new DowntimeActivity();
            activity.activityId = activityId;
            activity.name = (String) nameObj;
            activity.cyclesRequired = ((Number) cyclesRequiredObj).longValue();
            campaign.downtimeActivitiesById.put(activityId, activity);
            sendJson(exchange, 201, downtimeActivityToMap(activity));
        }
    }

    private static void handleCreateDowntimeAllocation(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object activityIdObj = obj.get("activity_id");
        if (!(activityIdObj instanceof String) || ((String) activityIdObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String activityId = (String) activityIdObj;

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            DowntimeActivity activity = campaign.downtimeActivitiesById.get(activityId);
            if (activity == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            String key = downtimeAllocationKey(characterId, activityId);
            if (campaign.downtimeAllocationsByKey.containsKey(key)) {
                sendJson(exchange, 409, mapOf("error", "allocation already exists"));
                return;
            }
            DowntimeAllocation allocation = new DowntimeAllocation();
            allocation.characterId = characterId;
            allocation.activityId = activityId;
            allocation.cyclesCompleted = 0;
            allocation.completions = 0;
            campaign.downtimeAllocationsByKey.put(key, allocation);
            sendJson(exchange, 201, downtimeAllocationToMap(allocation));
        }
    }

    private static void handleProgressDowntimeAllocation(HttpExchange exchange, String campaignId,
            String characterId, String activityId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            DowntimeActivity activity = campaign.downtimeActivitiesById.get(activityId);
            if (activity == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            DowntimeAllocation allocation = campaign.downtimeAllocationsByKey.get(downtimeAllocationKey(characterId, activityId));
            if (allocation == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            allocation.cyclesCompleted++;
            if (allocation.cyclesCompleted >= activity.cyclesRequired) {
                allocation.cyclesCompleted = 0;
                allocation.completions++;
            }
            sendJson(exchange, 200, downtimeAllocationToMap(allocation));
        }
    }

    private static void handleGetDowntimeAllocation(HttpExchange exchange, String campaignId, String characterId,
            String activityId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            DowntimeActivity activity = campaign.downtimeActivitiesById.get(activityId);
            if (activity == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            DowntimeAllocation allocation = campaign.downtimeAllocationsByKey.get(downtimeAllocationKey(characterId, activityId));
            if (allocation == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, downtimeAllocationToMap(allocation));
        }
    }

    private static void handleCreateShop(HttpExchange exchange, String campaignId, String settlementId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object shopIdObj = obj.get("shop_id");
        Object nameObj = obj.get("name");
        Object buyPriceObj = obj.get("buy_price");
        Object sellPriceObj = obj.get("sell_price");
        if (!(shopIdObj instanceof String) || ((String) shopIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(buyPriceObj instanceof Number) || !isIntegral(buyPriceObj)
                || ((Number) buyPriceObj).longValue() <= 0
                || !(sellPriceObj instanceof Number) || !isIntegral(sellPriceObj)
                || ((Number) sellPriceObj).longValue() < 0) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        Map<String, Long> stock = validateShopStock(obj.get("stock"));
        if (stock == null) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String shopId = (String) shopIdObj;

        synchronized (campaign) {
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (settlement.shopsById.containsKey(shopId)) {
                sendJson(exchange, 409, mapOf("error", "shop already exists"));
                return;
            }
            Shop shop = new Shop();
            shop.shopId = shopId;
            shop.name = (String) nameObj;
            shop.stock.putAll(stock);
            shop.buyPrice = ((Number) buyPriceObj).longValue();
            shop.sellPrice = ((Number) sellPriceObj).longValue();
            settlement.shopsById.put(shopId, shop);
            sendJson(exchange, 201, shopToMap(shop));
        }
    }

    private static void handleGetShop(HttpExchange exchange, String campaignId, String settlementId, String shopId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Shop shop = settlement.shopsById.get(shopId);
            if (shop == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            boolean isDm = user.username.equals(campaign.owner);
            if (!isDm) {
                PlayMember self = campaign.membersByUsername.get(user.username);
                String ownCharacterId = self == null ? null : self.characterId;
                if (ownCharacterId == null || !settlement.discoveredBy.contains(ownCharacterId)) {
                    sendJson(exchange, 404, mapOf("error", "not found"));
                    return;
                }
            }
            sendJson(exchange, 200, shopToMap(shop));
        }
    }

    private static void handleShopBuy(HttpExchange exchange, String campaignId, String settlementId, String shopId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object characterIdObj = obj.get("character_id");
        Object itemIdObj = obj.get("item_id");
        Object quantityObj = obj.get("quantity");

        synchronized (campaign) {
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Shop shop = settlement.shopsById.get(shopId);
            if (shop == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String characterId = (String) characterIdObj;
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (!(itemIdObj instanceof String) || !INVENTORY_ITEM_CATALOG.contains(itemIdObj)
                    || !(quantityObj instanceof Number) || !isIntegral(quantityObj)
                    || ((Number) quantityObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String itemId = (String) itemIdObj;
            long quantity = ((Number) quantityObj).longValue();
            long currentStock = shop.stock.getOrDefault(itemId, 0L);
            long cost = shop.buyPrice * quantity;
            if (currentStock < quantity || member.gold < cost) {
                sendJson(exchange, 409, mapOf("error", "insufficient stock or funds"));
                return;
            }
            shop.stock.put(itemId, currentStock - quantity);
            member.gold -= cost;
            member.inventoryItems.merge(itemId, quantity, Long::sum);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("item_id", itemId);
            resp.put("quantity", quantity);
            resp.put("gold", member.gold);
            resp.put("stock", shop.stock.get(itemId));
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleShopSell(HttpExchange exchange, String campaignId, String settlementId, String shopId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object characterIdObj = obj.get("character_id");
        Object itemIdObj = obj.get("item_id");
        Object quantityObj = obj.get("quantity");

        synchronized (campaign) {
            Settlement settlement = campaign.settlementsById.get(settlementId);
            if (settlement == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Shop shop = settlement.shopsById.get(shopId);
            if (shop == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String characterId = (String) characterIdObj;
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (!(itemIdObj instanceof String) || !INVENTORY_ITEM_CATALOG.contains(itemIdObj)
                    || !(quantityObj instanceof Number) || !isIntegral(quantityObj)
                    || ((Number) quantityObj).longValue() <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String itemId = (String) itemIdObj;
            long quantity = ((Number) quantityObj).longValue();
            long currentQuantity = member.inventoryItems.getOrDefault(itemId, 0L);
            if (currentQuantity < quantity) {
                sendJson(exchange, 409, mapOf("error", "insufficient inventory"));
                return;
            }
            long remaining = currentQuantity - quantity;
            if (remaining <= 0) {
                member.inventoryItems.remove(itemId);
            } else {
                member.inventoryItems.put(itemId, remaining);
            }
            member.gold += shop.sellPrice * quantity;
            long newStock = shop.stock.getOrDefault(itemId, 0L) + quantity;
            shop.stock.put(itemId, newStock);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("item_id", itemId);
            resp.put("quantity", quantity);
            resp.put("gold", member.gold);
            resp.put("stock", newStock);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handlePutEquipment(HttpExchange exchange, String campaignId, String characterId, String slot) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object itemIdObj = obj.get("item_id");
        if (!EQUIPMENT_SLOTS.contains(slot) || !(itemIdObj instanceof String)
                || !INVENTORY_ITEM_CATALOG.contains(itemIdObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String itemId = (String) itemIdObj;
        String legalSlot = ITEM_SLOT.get(itemId);
        if (legalSlot == null || !legalSlot.equals(slot)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            long held = member.inventoryItems.getOrDefault(itemId, 0L);
            if (held <= 0) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            member.equipment.put(slot, itemId);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("slot", slot);
            resp.put("item_id", itemId);
            resp.put("attuned", slot.equals(member.attunedSlot));
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetEquipment(HttpExchange exchange, String campaignId, String characterId, String slot) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        if (!EQUIPMENT_SLOTS.contains(slot)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            String itemId = member.equipment.getOrDefault(slot, "");

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("slot", slot);
            resp.put("item_id", itemId);
            resp.put("attuned", slot.equals(member.attunedSlot));
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleAttuneEquipment(HttpExchange exchange, String campaignId, String characterId, String slot) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        if (!EQUIPMENT_SLOTS.contains(slot)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            String itemId = member.equipment.get(slot);
            if (itemId == null || !ATTUNABLE_ITEMS.contains(itemId)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            if (member.attunedSlot != null) {
                sendJson(exchange, 409, mapOf("error", "already attuned"));
                return;
            }
            member.attunedSlot = slot;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("slot", slot);
            resp.put("item_id", itemId);
            resp.put("attuned", true);
            resp.put("attunement_count", 1);
            resp.put("max_attunements", 1);
            sendJson(exchange, 200, resp);
        }
    }

    /** Catalog of valid inventory item ids for {@code /inventory/items}. */
    private static final Set<String> INVENTORY_ITEM_CATALOG = Set.of("healing-potion", "torch",
            "leather-armor", "ring-of-protection", "amulet-of-health");

    /** Valid equipment slots. */
    private static final Set<String> EQUIPMENT_SLOTS = Set.of("armor", "accessory");

    /** Item id -> the single slot it may be equipped into. */
    private static final Map<String, String> ITEM_SLOT = Map.of(
            "leather-armor", "armor",
            "ring-of-protection", "accessory",
            "amulet-of-health", "accessory");

    /** Accessory items that support attunement. */
    private static final Set<String> ATTUNABLE_ITEMS = Set.of("ring-of-protection", "amulet-of-health");

    /** Catalog items that may be consumed via {@code /inventory/items/{item_id}/consume}. */
    private static final Set<String> CONSUMABLE_ITEMS = Set.of("healing-potion");

    private static void handleConsumeInventoryItem(HttpExchange exchange, String campaignId, String characterId, String itemId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        if (!CONSUMABLE_ITEMS.contains(itemId)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            long held = member.inventoryItems.getOrDefault(itemId, 0L);
            if (held <= 0) {
                sendJson(exchange, 409, mapOf("error", "no held stack"));
                return;
            }
            long remaining = held - 1;
            member.inventoryItems.put(itemId, remaining);

            Map<String, Object> effect = new LinkedHashMap<>();
            effect.put("type", "healing");
            effect.put("hp_restored", 5);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("item_id", itemId);
            resp.put("quantity_consumed", 1);
            resp.put("total_quantity", remaining);
            resp.put("effect", effect);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleAddInventoryItem(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object itemIdObj = obj.get("item_id");
        Object quantityObj = obj.get("quantity");
        if (!(itemIdObj instanceof String) || !INVENTORY_ITEM_CATALOG.contains(itemIdObj)
                || !(quantityObj instanceof Number) || !isIntegral(quantityObj)
                || ((Number) quantityObj).longValue() <= 0) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String itemId = (String) itemIdObj;
        long quantity = ((Number) quantityObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            long total = member.inventoryItems.getOrDefault(itemId, 0L) + quantity;
            member.inventoryItems.put(itemId, total);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("item_id", itemId);
            resp.put("quantity", quantity);
            resp.put("total_quantity", total);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetInventoryItems(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            List<String> itemIds = new ArrayList<>(member.inventoryItems.keySet());
            itemIds.sort(null);
            List<Map<String, Object>> items = new ArrayList<>();
            for (String itemId : itemIds) {
                long qty = member.inventoryItems.get(itemId);
                if (qty <= 0) {
                    continue;
                }
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("item_id", itemId);
                item.put("quantity", qty);
                items.add(item);
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("items", items);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleRemoveInventoryItem(HttpExchange exchange, String campaignId, String characterId, String itemId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object quantityObj = obj.get("quantity");
        if (!INVENTORY_ITEM_CATALOG.contains(itemId)
                || !(quantityObj instanceof Number) || !isIntegral(quantityObj)
                || ((Number) quantityObj).longValue() <= 0) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long quantity = ((Number) quantityObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            long held = member.inventoryItems.getOrDefault(itemId, 0L);
            if (quantity > held) {
                sendJson(exchange, 409, mapOf("error", "insufficient quantity"));
                return;
            }
            long remaining = held - quantity;
            member.inventoryItems.put(itemId, remaining);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("item_id", itemId);
            resp.put("quantity", quantity);
            resp.put("total_quantity", remaining);
            sendJson(exchange, 200, resp);
        }
    }

    /** Spellcasting ability per class, used to compute maximum prepared spells. */
    private static final Map<String, String> CLASS_SPELLCASTING_ABILITY = Map.ofEntries(
            Map.entry("wizard", "int"),
            Map.entry("sorcerer", "cha"),
            Map.entry("warlock", "cha"),
            Map.entry("bard", "cha"),
            Map.entry("cleric", "wis"),
            Map.entry("druid", "wis"),
            Map.entry("paladin", "cha"),
            Map.entry("ranger", "wis"));

    private static int maxPreparedSpells(PlayMember member) {
        String ability = CLASS_SPELLCASTING_ABILITY.get(member.characterClass);
        int abilityModifier = ability == null ? 0 : member.abilityModifiers.getOrDefault(ability, 0);
        return (int) Math.max(1, member.level + abilityModifier);
    }

    private static void handlePutPreparedSpells(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object spellIdsObj = obj.get("spell_ids");
        if (!(spellIdsObj instanceof List)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        List<?> spellIdsRaw = (List<?>) spellIdsObj;
        List<String> spellIds = new ArrayList<>();
        for (Object item : spellIdsRaw) {
            if (!(item instanceof String) || ((String) item).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid spell_ids"));
                return;
            }
            spellIds.add((String) item);
        }

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<String, Integer> knownSpells = CLASS_SPELLS.get(member.characterClass);
            if (knownSpells == null) {
                sendJson(exchange, 400, mapOf("error", "not a spellcasting class"));
                return;
            }
            for (String spellId : spellIds) {
                if (!member.spellsById.containsKey(spellId)) {
                    sendJson(exchange, 400, mapOf("error", "unknown spell " + spellId));
                    return;
                }
            }
            int maxPrepared = maxPreparedSpells(member);
            if (spellIds.size() > maxPrepared) {
                sendJson(exchange, 400, mapOf("error", "too many prepared spells"));
                return;
            }
            member.preparedSpellIds.clear();
            member.preparedSpellIds.addAll(spellIds);
            sendJson(exchange, 200, preparedSpellsResponse(member, maxPrepared));
        }
    }

    private static void handleGetPreparedSpells(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, preparedSpellsResponse(member, maxPreparedSpells(member)));
        }
    }

    private static Map<String, Object> preparedSpellsResponse(PlayMember member, int maxPrepared) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("character_id", member.characterId);
        resp.put("prepared_spells", new ArrayList<>(member.preparedSpellIds));
        resp.put("max_prepared", maxPrepared);
        return resp;
    }

    /** Spells each class may know, keyed by class then spell_id, valued by canonical spell level. */
    private static final Map<String, Map<String, Integer>> CLASS_SPELLS = Map.ofEntries(
            Map.entry("wizard", Map.ofEntries(
                    Map.entry("fire-bolt", 0), Map.entry("mage-hand", 0), Map.entry("prestidigitation", 0),
                    Map.entry("magic-missile", 1), Map.entry("mage-armor", 1), Map.entry("shield", 1),
                    Map.entry("misty-step", 2), Map.entry("fireball", 3))),
            Map.entry("sorcerer", Map.ofEntries(
                    Map.entry("fire-bolt", 0), Map.entry("prestidigitation", 0),
                    Map.entry("magic-missile", 1), Map.entry("shield", 1),
                    Map.entry("misty-step", 2), Map.entry("fireball", 3))),
            Map.entry("warlock", Map.ofEntries(
                    Map.entry("eldritch-blast", 0), Map.entry("prestidigitation", 0),
                    Map.entry("hex", 1), Map.entry("armor-of-agathys", 1),
                    Map.entry("misty-step", 2))),
            Map.entry("bard", Map.ofEntries(
                    Map.entry("vicious-mockery", 0), Map.entry("prestidigitation", 0),
                    Map.entry("healing-word", 1), Map.entry("dissonant-whispers", 1),
                    Map.entry("invisibility", 2))),
            Map.entry("cleric", Map.ofEntries(
                    Map.entry("sacred-flame", 0), Map.entry("guidance", 0),
                    Map.entry("cure-wounds", 1), Map.entry("bless", 1),
                    Map.entry("spiritual-weapon", 2))),
            Map.entry("druid", Map.ofEntries(
                    Map.entry("produce-flame", 0), Map.entry("guidance", 0),
                    Map.entry("entangle", 1), Map.entry("goodberry", 1),
                    Map.entry("flame-blade", 2))),
            Map.entry("paladin", Map.ofEntries(
                    Map.entry("cure-wounds", 1), Map.entry("bless", 1),
                    Map.entry("find-steed", 2))),
            Map.entry("ranger", Map.ofEntries(
                    Map.entry("hunters-mark", 1), Map.entry("cure-wounds", 1),
                    Map.entry("pass-without-trace", 2))));

    private static void handleAddSpell(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object spellIdObj = obj.get("spell_id");
        Object nameObj = obj.get("name");
        Object levelObj = obj.get("level");
        if (!(spellIdObj instanceof String) || ((String) spellIdObj).isEmpty()
                || !(nameObj instanceof String) || ((String) nameObj).isEmpty()
                || !(levelObj instanceof Number) || !isIntegral(levelObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String spellId = (String) spellIdObj;
        String name = (String) nameObj;
        long level = ((Number) levelObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<String, Integer> knownSpells = CLASS_SPELLS.get(member.characterClass);
            Integer canonicalLevel = knownSpells == null ? null : knownSpells.get(spellId);
            if (canonicalLevel == null || canonicalLevel.longValue() != level) {
                sendJson(exchange, 400, mapOf("error", "invalid class/spell combination"));
                return;
            }
            if (member.spellsById.containsKey(spellId)) {
                sendJson(exchange, 409, mapOf("error", "spell already known"));
                return;
            }
            Map<String, Object> spell = new LinkedHashMap<>();
            spell.put("spell_id", spellId);
            spell.put("name", name);
            spell.put("level", level);
            member.spellsById.put(spellId, spell);
            sendJson(exchange, 201, spell);
        }
    }

    private static void handleGetSpells(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("spells", new ArrayList<>(member.spellsById.values()));
            sendJson(exchange, 200, resp);
        }
    }

    /** Number of spell slots of {@code spellLevel} a character of {@code characterLevel} has. Cantrips (level 0) are unlimited. */
    private static int maxSpellSlots(long characterLevel, long spellLevel) {
        if (spellLevel <= 0) {
            return Integer.MAX_VALUE;
        }
        long remaining = characterLevel - spellLevel + 1;
        if (remaining <= 0) {
            return 0;
        }
        return (int) ((remaining + 1) / 2);
    }

    private static void handleCastSpell(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object spellIdObj = obj.get("spell_id");
        Object targetObj = obj.get("target");
        if (!(spellIdObj instanceof String) || ((String) spellIdObj).isEmpty()
                || !(targetObj instanceof String) || ((String) targetObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String spellId = (String) spellIdObj;
        String target = (String) targetObj;

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<String, Integer> knownSpells = CLASS_SPELLS.get(member.characterClass);
            if (knownSpells == null) {
                sendJson(exchange, 400, mapOf("error", "not a spellcasting class"));
                return;
            }
            if (!member.preparedSpellIds.contains(spellId)) {
                sendJson(exchange, 400, mapOf("error", "spell not prepared"));
                return;
            }
            Map<String, Object> spell = member.spellsById.get(spellId);
            long spellLevel = spell == null ? 0 : ((Number) spell.get("level")).longValue();

            int used = member.spellSlotsUsed.getOrDefault(spellLevel, 0);
            int maxSlots = maxSpellSlots(member.level, spellLevel);
            if (spellLevel > 0 && used >= maxSlots) {
                sendJson(exchange, 409, mapOf("error", "no remaining spell slots"));
                return;
            }
            int slotsRemaining;
            if (spellLevel > 0) {
                used += 1;
                member.spellSlotsUsed.put(spellLevel, used);
                slotsRemaining = maxSlots - used;
            } else {
                slotsRemaining = 0;
            }

            Map<String, Object> cast = new LinkedHashMap<>();
            cast.put("character_id", member.characterId);
            cast.put("spell_id", spellId);
            cast.put("target", target);
            cast.put("slot_level", spellLevel);
            cast.put("slots_remaining", slotsRemaining);
            cast.put("sequence", member.casts.size() + 1);
            member.casts.add(cast);
            sendJson(exchange, 201, cast);
        }
    }

    private static void handleGetCasts(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("casts", new ArrayList<>(member.casts));
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> concentrationResponse(PlayMember member) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("character_id", member.characterId);
        resp.put("concentration", member.concentration);
        return resp;
    }

    private static void handlePutConcentration(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object spellIdObj = obj.get("spell_id");
        Object targetObj = obj.get("target");
        Object durationObj = obj.get("duration_turns");
        if (!(spellIdObj instanceof String) || ((String) spellIdObj).isEmpty()
                || !(targetObj instanceof String) || ((String) targetObj).isEmpty()
                || !(durationObj instanceof Number) || !isIntegral(durationObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String spellId = (String) spellIdObj;
        String target = (String) targetObj;
        long duration = ((Number) durationObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<String, Integer> knownSpells = CLASS_SPELLS.get(member.characterClass);
            if (knownSpells == null) {
                sendJson(exchange, 400, mapOf("error", "not a spellcasting class"));
                return;
            }
            if (!member.spellsById.containsKey(spellId)) {
                sendJson(exchange, 400, mapOf("error", "unknown spell"));
                return;
            }
            if (!member.preparedSpellIds.contains(spellId)) {
                sendJson(exchange, 400, mapOf("error", "spell not prepared"));
                return;
            }
            if (duration < 1) {
                sendJson(exchange, 400, mapOf("error", "invalid duration_turns"));
                return;
            }
            Map<String, Object> concentration = new LinkedHashMap<>();
            concentration.put("spell_id", spellId);
            concentration.put("target", target);
            concentration.put("remaining_turns", duration);
            member.concentration = concentration;
            sendJson(exchange, 200, concentrationResponse(member));
        }
    }

    private static void handleGetConcentration(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, concentrationResponse(member));
        }
    }

    private static void handleAdvanceConcentrationTurn(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.concentration != null) {
                long remaining = ((Number) member.concentration.get("remaining_turns")).longValue() - 1;
                if (remaining <= 0) {
                    member.concentration = null;
                } else {
                    member.concentration.put("remaining_turns", remaining);
                }
            }
            sendJson(exchange, 200, concentrationResponse(member));
        }
    }

    private static void handleDeleteConcentration(HttpExchange exchange, String campaignId, String characterId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            member.concentration = null;
            sendJson(exchange, 200, concentrationResponse(member));
        }
    }

    private static final Set<String> VALID_SKILLS = new LinkedHashSet<>(
            List.of("acrobatics", "animal-handling", "arcana", "athletics", "deception", "history",
                    "insight", "intimidation", "investigation", "medicine", "nature", "perception",
                    "performance", "persuasion", "religion", "sleight-of-hand", "stealth", "survival"));

    private static void handleSkillCheck(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object skillObj = obj.get("skill");
        Object abilityObj = obj.get("ability");
        Object proficientObj = obj.get("proficient");
        Object rollObj = obj.get("roll");
        if (!(skillObj instanceof String) || !VALID_SKILLS.contains(skillObj)
                || !(abilityObj instanceof String) || !ABILITY_KEYS.contains(abilityObj)
                || !(proficientObj instanceof Boolean)
                || !(rollObj instanceof Number) || !isIntegral(rollObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String skill = (String) skillObj;
        String ability = (String) abilityObj;
        boolean proficient = (Boolean) proficientObj;
        long roll = ((Number) rollObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Integer abilityModifier = member.abilityModifiers.get(ability);
            if (abilityModifier == null) {
                abilityModifier = 0;
            }
            int modifier = abilityModifier + (proficient ? member.proficiencyBonus : 0);
            long total = roll + modifier;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("skill", skill);
            resp.put("ability", ability);
            resp.put("modifier", modifier);
            resp.put("total", total);
            sendJson(exchange, 200, resp);
        }
    }

    private static final Set<String> VALID_RACES = new LinkedHashSet<>(
            List.of("human", "elf", "dwarf", "halfling", "dragonborn", "gnome", "half-elf", "half-orc", "tiefling"));

    private static final Set<String> VALID_CLASSES = new LinkedHashSet<>(
            List.of("barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger",
                    "rogue", "sorcerer", "warlock", "wizard"));

    private static final Set<String> VALID_BACKGROUNDS = new LinkedHashSet<>(
            List.of("acolyte", "criminal", "folk-hero", "noble", "sage", "soldier", "hermit", "outlander", "entertainer"));

    private static final Map<String, Integer> CLASS_HIT_DIE = Map.ofEntries(
            Map.entry("barbarian", 12),
            Map.entry("bard", 8),
            Map.entry("cleric", 8),
            Map.entry("druid", 8),
            Map.entry("fighter", 10),
            Map.entry("monk", 8),
            Map.entry("paladin", 10),
            Map.entry("ranger", 10),
            Map.entry("rogue", 8),
            Map.entry("sorcerer", 6),
            Map.entry("warlock", 8),
            Map.entry("wizard", 6));

    private static void handleBuildCharacter(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object raceObj = obj.get("race");
        Object classObj = obj.get("class");
        Object backgroundObj = obj.get("background");
        if (!(raceObj instanceof String) || !VALID_RACES.contains(raceObj)
                || !(classObj instanceof String) || !VALID_CLASSES.contains(classObj)
                || !(backgroundObj instanceof String) || !VALID_BACKGROUNDS.contains(backgroundObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        Object abilitiesObj = obj.get("abilities");
        if (!(abilitiesObj instanceof Map)) {
            sendJson(exchange, 400, mapOf("error", "invalid abilities"));
            return;
        }
        Map<?, ?> abilities = (Map<?, ?>) abilitiesObj;
        Map<String, Integer> modifiers = new LinkedHashMap<>();
        for (String key : ABILITY_KEYS) {
            Object scoreObj = abilities.get(key);
            if (!(scoreObj instanceof Number) || !isIntegral(scoreObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid ability " + key));
                return;
            }
            long score = ((Number) scoreObj).longValue();
            if (score < 1 || score > 30) {
                sendJson(exchange, 400, mapOf("error", "ability out of range"));
                return;
            }
            modifiers.put(key, abilityModifier(score));
        }

        String race = (String) raceObj;
        String characterClass = (String) classObj;
        String background = (String) backgroundObj;

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            int conModifier = modifiers.get("con");
            int hitDie = CLASS_HIT_DIE.getOrDefault(characterClass, 8);
            long hpMax = hitDie + conModifier;
            int proficiencyBonus = proficiencyBonus(member.level);

            member.race = race;
            member.characterClass = characterClass;
            member.background = background;
            member.hpMax = hpMax;
            member.hpCurrent = hpMax;
            member.proficiencyBonus = proficiencyBonus;
            member.conModifier = conModifier;
            member.abilityModifiers.clear();
            member.abilityModifiers.putAll(modifiers);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("race", member.race);
            resp.put("class", member.characterClass);
            resp.put("background", member.background);
            resp.put("level", member.level);
            resp.put("hp_max", member.hpMax);
            resp.put("proficiency_bonus", member.proficiencyBonus);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleLevelUpCharacter(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object levelObj = obj.get("level");
        if (!(levelObj instanceof Number) || !isIntegral(levelObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long newLevel = ((Number) levelObj).longValue();

        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (newLevel != member.level + 1) {
                sendJson(exchange, 400, mapOf("error", "invalid level"));
                return;
            }

            int hitDie = CLASS_HIT_DIE.getOrDefault(member.characterClass, 8);
            long hpGain = Math.max(1, (hitDie / 2 + 1) + member.conModifier);
            member.level = newLevel;
            member.hpMax = member.hpMax + hpGain;
            member.hpCurrent = member.hpCurrent + hpGain;
            member.proficiencyBonus = proficiencyBonus(member.level);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("level", member.level);
            resp.put("hp_max", member.hpMax);
            resp.put("hit_dice", "1d" + hitDie);
            resp.put("proficiency_bonus", member.proficiencyBonus);
            sendJson(exchange, 200, resp);
        }
    }

    private static PlayMember findMemberByCharacterId(PlayCampaign campaign, String characterId) {
        for (PlayMember member : campaign.membersByUsername.values()) {
            if (member.characterId.equals(characterId)) {
                return member;
            }
        }
        return null;
    }

    private static void handleCharacterDamage(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object amountObj = obj.get("amount");
        if (!(amountObj instanceof Number) || !isIntegral(amountObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long amount = ((Number) amountObj).longValue();
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            long hpBefore = member.hpCurrent;
            long hpAfter = Math.max(0, hpBefore - amount);
            member.hpCurrent = hpAfter;
            if (hpAfter == 0 && "alive".equals(member.status)) {
                member.status = "unconscious";
                member.deathSaveSuccesses = 0;
                member.deathSaveFailures = 0;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("target", member.characterId);
            resp.put("hp_before", hpBefore);
            resp.put("hp_after", hpAfter);
            resp.put("damage", amount);
            resp.put("status", member.status);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleDeathSave(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object outcomeObj = obj.get("outcome");
        if (!(outcomeObj instanceof String)
                || (!"success".equals(outcomeObj) && !"failure".equals(outcomeObj))) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String outcome = (String) outcomeObj;
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!user.username.equals(member.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (!"unconscious".equals(member.status)) {
                sendJson(exchange, 409, mapOf("error", "character is not making death saves"));
                return;
            }
            if ("success".equals(outcome)) {
                member.deathSaveSuccesses++;
                if (member.deathSaveSuccesses >= 3) {
                    member.status = "stable";
                }
            } else {
                member.deathSaveFailures++;
                if (member.deathSaveFailures >= 3) {
                    member.status = "dead";
                }
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("successes", member.deathSaveSuccesses);
            resp.put("failures", member.deathSaveFailures);
            resp.put("status", member.status);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetCharacterStatus(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("hp_current", member.hpCurrent);
            resp.put("hp_max", member.hpMax);
            resp.put("status", member.status);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetCharacterOwner(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("owner", member.owner);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleClaimCharacter(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner != null) {
                sendJson(exchange, 409, mapOf("error", "character already owned"));
                return;
            }
            member.owner = user.username;
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("owner", member.owner);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleTransferCharacter(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object newOwnerObj = obj.get("new_owner");
        if (!(newOwnerObj instanceof String) || ((String) newOwnerObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid new_owner"));
            return;
        }
        String newOwner = (String) newOwnerObj;
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (member.owner == null || !member.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            boolean newOwnerIsMember = newOwner.equals(campaign.owner) || campaign.membersByUsername.containsKey(newOwner);
            if (!newOwnerIsMember) {
                sendJson(exchange, 400, mapOf("error", "new owner must be a campaign member"));
                return;
            }
            member.owner = newOwner;
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("owner", member.owner);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreateScene(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object idObj = obj.get("id");
        Object nameObj = obj.get("name");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty() || !(nameObj instanceof String)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String id = (String) idObj;
        String name = (String) nameObj;
        synchronized (campaign) {
            if (campaign.scenesById.containsKey(id)) {
                sendJson(exchange, 409, mapOf("error", "scene already exists"));
                return;
            }
            Scene scene = new Scene();
            scene.id = id;
            scene.name = name;
            scene.status = "open";
            campaign.scenesById.put(id, scene);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", scene.id);
            resp.put("name", scene.name);
            resp.put("status", scene.status);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleCreateEncounter(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object idObj = obj.get("id");
        Object nameObj = obj.get("name");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty() || !(nameObj instanceof String)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String id = (String) idObj;
        String name = (String) nameObj;
        synchronized (campaign) {
            if (campaign.activeEncounterId != null) {
                sendJson(exchange, 409, mapOf("error", "campaign already in combat"));
                return;
            }
            if (campaign.encountersById.containsKey(id)) {
                sendJson(exchange, 409, mapOf("error", "encounter already exists"));
                return;
            }
            Encounter encounter = new Encounter();
            encounter.id = id;
            encounter.name = name;
            encounter.status = "active";
            campaign.encountersById.put(id, encounter);
            campaign.activeEncounterId = id;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", encounter.id);
            resp.put("name", encounter.name);
            resp.put("status", encounter.status);
            resp.put("combatants", encounter.combatants);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleAddMonster(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object monsterIdObj = obj.get("monster_id");
        Object nameObj = obj.get("name");
        Object hpMaxObj = obj.get("hp_max");
        Object initiativeObj = obj.get("initiative");
        if (!(monsterIdObj instanceof String) || ((String) monsterIdObj).isEmpty()
                || !(nameObj instanceof String)
                || !(hpMaxObj instanceof Number) || !isIntegral(hpMaxObj)
                || !(initiativeObj instanceof Number) || !isIntegral(initiativeObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String monsterId = (String) monsterIdObj;
        String name = (String) nameObj;
        long hpMax = ((Number) hpMaxObj).longValue();
        long initiative = ((Number) initiativeObj).longValue();
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            if (encounter.monstersById.containsKey(monsterId)) {
                sendJson(exchange, 409, mapOf("error", "monster already exists"));
                return;
            }
            Monster monster = new Monster();
            monster.monsterId = monsterId;
            monster.name = name;
            monster.hpMax = hpMax;
            monster.initiative = initiative;
            monster.hpCurrent = hpMax;
            encounter.monstersById.put(monsterId, monster);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("monster_id", monster.monsterId);
            resp.put("name", monster.name);
            resp.put("hp_max", monster.hpMax);
            resp.put("initiative", monster.initiative);
            resp.put("hp_current", monster.hpCurrent);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleRemoveMonster(HttpExchange exchange, String campaignId, String encounterId, String monsterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            Monster removed = encounter.monstersById.remove(monsterId);
            if (removed == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, mapOf("removed", monsterId));
        }
    }

    private static void handleBindCombatant(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object memberObj = obj.get("member");
        Object initiativeObj = obj.get("initiative");
        if (!(memberObj instanceof String) || ((String) memberObj).isEmpty()
                || !(initiativeObj instanceof Number) || !isIntegral(initiativeObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String memberName = (String) memberObj;
        long initiative = ((Number) initiativeObj).longValue();
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            PlayMember member = campaign.membersByUsername.get(memberName);
            if (member == null) {
                sendJson(exchange, 400, mapOf("error", "invalid member"));
                return;
            }
            if (encounter.combatantsByMember.containsKey(memberName)) {
                sendJson(exchange, 409, mapOf("error", "combatant already exists"));
                return;
            }
            PlayCombatant combatant = new PlayCombatant();
            combatant.member = memberName;
            combatant.characterId = member.characterId;
            combatant.name = member.name;
            combatant.initiative = initiative;
            encounter.combatantsByMember.put(memberName, combatant);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("member", combatant.member);
            resp.put("character_id", combatant.characterId);
            resp.put("name", combatant.name);
            resp.put("initiative", combatant.initiative);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleUnbindCombatant(HttpExchange exchange, String campaignId, String encounterId, String member) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            PlayCombatant removed = encounter.combatantsByMember.remove(member);
            if (removed == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, mapOf("removed", member));
        }
    }

    /**
     * Deterministic initiative order for an encounter: descending
     * initiative, ties broken by name ascending (matches
     * {@link #handleInitiativeOrder}'s tie-break rule).
     */
    private static List<TurnEntry> buildTurnOrder(Encounter encounter) {
        List<TurnEntry> order = new ArrayList<>();
        for (Monster monster : encounter.monstersById.values()) {
            TurnEntry entry = new TurnEntry();
            entry.name = monster.name;
            entry.kind = "monster";
            entry.initiative = monster.initiative;
            entry.target = monster.monsterId;
            order.add(entry);
        }
        for (PlayCombatant combatant : encounter.combatantsByMember.values()) {
            TurnEntry entry = new TurnEntry();
            entry.name = combatant.name;
            entry.kind = "player";
            entry.initiative = combatant.initiative;
            entry.member = combatant.member;
            entry.target = combatant.member;
            order.add(entry);
        }
        order.sort((a, b) -> {
            if (a.initiative != b.initiative) {
                return Long.compare(b.initiative, a.initiative);
            }
            return a.name.compareTo(b.name);
        });
        if (encounter.turnOrderOverride == null) {
            return order;
        }
        Map<String, TurnEntry> byTarget = new LinkedHashMap<>();
        for (TurnEntry entry : order) {
            byTarget.put(entry.target, entry);
        }
        List<TurnEntry> reordered = new ArrayList<>();
        for (String target : encounter.turnOrderOverride) {
            TurnEntry entry = byTarget.remove(target);
            if (entry != null) {
                reordered.add(entry);
            }
        }
        reordered.addAll(byTarget.values());
        return reordered;
    }

    private static Map<String, Object> turnEntryJson(TurnEntry entry) {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("name", entry.name);
        json.put("kind", entry.kind);
        json.put("initiative", entry.initiative);
        return json;
    }

    private static void handleGetEncounterTurn(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            if (order.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "no combatants"));
                return;
            }
            int index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("round", encounter.round);
            resp.put("turn_index", index);
            resp.put("active", turnEntryJson(order.get(index)));
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleAdvanceEncounterTurn(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            if (order.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "no combatants"));
                return;
            }
            int index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
            TurnEntry active = order.get(index);
            boolean isOwner = user.username.equals(campaign.owner);
            boolean isCurrentCombatant = "player".equals(active.kind) && user.username.equals(active.member);
            if (!isOwner && !isCurrentCombatant) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }
            int nextIndex = index + 1;
            int round = encounter.round;
            if (nextIndex >= order.size()) {
                nextIndex = 0;
                round += 1;
            }
            encounter.turnIndex = nextIndex;
            encounter.round = round;

            TurnEntry nextActive = order.get(nextIndex);
            decrementConditions(encounter, nextActive.target);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("round", encounter.round);
            resp.put("turn_index", encounter.turnIndex);
            resp.put("active", turnEntryJson(order.get(nextIndex)));
            sendJson(exchange, 200, resp);
        }
    }

    /**
     * Delays the current combatant to a later slot in the initiative order without advancing
     * the round or granting anyone an extra turn: the combatant is spliced out of its current
     * slot and reinserted at {@code position}, so whoever now occupies the vacated slot becomes
     * current.
     */
    private static void handleDelayEncounterTurn(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            if (order.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "no combatants"));
                return;
            }
            int index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
            TurnEntry active = order.get(index);
            boolean isOwner = user.username.equals(campaign.owner);
            boolean isCurrentCombatant = "player".equals(active.kind) && user.username.equals(active.member);
            if (!isOwner && !isCurrentCombatant) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object positionObj = obj.get("new_index");
            if (positionObj == null) {
                positionObj = obj.get("position");
            }
            if (!(positionObj instanceof Number) || !isIntegral(positionObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid position"));
                return;
            }
            int position = ((Number) positionObj).intValue();
            if (position <= index || position >= order.size()) {
                sendJson(exchange, 400, mapOf("error", "illegal index"));
                return;
            }

            List<TurnEntry> reordered = new ArrayList<>(order);
            reordered.remove(index);
            reordered.add(position, active);

            List<String> override = new ArrayList<>();
            for (TurnEntry entry : reordered) {
                override.add(entry.target);
            }
            encounter.turnOrderOverride = override;
            // Delaying does not end the combatant's turn; it stays theirs at the new slot
            // until an explicit advance, so the turn pointer follows them to `position`.
            encounter.turnIndex = position;

            List<Object> orderJson = new ArrayList<>();
            for (TurnEntry entry : reordered) {
                orderJson.add(turnEntryJson(entry));
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("round", encounter.round);
            resp.put("turn_index", encounter.turnIndex);
            resp.put("order", orderJson);
            sendJson(exchange, 200, resp);
        }
    }

    /** Records a ready action for the current combatant. Does not change the turn order. */
    private static void handleReadyEncounterTurn(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            if (order.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "no combatants"));
                return;
            }
            int index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
            TurnEntry active = order.get(index);
            boolean isCurrentCombatant = "player".equals(active.kind) && user.username.equals(active.member);
            if (!isCurrentCombatant) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object triggerObj = obj.get("trigger");
            if (!(triggerObj instanceof String) || ((String) triggerObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid trigger"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("actor", user.username);
            resp.put("trigger", triggerObj);
            sendJson(exchange, 201, resp);
        }
    }

    /** Decrements remaining_rounds for {@code target}'s conditions, dropping any that hit 0. */
    private static void decrementConditions(Encounter encounter, String target) {
        if (target == null) {
            return;
        }
        List<Condition> conditions = encounter.conditionsByTarget.get(target);
        if (conditions == null || conditions.isEmpty()) {
            return;
        }
        List<Condition> remaining = new ArrayList<>();
        for (Condition cond : conditions) {
            cond.remainingRounds -= 1;
            if (cond.remainingRounds > 0) {
                remaining.add(cond);
            }
        }
        encounter.conditionsByTarget.put(target, remaining);
    }

    private static String resolveEncounterTargetKey(Encounter encounter, String target) {
        if (encounter.monstersById.containsKey(target)) {
            return target;
        }
        if (encounter.combatantsByMember.containsKey(target)) {
            return target;
        }
        for (PlayCombatant c : encounter.combatantsByMember.values()) {
            if (c.name.equals(target)) {
                return c.member;
            }
        }
        return null;
    }

    private static List<Object> conditionListJson(List<Condition> conditions) {
        List<Object> list = new ArrayList<>();
        for (Condition cond : conditions) {
            Map<String, Object> cm = new LinkedHashMap<>();
            cm.put("condition", cond.condition);
            cm.put("remaining_rounds", cond.remainingRounds);
            list.add(cm);
        }
        return list;
    }

    private static void handleAddEncounterCondition(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object targetObj = obj.get("target");
        Object conditionObj = obj.get("condition");
        Object durationObj = obj.get("duration_rounds");
        if (!(targetObj instanceof String) || ((String) targetObj).isEmpty()
                || !(conditionObj instanceof String) || ((String) conditionObj).isEmpty()
                || !(durationObj instanceof Number) || !isIntegral(durationObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        long duration = ((Number) durationObj).longValue();
        if (duration <= 0) {
            sendJson(exchange, 400, mapOf("error", "duration_rounds must be positive"));
            return;
        }
        String target = (String) targetObj;
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            String key = resolveEncounterTargetKey(encounter, target);
            if (key == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            List<Condition> conditions = encounter.conditionsByTarget.computeIfAbsent(key, k -> new ArrayList<>());
            conditions.add(new Condition((String) conditionObj, duration));

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("target", target);
            resp.put("conditions", conditionListJson(conditions));
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetEncounterStatus(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            List<Object> orderJson = new ArrayList<>();
            for (TurnEntry entry : order) {
                orderJson.add(turnEntryJson(entry));
            }
            int index = 0;
            Object activeJson = null;
            if (!order.isEmpty()) {
                index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
                activeJson = turnEntryJson(order.get(index));
            }
            Map<String, Object> conditionsMap = new LinkedHashMap<>();
            for (Map.Entry<String, List<Condition>> e : encounter.conditionsByTarget.entrySet()) {
                if (e.getValue().isEmpty()) {
                    continue;
                }
                conditionsMap.put(e.getKey(), conditionListJson(e.getValue()));
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("round", encounter.round);
            resp.put("turn_index", index);
            resp.put("active", activeJson);
            resp.put("order", orderJson);
            resp.put("conditions", conditionsMap);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleAwardEncounterRewards(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object xpObj = obj.get("xp");
        Object lootObj = obj.get("loot");
        if (!(xpObj instanceof Number) || !isIntegral(xpObj) || !(lootObj instanceof List)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        List<?> lootList = (List<?>) lootObj;
        List<Map<String, Object>> loot = new ArrayList<>();
        for (Object entry : lootList) {
            if (!(entry instanceof Map)) {
                sendJson(exchange, 400, mapOf("error", "invalid loot entry"));
                return;
            }
            Map<?, ?> entryMap = (Map<?, ?>) entry;
            Object slugObj = entryMap.get("slug");
            Object quantityObj = entryMap.get("quantity");
            if (!(slugObj instanceof String) || ((String) slugObj).isEmpty()
                    || !(quantityObj instanceof Number) || !isIntegral(quantityObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid loot entry"));
                return;
            }
            Map<String, Object> lootEntry = new LinkedHashMap<>();
            lootEntry.put("slug", (String) slugObj);
            lootEntry.put("quantity", ((Number) quantityObj).longValue());
            loot.add(lootEntry);
        }
        long xp = ((Number) xpObj).longValue();
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            if (encounter.rewardsAwarded) {
                sendJson(exchange, 409, mapOf("error", "rewards already awarded"));
                return;
            }
            encounter.rewardsAwarded = true;
            encounter.xpAwarded = xp;
            encounter.loot = loot;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", encounter.id);
            resp.put("xp", xp);
            resp.put("loot", loot);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCloseEncounter(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            encounter.status = "closed";
            if (encounterId.equals(campaign.activeEncounterId)) {
                campaign.activeEncounterId = null;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", encounter.id);
            resp.put("status", encounter.status);
            resp.put("xp_awarded", encounter.xpAwarded);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleEndEncounter(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            if (encounter.ended) {
                sendJson(exchange, 409, mapOf("error", "campaign not in combat"));
                return;
            }
            if ("active".equals(encounter.status)) {
                encounter.status = "closed";
            }
            if (encounterId.equals(campaign.activeEncounterId)) {
                campaign.activeEncounterId = null;
            }
            encounter.ended = true;
            campaign.phase = "exploration";
            campaign.currentActor = "dm";
            if (campaign.turnQueue != null && !campaign.turnQueue.isEmpty()) {
                campaign.turnIndex = campaign.turnQueue.size() - 1;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("status", campaign.status);
            resp.put("phase", campaign.phase);
            resp.put("current_actor", campaign.currentActor);
            sendJson(exchange, 200, resp);
        }
    }

    private static final Set<String> COMBAT_ACTION_TYPES = new LinkedHashSet<>();
    static {
        COMBAT_ACTION_TYPES.add("attack");
        COMBAT_ACTION_TYPES.add("help");
        COMBAT_ACTION_TYPES.add("dodge");
        COMBAT_ACTION_TYPES.add("ready");
    }

    private static void handleAddCombatAction(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            List<TurnEntry> order = buildTurnOrder(encounter);
            if (order.isEmpty()) {
                sendJson(exchange, 404, mapOf("error", "no combatants"));
                return;
            }
            int index = ((encounter.turnIndex % order.size()) + order.size()) % order.size();
            TurnEntry active = order.get(index);
            boolean isCurrentCombatant = "player".equals(active.kind) && user.username.equals(active.member);
            if (!isCurrentCombatant) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            try {
                Map<?, ?> obj = parseJsonObject(exchange);
                if (obj == null) {
                    return;
                }
                Object typeObj = obj.get("type");
                if (!(typeObj instanceof String) || !COMBAT_ACTION_TYPES.contains(typeObj)) {
                    sendJson(exchange, 400, mapOf("error", "invalid type"));
                    return;
                }
                Object textObj = obj.get("text");
                if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid text"));
                    return;
                }
                Object targetObj = obj.get("target");
                if (targetObj != null && !(targetObj instanceof String)) {
                    sendJson(exchange, 400, mapOf("error", "invalid target"));
                    return;
                }

                int sequence = campaign.narrationEvents.size() + 1;
                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "combat_action");
                event.put("actor", user.username);
                event.put("type", typeObj);
                event.put("target", targetObj);
                event.put("text", textObj);
                campaign.narrationEvents.add(event);

                sendJson(exchange, 201, event);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
            }
        }
    }

    /** Result of resolving a damage/heal target within an encounter. */
    private static final class HpTarget {
        long hpMax;
        long hpCurrent;
        java.util.function.LongConsumer setter;
    }

    private static HpTarget resolveHpTarget(PlayCampaign campaign, Encounter encounter, String target) {
        Monster monster = encounter.monstersById.get(target);
        if (monster != null) {
            HpTarget t = new HpTarget();
            t.hpMax = monster.hpMax;
            t.hpCurrent = monster.hpCurrent;
            Monster finalMonster = monster;
            t.setter = value -> finalMonster.hpCurrent = value;
            return t;
        }
        PlayCombatant combatant = encounter.combatantsByMember.get(target);
        if (combatant == null) {
            for (PlayCombatant c : encounter.combatantsByMember.values()) {
                if (c.name.equals(target)) {
                    combatant = c;
                    break;
                }
            }
        }
        if (combatant != null) {
            PlayMember member = campaign.membersByUsername.get(combatant.member);
            if (member != null) {
                HpTarget t = new HpTarget();
                t.hpMax = member.hpMax;
                t.hpCurrent = member.hpCurrent;
                PlayMember finalMember = member;
                t.setter = value -> finalMember.hpCurrent = value;
                return t;
            }
        }
        return null;
    }

    private static void handleEncounterDamage(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object targetObj = obj.get("target");
        Object amountObj = obj.get("amount");
        if (!(targetObj instanceof String) || ((String) targetObj).isEmpty()
                || !(amountObj instanceof Number) || !isIntegral(amountObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String target = (String) targetObj;
        long amount = ((Number) amountObj).longValue();
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            HpTarget hpTarget = resolveHpTarget(campaign, encounter, target);
            if (hpTarget == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            long hpBefore = hpTarget.hpCurrent;
            long hpAfter = Math.max(0, hpBefore - amount);
            hpTarget.setter.accept(hpAfter);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("target", target);
            resp.put("hp_before", hpBefore);
            resp.put("hp_after", hpAfter);
            resp.put("damage", amount);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleEncounterHeal(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object targetObj = obj.get("target");
        Object amountObj = obj.get("amount");
        if (!(targetObj instanceof String) || ((String) targetObj).isEmpty()
                || !(amountObj instanceof Number) || !isIntegral(amountObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String target = (String) targetObj;
        long amount = ((Number) amountObj).longValue();
        synchronized (campaign) {
            Encounter encounter = requireEncounter(exchange, campaign, encounterId);
            if (encounter == null) {
                return;
            }
            HpTarget hpTarget = resolveHpTarget(campaign, encounter, target);
            if (hpTarget == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            long hpBefore = hpTarget.hpCurrent;
            long hpAfter = Math.min(hpTarget.hpMax, hpBefore + amount);
            hpTarget.setter.accept(hpAfter);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("target", target);
            resp.put("hp_before", hpBefore);
            resp.put("hp_after", hpAfter);
            resp.put("healing", amount);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleEnterScene(HttpExchange exchange, String campaignId, String sceneId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Scene scene = campaign.scenesById.get(sceneId);
            if (scene == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if ("closed".equals(scene.status)) {
                sendJson(exchange, 409, mapOf("error", "scene is closed"));
                return;
            }
            campaign.currentSceneId = scene.id;

            int sequence = campaign.narrationEvents.size() + 1;
            Map<String, Object> event = new LinkedHashMap<>();
            event.put("sequence", sequence);
            event.put("kind", "scene");
            event.put("actor", user.username);
            event.put("text", scene.id);
            campaign.narrationEvents.add(event);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("current_scene_id", scene.id);
            resp.put("name", scene.name);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCloseScene(HttpExchange exchange, String campaignId, String sceneId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Scene scene = campaign.scenesById.get(sceneId);
            if (scene == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            scene.status = "closed";
            if (sceneId.equals(campaign.currentSceneId)) {
                campaign.currentSceneId = null;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", scene.id);
            resp.put("status", scene.status);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetCurrentScene(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            Scene scene = campaign.currentSceneId == null ? null : campaign.scenesById.get(campaign.currentSceneId);
            if (scene == null || !"open".equals(scene.status)) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", scene.id);
            resp.put("name", scene.name);
            resp.put("status", scene.status);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreateLocation(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object idObj = obj.get("id");
        Object nameObj = obj.get("name");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty() || !(nameObj instanceof String)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String id = (String) idObj;
        String name = (String) nameObj;
        synchronized (campaign) {
            if (campaign.locationsById.containsKey(id)) {
                sendJson(exchange, 409, mapOf("error", "location already exists"));
                return;
            }
            Location location = new Location();
            location.id = id;
            location.name = name;
            campaign.locationsById.put(id, location);
            if (campaign.currentLocationId == null) {
                campaign.currentLocationId = location.id;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", location.id);
            resp.put("name", location.name);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleCreateConnection(HttpExchange exchange, String campaignId, String fromId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object toIdObj = obj.get("to_id");
        Object travelTurnsObj = obj.get("travel_turns");
        if (!(toIdObj instanceof String) || ((String) toIdObj).isEmpty()
                || !(travelTurnsObj instanceof Number) || !isIntegral(travelTurnsObj)) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
            return;
        }
        String toId = (String) toIdObj;
        long travelTurns = ((Number) travelTurnsObj).longValue();
        synchronized (campaign) {
            Location from = campaign.locationsById.get(fromId);
            if (from == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!campaign.locationsById.containsKey(toId)) {
                sendJson(exchange, 400, mapOf("error", "destination location does not exist"));
                return;
            }
            for (Connection existing : from.connections) {
                if (existing.toId.equals(toId)) {
                    sendJson(exchange, 400, mapOf("error", "already connected"));
                    return;
                }
            }
            Connection connection = new Connection();
            connection.toId = toId;
            connection.travelTurns = travelTurns;
            from.connections.add(connection);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("from_id", fromId);
            resp.put("to_id", toId);
            resp.put("travel_turns", travelTurns);
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetTravel(HttpExchange exchange, String campaignId, String locId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            Location location = campaign.locationsById.get(locId);
            if (location == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            List<Map<String, Object>> destinations = new ArrayList<>();
            for (Connection connection : location.connections) {
                Location dest = campaign.locationsById.get(connection.toId);
                if (dest == null) {
                    continue;
                }
                Map<String, Object> destMap = new LinkedHashMap<>();
                destMap.put("id", dest.id);
                destMap.put("name", dest.name);
                destMap.put("travel_turns", connection.travelTurns);
                destinations.add(destMap);
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("destinations", destinations);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetOnboarding(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            boolean isOwner = user.username.equals(campaign.owner);
            Map<String, Object> resp = new LinkedHashMap<>();
            if (isOwner) {
                resp.put("role", "dm");
                resp.put("next_steps", List.of("configure-safety", "invite-players", "start-campaign"));
            } else {
                resp.put("role", "player");
                resp.put("next_steps", List.of("review-party", "take-turn", "submit-action"));
            }
            resp.put("can_mutate", true);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetCampaignDocument(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            boolean isOwner = user.username.equals(campaign.owner);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("story", campaign.story);
            if (isOwner) {
                resp.put("dm_notes", campaign.dmNotes);
            }
            sendJson(exchange, 200, resp);
        }
    }

    private static void handlePutCampaignDocument(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object story = obj.get("story");
        Object dmNotes = obj.get("dm_notes");
        synchronized (campaign) {
            if (story instanceof String) {
                campaign.story = (String) story;
            }
            if (dmNotes instanceof String) {
                campaign.dmNotes = (String) dmNotes;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("story", campaign.story);
            resp.put("dm_notes", campaign.dmNotes);
            sendJson(exchange, 200, resp);
        }
    }

    private static Map<String, Object> backupJson(Backup backup) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("backup_id", backup.backupId);
        resp.put("story", backup.story);
        resp.put("status", backup.status);
        return resp;
    }

    private static void handleCreateBackup(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Backup backup = new Backup();
            backup.backupId = "backup-" + campaign.nextBackupSequence;
            campaign.nextBackupSequence++;
            backup.story = campaign.story;
            backup.status = campaign.status;
            campaign.backupsById.put(backup.backupId, backup);
            campaign.backupsInOrder.add(backup);
            sendJson(exchange, 201, backupJson(backup));
        }
    }

    private static void handleListBackups(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> backups = new ArrayList<>();
            for (Backup backup : campaign.backupsInOrder) {
                backups.add(backupJson(backup));
            }
            sendJson(exchange, 200, mapOf("backups", backups));
        }
    }

    private static void handleRestoreBackup(HttpExchange exchange, String campaignId, String backupId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Backup backup = campaign.backupsById.get(backupId);
            if (backup == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            campaign.story = backup.story;
            campaign.status = backup.status;
            sendJson(exchange, 200, backupJson(backup));
        }
    }

    /**
     * Validates a consent payload, returning trimmed, duplicate-free values
     * in request order, or null if the payload is not a nonempty array of
     * nonempty strings with unique values.
     */
    private static List<String> validateSessionZeroConsent(Object consentObj) {
        if (!(consentObj instanceof List)) {
            return null;
        }
        List<?> raw = (List<?>) consentObj;
        if (raw.isEmpty()) {
            return null;
        }
        List<String> normalized = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object item : raw) {
            if (!(item instanceof String)) {
                return null;
            }
            String value = (String) item;
            if (value.isEmpty() || !seen.add(value)) {
                return null;
            }
            normalized.add(value);
        }
        return normalized;
    }

    private static Map<String, Object> sessionZeroToMap(Map<String, Object> sessionZero) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("rules", sessionZero.get("rules"));
        resp.put("tone", sessionZero.get("tone"));
        resp.put("consent", sessionZero.get("consent"));
        return resp;
    }

    private static void handleGetSessionZero(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            if (campaign.sessionZero == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            sendJson(exchange, 200, sessionZeroToMap(campaign.sessionZero));
        }
    }

    private static void handlePutSessionZero(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object rulesObj = obj.get("rules");
        Object toneObj = obj.get("tone");
        Object consentObj = obj.get("consent");
        if (!(rulesObj instanceof String) || ((String) rulesObj).isEmpty()
                || !(toneObj instanceof String) || ((String) toneObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        List<String> consent = validateSessionZeroConsent(consentObj);
        if (consent == null) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        synchronized (campaign) {
            if (!"lobby".equals(campaign.status)) {
                sendJson(exchange, 409, mapOf("error", "campaign already started"));
                return;
            }
            Map<String, Object> sessionZero = new LinkedHashMap<>();
            sessionZero.put("rules", rulesObj);
            sessionZero.put("tone", toneObj);
            sessionZero.put("consent", consent);
            campaign.sessionZero = sessionZero;
            sendJson(exchange, 200, sessionZeroToMap(sessionZero));
        }
    }

    /**
     * Validates a tags payload, returning trimmed values in request order, or
     * null if it is not an array of unique nonempty strings. When
     * {@code requireNonEmpty} is true, an empty array is also rejected.
     */
    private static List<String> validateTags(Object tagsObj, boolean requireNonEmpty) {
        if (!(tagsObj instanceof List)) {
            return null;
        }
        List<?> raw = (List<?>) tagsObj;
        if (requireNonEmpty && raw.isEmpty()) {
            return null;
        }
        List<String> normalized = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object item : raw) {
            if (!(item instanceof String)) {
                return null;
            }
            String value = (String) item;
            if (value.isEmpty() || !seen.add(value)) {
                return null;
            }
            normalized.add(value);
        }
        return normalized;
    }

    private static Map<String, Object> contentToMap(ContentRecord content) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("content_id", content.contentId);
        map.put("kind", content.kind);
        map.put("text", content.text);
        map.put("tags", content.tags);
        return map;
    }

    private static void handleCreateContent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object contentIdObj = obj.get("content_id");
        Object kindObj = obj.get("kind");
        Object textObj = obj.get("text");
        Object tagsObj = obj.get("tags");
        if (!(contentIdObj instanceof String) || ((String) contentIdObj).isEmpty()
                || !(kindObj instanceof String) || ((String) kindObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        List<String> tags = validateTags(tagsObj, true);
        if (tags == null) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String contentId = (String) contentIdObj;
        synchronized (campaign) {
            if (campaign.contentById.containsKey(contentId)) {
                sendJson(exchange, 409, mapOf("error", "content already exists"));
                return;
            }
            ContentRecord content = new ContentRecord();
            content.contentId = contentId;
            content.kind = (String) kindObj;
            content.text = (String) textObj;
            content.tags = tags;
            campaign.contentById.put(contentId, content);
            sendJson(exchange, 201, contentToMap(content));
        }
    }

    private static void handlePutContentTags(HttpExchange exchange, String campaignId, String contentId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        List<String> tags = validateTags(obj.get("tags"), false);
        if (tags == null) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        synchronized (campaign) {
            ContentRecord content = campaign.contentById.get(contentId);
            if (content == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            content.tags = tags;
            sendJson(exchange, 200, contentToMap(content));
        }
    }

    private static void handleGetContentList(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        String excludeTag = null;
        String rawQuery = exchange.getRequestURI().getRawQuery();
        if (rawQuery != null) {
            for (String param : rawQuery.split("&")) {
                if (param.isEmpty()) {
                    continue;
                }
                int eq = param.indexOf('=');
                String key = eq < 0 ? param : param.substring(0, eq);
                String value = eq < 0 ? "" : param.substring(eq + 1);
                if ("exclude_tag".equals(key)) {
                    try {
                        excludeTag = URLDecoder.decode(value, "UTF-8");
                    } catch (IOException e) {
                        excludeTag = value;
                    }
                }
            }
            if (excludeTag != null && excludeTag.isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid exclude_tag"));
                return;
            }
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            List<Map<String, Object>> results = new ArrayList<>();
            for (ContentRecord content : campaign.contentById.values()) {
                if (!isDm && excludeTag != null && content.tags.contains(excludeTag)) {
                    continue;
                }
                results.add(contentToMap(content));
            }
            sendJson(exchange, 200, mapOf("content", results));
        }
    }

    private static Map<String, Object> noteToMap(Note note) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("note_id", note.noteId);
        resp.put("text", note.text);
        resp.put("visibility", note.visibility);
        resp.put("owner", note.owner);
        return resp;
    }

    private static boolean noteVisibleTo(Note note, PlayCampaign campaign, User user) {
        if (user.username.equals(campaign.owner)) {
            return true;
        }
        if ("party".equals(note.visibility)) {
            return true;
        }
        return note.owner.equals(user.username);
    }

    private static void handleCreateNote(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object noteIdObj = obj.get("note_id");
        Object textObj = obj.get("text");
        Object visibilityObj = obj.get("visibility");
        if (!(noteIdObj instanceof String) || ((String) noteIdObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()
                || !(visibilityObj instanceof String)
                || !("private".equals(visibilityObj) || "party".equals(visibilityObj))) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String noteId = (String) noteIdObj;
        synchronized (campaign) {
            if (campaign.notesById.containsKey(noteId)) {
                sendJson(exchange, 409, mapOf("error", "note already exists"));
                return;
            }
            Note note = new Note();
            note.noteId = noteId;
            note.text = (String) textObj;
            note.visibility = (String) visibilityObj;
            note.owner = user.username;
            campaign.notesById.put(noteId, note);
            sendJson(exchange, 201, noteToMap(note));
        }
    }

    private static void handleListNotes(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> results = new ArrayList<>();
            for (Note note : campaign.notesById.values()) {
                if (noteVisibleTo(note, campaign, user)) {
                    results.add(noteToMap(note));
                }
            }
            sendJson(exchange, 200, mapOf("notes", results));
        }
    }

    private static void handleGetNote(HttpExchange exchange, String campaignId, String noteId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Note note = campaign.notesById.get(noteId);
            if (note == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!noteVisibleTo(note, campaign, user)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            sendJson(exchange, 200, noteToMap(note));
        }
    }

    private static void handleUpdateNote(HttpExchange exchange, String campaignId, String noteId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object textObj = obj.get("text");
        Object visibilityObj = obj.get("visibility");
        if (!(textObj instanceof String) || ((String) textObj).isEmpty()
                || !(visibilityObj instanceof String)
                || !("private".equals(visibilityObj) || "party".equals(visibilityObj))) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        synchronized (campaign) {
            Note note = campaign.notesById.get(noteId);
            if (note == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!note.owner.equals(user.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            note.text = (String) textObj;
            note.visibility = (String) visibilityObj;
            sendJson(exchange, 200, noteToMap(note));
        }
    }

    private static Map<String, Object> whisperToMap(Whisper whisper) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("whisper_id", whisper.whisperId);
        resp.put("from_character_id", whisper.fromCharacterId);
        resp.put("to_character_id", whisper.toCharacterId);
        resp.put("text", whisper.text);
        return resp;
    }

    private static void handleCreateWhisper(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object whisperIdObj = obj.get("whisper_id");
        Object toCharacterIdObj = obj.get("to_character_id");
        Object textObj = obj.get("text");
        if (!(whisperIdObj instanceof String) || ((String) whisperIdObj).isEmpty()
                || !(toCharacterIdObj instanceof String) || ((String) toCharacterIdObj).isEmpty()
                || !(textObj instanceof String) || ((String) textObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String whisperId = (String) whisperIdObj;
        String toCharacterId = (String) toCharacterIdObj;
        synchronized (campaign) {
            PlayMember senderMember = campaign.membersByUsername.get(user.username);
            if (senderMember == null || senderMember.owner == null || !senderMember.owner.equals(user.username)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            PlayMember toMember = findMemberByCharacterId(campaign, toCharacterId);
            if (toMember == null || !campaign.membersByUsername.containsKey(toMember.username)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            if (campaign.whispersById.containsKey(whisperId)) {
                sendJson(exchange, 409, mapOf("error", "whisper already exists"));
                return;
            }
            Whisper whisper = new Whisper();
            whisper.whisperId = whisperId;
            whisper.fromCharacterId = senderMember.characterId;
            whisper.toCharacterId = toCharacterId;
            whisper.text = (String) textObj;
            campaign.whispersById.put(whisperId, whisper);
            sendJson(exchange, 201, whisperToMap(whisper));
        }
    }

    private static void handleListWhispers(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            String ownCharacterId = null;
            if (!isDm) {
                PlayMember own = campaign.membersByUsername.get(user.username);
                if (own != null) {
                    ownCharacterId = own.characterId;
                }
            }
            List<Map<String, Object>> results = new ArrayList<>();
            for (Whisper whisper : campaign.whispersById.values()) {
                if (isDm
                        || (ownCharacterId != null
                                && (ownCharacterId.equals(whisper.fromCharacterId)
                                        || ownCharacterId.equals(whisper.toCharacterId)))) {
                    results.add(whisperToMap(whisper));
                }
            }
            sendJson(exchange, 200, mapOf("whispers", results));
        }
    }

    private static Map<String, Object> invitationToMap(Invitation invitation) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("invitation_id", invitation.invitationId);
        resp.put("username", invitation.username);
        resp.put("character_id", invitation.characterId);
        resp.put("status", invitation.status);
        return resp;
    }

    private static void handleCreateInvitation(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        Map<?, ?> obj = parseJsonObject(exchange);
        if (obj == null) {
            return;
        }
        Object invitationIdObj = obj.get("invitation_id");
        Object usernameObj = obj.get("username");
        Object characterIdObj = obj.get("character_id");
        if (!(invitationIdObj instanceof String) || ((String) invitationIdObj).isEmpty()
                || !(usernameObj instanceof String) || ((String) usernameObj).isEmpty()
                || !(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "invalid payload"));
            return;
        }
        String invitationId = (String) invitationIdObj;
        String targetUsername = (String) usernameObj;
        String characterId = (String) characterIdObj;

        User targetUser = USERS.get(targetUsername);
        if (targetUser == null || !"player".equals(targetUser.role)) {
            sendJson(exchange, 400, mapOf("error", "invalid target user"));
            return;
        }

        synchronized (campaign) {
            if (campaign.invitationsById.containsKey(invitationId)) {
                sendJson(exchange, 409, mapOf("error", "invitation already exists"));
                return;
            }
            for (Invitation existing : campaign.invitationsById.values()) {
                if ("pending".equals(existing.status) && existing.username.equals(targetUsername)) {
                    sendJson(exchange, 409, mapOf("error", "invitation already pending"));
                    return;
                }
            }

            Invitation invitation = new Invitation();
            invitation.invitationId = invitationId;
            invitation.username = targetUsername;
            invitation.characterId = characterId;
            invitation.status = "pending";
            campaign.invitationsById.put(invitationId, invitation);
            campaign.invitationsInOrder.add(invitation);
            sendJson(exchange, 201, invitationToMap(invitation));
        }
    }

    private static void handleAcceptInvitation(HttpExchange exchange, String campaignId, String invitationId)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            Invitation invitation = campaign.invitationsById.get(invitationId);
            if (invitation == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            if (!user.username.equals(invitation.username)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            if (!"pending".equals(invitation.status)) {
                sendJson(exchange, 409, mapOf("error", "invitation already resolved"));
                return;
            }

            invitation.status = "accepted";

            PlayMember member = campaign.membersByUsername.get(user.username);
            if (member == null) {
                member = new PlayMember();
                member.username = user.username;
                member.characterId = invitation.characterId;
                member.name = "";
                member.characterClass = "";
                member.owner = user.username;
                campaign.membersByUsername.put(user.username, member);
                campaign.characterIds.add(invitation.characterId);
            }

            sendJson(exchange, 200, invitationToMap(invitation));
        }
    }

    private static void handleListInvitations(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            boolean isDm = user.username.equals(campaign.owner);
            List<Map<String, Object>> results = new ArrayList<>();
            for (Invitation invitation : campaign.invitationsInOrder) {
                if (isDm || invitation.username.equals(user.username)) {
                    results.add(invitationToMap(invitation));
                }
            }
            sendJson(exchange, 200, mapOf("invitations", results));
        }
    }

    private static final Set<String> VALID_DELEGATION_POWERS = new HashSet<>(Arrays.asList("narrate"));

    private static Map<String, Object> delegationToMap(Delegation delegation) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("username", delegation.username);
        resp.put("powers", new ArrayList<>(delegation.powers));
        resp.put("active", delegation.active);
        return resp;
    }

    private static boolean hasDelegatedPower(PlayCampaign campaign, String username, String power) {
        Delegation delegation = campaign.delegationsByUsername.get(username);
        return delegation != null && delegation.active && delegation.powers.contains(power);
    }

    private static void handleGrantDelegation(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!user.username.equals(campaign.owner)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object usernameObj = obj.get("username");
            Object powersObj = obj.get("powers");
            if (!(usernameObj instanceof String) || ((String) usernameObj).isEmpty()
                    || !(powersObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String targetUsername = (String) usernameObj;
            List<?> powersList = (List<?>) powersObj;
            if (powersList.isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            List<String> powers = new ArrayList<>();
            Set<String> seenPowers = new HashSet<>();
            for (Object powerObj : powersList) {
                if (!(powerObj instanceof String) || !VALID_DELEGATION_POWERS.contains(powerObj)) {
                    sendJson(exchange, 400, mapOf("error", "invalid payload"));
                    return;
                }
                if (!seenPowers.add((String) powerObj)) {
                    sendJson(exchange, 400, mapOf("error", "invalid payload"));
                    return;
                }
                powers.add((String) powerObj);
            }
            if (!campaign.membersByUsername.containsKey(targetUsername)) {
                sendJson(exchange, 400, mapOf("error", "not a campaign member"));
                return;
            }
            Delegation existing = campaign.delegationsByUsername.get(targetUsername);
            if (existing != null && existing.active) {
                sendJson(exchange, 409, mapOf("error", "delegation already exists"));
                return;
            }

            Delegation delegation = new Delegation();
            delegation.username = targetUsername;
            delegation.powers.addAll(powers);
            delegation.active = true;
            campaign.delegationsByUsername.put(targetUsername, delegation);

            Map<String, Object> auditEntry = new LinkedHashMap<>();
            auditEntry.put("username", targetUsername);
            auditEntry.put("action", "granted");
            auditEntry.put("powers", new ArrayList<>(powers));
            campaign.delegationAudit.add(auditEntry);

            sendJson(exchange, 201, delegationToMap(delegation));
        }
    }

    private static void handleRevokeDelegation(HttpExchange exchange, String campaignId, String targetUsername)
            throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!user.username.equals(campaign.owner)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Delegation delegation = campaign.delegationsByUsername.get(targetUsername);
            if (delegation == null || !delegation.active) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            delegation.active = false;

            Map<String, Object> auditEntry = new LinkedHashMap<>();
            auditEntry.put("username", delegation.username);
            auditEntry.put("action", "revoked");
            auditEntry.put("powers", new ArrayList<>(delegation.powers));
            campaign.delegationAudit.add(auditEntry);

            sendJson(exchange, 200, delegationToMap(delegation));
        }
    }

    private static void handleGetDelegationAudit(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!user.username.equals(campaign.owner)) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            List<Map<String, Object>> entries = new ArrayList<>();
            for (Map<String, Object> entry : campaign.delegationAudit) {
                entries.add(new LinkedHashMap<>(entry));
            }
            sendJson(exchange, 200, mapOf("entries", entries));
        }
    }

    private static void handleCreateAuditEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object kindObj = obj.get("kind");
            Object correlationObj = obj.get("correlation_id");
            if (!(kindObj instanceof String) || ((String) kindObj).isEmpty()
                    || !(correlationObj instanceof String) || ((String) correlationObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String kind = (String) kindObj;
            String correlationId = (String) correlationObj;
            if (campaign.auditCorrelationIds.contains(correlationId)) {
                sendJson(exchange, 409, mapOf("error", "correlation_id already exists"));
                return;
            }
            String role = user.username.equals(campaign.owner) ? "DM" : "player";
            int timestamp = campaign.nextAuditTimestamp++;

            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("kind", kind);
            entry.put("actor", user.username);
            entry.put("role", role);
            entry.put("timestamp", timestamp);
            entry.put("correlation_id", correlationId);

            campaign.auditTrail.add(entry);
            campaign.auditCorrelationIds.add(correlationId);

            sendJson(exchange, 201, entry);
        }
    }

    private static void handleListAuditEvents(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignOwner(exchange, campaign, user)) {
                return;
            }
            List<Map<String, Object>> entries = new ArrayList<>();
            for (Map<String, Object> entry : campaign.auditTrail) {
                entries.add(new LinkedHashMap<>(entry));
            }
            sendJson(exchange, 200, mapOf("entries", entries));
        }
    }

    private static void handleAppendProjectionEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            boolean isOwner = user.username.equals(campaign.owner);
            if (isOwner) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object eventIdObj = obj.get("event_id");
            Object kindObj = obj.get("kind");
            Object valueObj = obj.get("value");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String eventId = (String) eventIdObj;
            if (!(kindObj instanceof String)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String kind = (String) kindObj;
            if (!"set-story".equals(kind) && !"increment-danger".equals(kind)) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String value = null;
            if ("set-story".equals(kind)) {
                if (!(valueObj instanceof String) || ((String) valueObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid payload"));
                    return;
                }
                value = (String) valueObj;
            } else {
                if (valueObj != null) {
                    sendJson(exchange, 400, mapOf("error", "invalid payload"));
                    return;
                }
            }
            if (campaign.projectionEventIds.contains(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event_id already exists"));
                return;
            }

            ProjectionEvent event = new ProjectionEvent();
            event.sequence = campaign.nextProjectionSequence++;
            event.eventId = eventId;
            event.kind = kind;
            event.value = value;

            campaign.projectionEvents.add(event);
            campaign.projectionEventIds.add(eventId);
            campaign.projectionEventCount++;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("sequence", event.sequence);
            resp.put("event_id", event.eventId);
            resp.put("kind", event.kind);
            if ("set-story".equals(kind)) {
                resp.put("value", event.value);
            }
            sendJson(exchange, 201, resp);
        }
    }

    private static void handleGetProjection(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            String story = "";
            int danger = 0;
            List<String> appliedEventIds = new ArrayList<>();
            List<ProjectionEvent> ordered = new ArrayList<>(campaign.projectionEvents);
            ordered.sort((a, b) -> Integer.compare(a.sequence, b.sequence));
            for (ProjectionEvent event : ordered) {
                if ("set-story".equals(event.kind)) {
                    story = event.value;
                } else if ("increment-danger".equals(event.kind)) {
                    danger++;
                }
                appliedEventIds.add(event.eventId);
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("story", story);
            resp.put("danger", danger);
            resp.put("applied_event_ids", appliedEventIds);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreateIdempotentEvent(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        String idempotencyKey = exchange.getRequestHeaders().getFirst("Idempotency-Key");
        if (idempotencyKey == null || idempotencyKey.trim().isEmpty()) {
            sendJson(exchange, 400, mapOf("error", "missing idempotency key"));
            return;
        }
        idempotencyKey = idempotencyKey.trim();
        synchronized (campaign) {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object eventIdObj = obj.get("event_id");
            Object valueObj = obj.get("value");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                    || !(valueObj instanceof String) || ((String) valueObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid payload"));
                return;
            }
            String eventId = (String) eventIdObj;
            String value = (String) valueObj;

            IdempotentEvent existingForKey = campaign.idempotentEventsByKey.get(idempotencyKey);
            if (existingForKey != null) {
                if (existingForKey.eventId.equals(eventId) && existingForKey.value.equals(value)) {
                    sendJson(exchange, 200, idempotentEventJson(existingForKey));
                } else {
                    sendJson(exchange, 409, mapOf("error", "idempotency key conflict"));
                }
                return;
            }

            if (campaign.idempotentEventIdOwners.containsKey(eventId)) {
                sendJson(exchange, 409, mapOf("error", "event_id already exists"));
                return;
            }

            IdempotentEvent event = new IdempotentEvent();
            event.sequence = campaign.nextIdempotentSequence++;
            event.eventId = eventId;
            event.value = value;
            event.idempotencyKey = idempotencyKey;

            campaign.idempotentEvents.add(event);
            campaign.idempotentEventIdOwners.put(eventId, idempotencyKey);
            campaign.idempotentEventsByKey.put(idempotencyKey, event);

            sendJson(exchange, 201, idempotentEventJson(event));
        }
    }

    private static void handleListIdempotentEvents(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<IdempotentEvent> ordered = new ArrayList<>(campaign.idempotentEvents);
            ordered.sort((a, b) -> Integer.compare(a.sequence, b.sequence));
            List<Map<String, Object>> events = new ArrayList<>();
            for (IdempotentEvent event : ordered) {
                events.add(idempotentEventJson(event));
            }
            sendJson(exchange, 200, mapOf("events", events));
        }
    }

    private static Map<String, Object> idempotentEventJson(IdempotentEvent event) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("event_id", event.eventId);
        resp.put("value", event.value);
        resp.put("sequence", event.sequence);
        resp.put("idempotency_key", event.idempotencyKey);
        return resp;
    }

    private static void handleGetCharacterSheet(HttpExchange exchange, String campaignId, String characterId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignMember(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = findMemberByCharacterId(campaign, characterId);
            if (member == null) {
                sendJson(exchange, 404, mapOf("error", "not found"));
                return;
            }
            boolean isDm = user.username.equals(campaign.owner);
            boolean isOwner = member.owner != null && member.owner.equals(user.username);
            if (!isDm && !isOwner) {
                sendJson(exchange, 403, mapOf("error", "forbidden"));
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("character_id", member.characterId);
            resp.put("owner", member.owner);
            resp.put("name", member.name);
            resp.put("class", member.characterClass);
            resp.put("level", 1);
            resp.put("proficiency_bonus", 2);
            resp.put("hp_max", 10);
            resp.put("armor_class", 10);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetGmStatus(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            List<Map<String, Object>> party = new ArrayList<>();
            for (PlayMember member : campaign.membersByUsername.values()) {
                Map<String, Object> summary = new LinkedHashMap<>();
                summary.put("username", member.username);
                summary.put("character_id", member.characterId);
                summary.put("name", member.name);
                summary.put("class", member.characterClass);
                party.add(summary);
            }

            int fromIndex = Math.max(0, campaign.narrationEvents.size() - 10);
            List<Map<String, Object>> recentEvents = new ArrayList<>(
                    campaign.narrationEvents.subList(fromIndex, campaign.narrationEvents.size()));

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("needs_attention", user.username.equals(campaign.currentActor));
            resp.put("current_actor", campaign.currentActor);
            resp.put("party", party);
            resp.put("recent_events", recentEvents);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetMyTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        if (!"player".equals(user.role)) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            PlayMember member = campaign.membersByUsername.get(user.username);
            if (member == null) {
                sendJson(exchange, 403, mapOf("error", "not a campaign member"));
                return;
            }

            Map<String, Object> character = new LinkedHashMap<>();
            character.put("id", member.characterId);
            character.put("name", member.name);

            int fromIndex = Math.max(0, campaign.narrationEvents.size() - 10);
            List<Map<String, Object>> recentEvents = new ArrayList<>(
                    campaign.narrationEvents.subList(fromIndex, campaign.narrationEvents.size()));

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("is_my_turn", user.username.equals(campaign.currentActor));
            resp.put("current_actor", campaign.currentActor);
            resp.put("character", character);
            resp.put("recent_events", recentEvents);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleGetPlayCampaignTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaign.id);
            resp.put("current_actor", campaign.currentActor);
            resp.put("phase", campaign.phase);
            resp.put("turn_number", campaign.turnNumber);
            resp.put("queue", campaign.turnQueue == null ? buildTurnQueue(campaign.membersByUsername.size()) : campaign.turnQueue);
            resp.put("overdue", false);
            resp.put("logical_deadline", campaign.turnNumber + 1);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleNudgeTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object messageObj = obj.get("message");
            if (!(messageObj instanceof String) || ((String) messageObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid message"));
                return;
            }

            synchronized (campaign) {
                campaign.nudgeCount += 1;

                int sequence = campaign.narrationEvents.size() + 1;
                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "nudge");
                event.put("actor", user.username);
                event.put("text", messageObj);
                campaign.narrationEvents.add(event);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("campaign_id", campaign.id);
                resp.put("actor", user.username);
                resp.put("target", campaign.currentActor);
                resp.put("message", messageObj);
                resp.put("nudge_count", campaign.nudgeCount);
                sendJson(exchange, 201, resp);
            }
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAddNarration(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        boolean isOwner = user.username.equals(campaign.owner);
        boolean isDelegate;
        synchronized (campaign) {
            isDelegate = hasDelegatedPower(campaign, user.username, "narrate");
        }
        if (!isOwner && !isDelegate) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object textObj = obj.get("text");
            if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid text"));
                return;
            }

            synchronized (campaign) {
                int sequence = campaign.narrationEvents.size() + 1;
                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "narration");
                event.put("actor", isOwner ? "dm" : user.username);
                event.put("text", textObj);
                campaign.narrationEvents.add(event);

                sendJson(exchange, 201, event);
            }
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleAddMessage(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object textObj = obj.get("text");
            if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid text"));
                return;
            }

            int sequence = campaign.narrationEvents.size() + 1;
            Map<String, Object> event = new LinkedHashMap<>();
            event.put("sequence", sequence);
            event.put("kind", "chat");
            event.put("actor", user.username);
            event.put("text", textObj);
            event.put("current_actor", campaign.currentActor);
            campaign.narrationEvents.add(event);

            sendJson(exchange, 201, event);
        }
    }

    /**
     * The queue can contain "dm" more than once (once per player), so the
     * next actor must be derived from the campaign's current position in the
     * queue rather than by searching for the current actor's name.
     */
    private static int nextTurnIndex(List<String> queue, int currentIndex) {
        if (queue == null || queue.isEmpty()) {
            return 0;
        }
        return (currentIndex + 1) % queue.size();
    }

    private static void handleAddPlayerAction(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            if (!campaign.membersByUsername.containsKey(user.username)
                    || !user.username.equals(campaign.currentActor)) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            try {
                Map<?, ?> obj = parseJsonObject(exchange);
                if (obj == null) {
                    return;
                }
                Object typeObj = obj.get("type");
                Object textObj = obj.get("text");
                if (!(typeObj instanceof String) || ((String) typeObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid type"));
                    return;
                }
                if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid text"));
                    return;
                }

                int sequence = campaign.narrationEvents.size() + 1;
                int nextIdx = nextTurnIndex(campaign.turnQueue, campaign.turnIndex);
                String nextActor = (campaign.turnQueue == null || campaign.turnQueue.isEmpty())
                        ? "dm"
                        : campaign.turnQueue.get(nextIdx);

                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "action");
                event.put("actor", user.username);
                event.put("type", typeObj);
                event.put("text", textObj);
                event.put("next_actor", nextActor);
                campaign.narrationEvents.add(event);
                campaign.currentActor = nextActor;
                campaign.turnIndex = nextIdx;

                sendJson(exchange, 201, event);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
            }
        }
    }

    private static void handleTravelTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            if (!campaign.membersByUsername.containsKey(user.username)
                    || !user.username.equals(campaign.currentActor)) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            try {
                Map<?, ?> obj = parseJsonObject(exchange);
                if (obj == null) {
                    return;
                }
                Object destinationObj = obj.get("destination_id");
                if (!(destinationObj instanceof String) || ((String) destinationObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid destination_id"));
                    return;
                }
                String destinationId = (String) destinationObj;

                Location current = campaign.currentLocationId == null
                        ? null
                        : campaign.locationsById.get(campaign.currentLocationId);
                Connection connection = null;
                if (current != null) {
                    for (Connection candidate : current.connections) {
                        if (candidate.toId.equals(destinationId)) {
                            connection = candidate;
                            break;
                        }
                    }
                }
                if (connection == null) {
                    sendJson(exchange, 409, mapOf("error", "invalid destination"));
                    return;
                }

                int sequence = campaign.narrationEvents.size() + 1;
                int nextIdx = nextTurnIndex(campaign.turnQueue, campaign.turnIndex);
                String nextActor = (campaign.turnQueue == null || campaign.turnQueue.isEmpty())
                        ? "dm"
                        : campaign.turnQueue.get(nextIdx);

                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "travel");
                event.put("actor", user.username);
                event.put("destination_id", destinationId);
                event.put("travel_turns", connection.travelTurns);
                event.put("next_actor", nextActor);
                campaign.narrationEvents.add(event);
                campaign.currentActor = nextActor;
                campaign.turnIndex = nextIdx;
                campaign.currentLocationId = destinationId;

                sendJson(exchange, 201, event);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
            }
        }
    }

    private static void handleRestTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            if (!campaign.membersByUsername.containsKey(user.username)
                    || !user.username.equals(campaign.currentActor)) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            try {
                Map<?, ?> obj = parseJsonObject(exchange);
                if (obj == null) {
                    return;
                }
                Object typeObj = obj.get("type");
                if (!(typeObj instanceof String)
                        || (!"long".equals(typeObj) && !"short".equals(typeObj))) {
                    sendJson(exchange, 400, mapOf("error", "invalid type"));
                    return;
                }
                String restType = (String) typeObj;

                PlayMember member = campaign.membersByUsername.get(user.username);
                if ("long".equals(restType)) {
                    member.hpCurrent = member.hpMax;
                }

                int sequence = campaign.narrationEvents.size() + 1;
                int nextIdx = nextTurnIndex(campaign.turnQueue, campaign.turnIndex);
                String nextActor = (campaign.turnQueue == null || campaign.turnQueue.isEmpty())
                        ? "dm"
                        : campaign.turnQueue.get(nextIdx);

                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "rest");
                event.put("actor", user.username);
                event.put("type", restType);
                event.put("hp_current", member.hpCurrent);
                event.put("hp_max", member.hpMax);
                event.put("next_actor", nextActor);
                campaign.narrationEvents.add(event);
                campaign.currentActor = nextActor;
                campaign.turnIndex = nextIdx;

                sendJson(exchange, 201, event);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
            }
        }
    }

    private static void handleAddResolution(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        synchronized (campaign) {
            if (!requireCampaignMember(exchange, campaign, user)) {
                return;
            }
            if (!user.username.equals(campaign.owner)) {
                sendJson(exchange, 409, mapOf("error", "not your turn"));
                return;
            }

            try {
                Map<?, ?> obj = parseJsonObject(exchange);
                if (obj == null) {
                    return;
                }
                Object textObj = obj.get("text");
                if (!(textObj instanceof String) || ((String) textObj).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid text"));
                    return;
                }

                int sequence = campaign.narrationEvents.size() + 1;
                int nextIdx = nextTurnIndex(campaign.turnQueue, campaign.turnIndex);
                String nextActor = (campaign.turnQueue == null || campaign.turnQueue.isEmpty())
                        ? "dm"
                        : campaign.turnQueue.get(nextIdx);

                Map<String, Object> event = new LinkedHashMap<>();
                event.put("sequence", sequence);
                event.put("kind", "resolution");
                event.put("actor", user.username);
                event.put("text", textObj);
                event.put("next_actor", nextActor);
                campaign.narrationEvents.add(event);
                campaign.currentActor = nextActor;
                campaign.turnIndex = nextIdx;
                campaign.turnNumber++;
                event.put("turn_number", campaign.turnNumber);

                sendJson(exchange, 201, event);
            } catch (Exception e) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
            }
        }
    }

    private static void handleStartPlayCampaign(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        if (!requireCampaignOwner(exchange, campaign, user)) {
            return;
        }
        synchronized (campaign) {
            if (!"lobby".equals(campaign.status) || campaign.membersByUsername.size() < 2) {
                sendJson(exchange, 409, mapOf("error", "cannot start campaign"));
                return;
            }

            String firstMember = campaign.membersByUsername.keySet().iterator().next();
            campaign.status = "active";
            campaign.phase = "player";
            campaign.currentActor = firstMember;
            campaign.turnIndex = 0;
            campaign.turnNumber = 1;
            campaign.turnQueue = buildTurnQueue(campaign.membersByUsername.size());

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", campaign.id);
            resp.put("status", campaign.status);
            resp.put("current_actor", campaign.currentActor);
            resp.put("turn_number", campaign.turnNumber);
            sendJson(exchange, 200, resp);
        }
    }

    private static void handleCreatePlayCampaign(HttpExchange exchange) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        if (!"dm".equals(user.role)) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object idObj = obj.get("id");
            Object nameObj = obj.get("name");
            Object maxPlayersObj = obj.get("max_players");

            if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(maxPlayersObj instanceof Number)) {
                sendJson(exchange, 400, mapOf("error", "invalid max_players"));
                return;
            }

            String id = (String) idObj;
            PlayCampaign campaign = new PlayCampaign();
            campaign.id = id;
            campaign.name = (String) nameObj;
            campaign.owner = user.username;
            campaign.status = "lobby";
            campaign.maxPlayers = ((Number) maxPlayersObj).intValue();

            PlayCampaign existing = PLAY_CAMPAIGNS.putIfAbsent(id, campaign);
            if (existing != null) {
                sendJson(exchange, 409, mapOf("error", "campaign already exists"));
                return;
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", campaign.id);
            resp.put("name", campaign.name);
            resp.put("owner", campaign.owner);
            resp.put("status", campaign.status);
            resp.put("max_players", campaign.maxPlayers);
            sendJson(exchange, 201, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleJoinPlayCampaign(HttpExchange exchange, String campaignId) throws IOException {
        User user = requireSessionUser(exchange);
        if (user == null) {
            return;
        }
        if (!"player".equals(user.role)) {
            sendJson(exchange, 403, mapOf("error", "forbidden"));
            return;
        }
        PlayCampaign campaign = requirePlayCampaign(exchange, campaignId);
        if (campaign == null) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object characterIdObj = obj.get("character_id");
            Object nameObj = obj.get("name");
            Object classObj = obj.get("class");

            if (!(characterIdObj instanceof String) || ((String) characterIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid character_id"));
                return;
            }
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid name"));
                return;
            }
            if (!(classObj instanceof String) || ((String) classObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid class"));
                return;
            }

            String characterId = (String) characterIdObj;

            synchronized (campaign) {
                if (campaign.membersByUsername.containsKey(user.username)) {
                    sendJson(exchange, 409, mapOf("error", "already a member"));
                    return;
                }
                if (campaign.characterIds.contains(characterId)) {
                    sendJson(exchange, 409, mapOf("error", "character already in use"));
                    return;
                }
                if (campaign.membersByUsername.size() >= campaign.maxPlayers) {
                    sendJson(exchange, 409, mapOf("error", "party is full"));
                    return;
                }

                PlayMember member = new PlayMember();
                member.username = user.username;
                member.characterId = characterId;
                member.name = (String) nameObj;
                member.characterClass = (String) classObj;
                member.owner = user.username;

                campaign.membersByUsername.put(user.username, member);
                campaign.characterIds.add(characterId);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("username", member.username);
                resp.put("character_id", member.characterId);
                resp.put("name", member.name);
                resp.put("class", member.characterClass);
                sendJson(exchange, 201, resp);
            }
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    // ---------- DM tools handlers ----------

    private static String recommendationFor(String difficulty) {
        switch (difficulty) {
            case "trivial": return "trivial encounter";
            case "easy": return "safe warm-up";
            case "medium": return "balanced challenge";
            case "hard": return "dangerous fight";
            case "deadly": return "deadly showdown, prepare escape plans";
            default: return "unknown";
        }
    }

    private static void handleEncounterBuilder(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object campaignIdObj = obj.get("campaign_id");
            Object partyObj = obj.get("party");
            Object slugsObj = obj.get("monster_slugs");
            if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid campaign_id"));
                return;
            }
            if (!(partyObj instanceof List) || !(slugsObj instanceof List)) {
                sendJson(exchange, 400, mapOf("error", "invalid request"));
                return;
            }
            String campaignId = (String) campaignIdObj;
            List<?> party = (List<?>) partyObj;
            List<?> slugs = (List<?>) slugsObj;

            int[] thresholdSum = new int[]{0, 0, 0, 0};
            for (Object p : party) {
                if (!(p instanceof Map)) {
                    sendJson(exchange, 400, mapOf("error", "invalid party entry"));
                    return;
                }
                Object levelObj = ((Map<?, ?>) p).get("level");
                if (!(levelObj instanceof Number)) {
                    sendJson(exchange, 400, mapOf("error", "invalid party entry"));
                    return;
                }
                int level = ((Number) levelObj).intValue();
                int[] th = LEVEL_THRESHOLDS.get(level);
                if (th == null) {
                    sendJson(exchange, 400, mapOf("error", "unsupported level"));
                    return;
                }
                for (int i = 0; i < 4; i++) thresholdSum[i] += th[i];
            }

            long baseXp = 0;
            long monsterCount = 0;
            for (Object s : slugs) {
                if (!(s instanceof String) || ((String) s).isEmpty()) {
                    sendJson(exchange, 400, mapOf("error", "invalid monster_slugs"));
                    return;
                }
                Map<String, Object> monster = MONSTERS.get(s);
                if (monster == null) {
                    sendJson(exchange, 400, mapOf("error", "monster not found"));
                    return;
                }
                Object crObj = monster.get("cr");
                Integer xp = (crObj instanceof String) ? CR_XP.get(crObj) : null;
                if (xp == null) {
                    sendJson(exchange, 400, mapOf("error", "unsupported cr"));
                    return;
                }
                baseXp += xp;
                monsterCount++;
            }

            double multiplier = multiplierFor(monsterCount);
            double adjustedXp = baseXp * multiplier;

            String difficulty = "trivial";
            if (adjustedXp >= thresholdSum[3]) difficulty = "deadly";
            else if (adjustedXp >= thresholdSum[2]) difficulty = "hard";
            else if (adjustedXp >= thresholdSum[1]) difficulty = "medium";
            else if (adjustedXp >= thresholdSum[0]) difficulty = "easy";

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaignId);
            resp.put("base_xp", baseXp);
            resp.put("adjusted_xp", numeric(adjustedXp));
            resp.put("difficulty", difficulty);
            resp.put("monster_count", monsterCount);
            resp.put("recommendation", recommendationFor(difficulty));
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleLootParcel(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object campaignIdObj = obj.get("campaign_id");
            Object tierObj = obj.get("tier");
            Object seedObj = obj.get("seed");
            if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid campaign_id"));
                return;
            }
            if (!(tierObj instanceof Number) || !isIntegral(tierObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid tier"));
                return;
            }
            if (!(seedObj instanceof Number) || !isIntegral(seedObj)) {
                sendJson(exchange, 400, mapOf("error", "invalid seed"));
                return;
            }
            long tier = ((Number) tierObj).longValue();
            if (tier != 1) {
                sendJson(exchange, 400, mapOf("error", "unsupported tier"));
                return;
            }
            String campaignId = (String) campaignIdObj;

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("slug", "healing-potion");
            item.put("quantity", 2L);
            List<Object> items = new ArrayList<>();
            items.add(item);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaignId);
            resp.put("coins_gp", 75L);
            resp.put("items", items);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    private static void handleSessionRecap(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) {
            return;
        }
        try {
            Map<?, ?> obj = parseJsonObject(exchange);
            if (obj == null) {
                return;
            }
            Object campaignIdObj = obj.get("campaign_id");
            if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                sendJson(exchange, 400, mapOf("error", "invalid campaign_id"));
                return;
            }
            String campaignId = (String) campaignIdObj;

            List<Object> openThreads = new ArrayList<>();
            openThreads.add("Resolve goblin trail ambush");

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("campaign_id", campaignId);
            resp.put("summary", "Nyx scouts the goblin trail.");
            resp.put("open_threads", openThreads);
            sendJson(exchange, 200, resp);
        } catch (Exception e) {
            sendJson(exchange, 400, mapOf("error", "invalid request"));
        }
    }

    // ---------- Helpers ----------

    /**
     * Enforces the expected HTTP method for a single-method endpoint. Sends a 405
     * response and returns false if the request doesn't match, so callers can
     * write {@code if (!requireMethod(exchange, "POST")) return;}.
     */
    private static boolean requireMethod(HttpExchange exchange, String method) throws IOException {
        if (!method.equalsIgnoreCase(exchange.getRequestMethod())) {
            sendJson(exchange, 405, mapOf("error", "method not allowed"));
            return false;
        }
        return true;
    }

    /**
     * Reads and parses the request body as a JSON object. Sends a 400 "invalid
     * body" response and returns null if the body isn't a JSON object; callers
     * must check for null and return without sending another response. Malformed
     * JSON propagates as an exception, matching each handler's existing
     * top-level catch that reports "invalid request".
     */
    private static Map<?, ?> parseJsonObject(HttpExchange exchange) throws IOException {
        Object body = Json.parse(readBody(exchange));
        if (!(body instanceof Map)) {
            sendJson(exchange, 400, mapOf("error", "invalid body"));
            return null;
        }
        return (Map<?, ?>) body;
    }

    private static Object numeric(double value) {
        if (value == Math.rint(value) && !Double.isInfinite(value)) {
            return (long) value;
        }
        return value;
    }

    private static Map<String, Object> mapOf(String key, Object value) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(key, value);
        return m;
    }

    private static String readBody(HttpExchange exchange) throws IOException {
        try (InputStream is = exchange.getRequestBody()) {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) != -1) {
                baos.write(buf, 0, n);
            }
            return baos.toString(StandardCharsets.UTF_8);
        }
    }

    private static void sendJson(HttpExchange exchange, int status, Object payload) throws IOException {
        byte[] bytes = Json.stringify(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    // ---------- Minimal JSON parser/serializer ----------

    static final class Json {
        private final String src;
        private int pos;

        private Json(String src) {
            this.src = src;
            this.pos = 0;
        }

        static Object parse(String s) {
            Json p = new Json(s);
            p.skipWhitespace();
            Object v = p.parseValue();
            p.skipWhitespace();
            if (p.pos != p.src.length()) {
                throw new RuntimeException("trailing content");
            }
            return v;
        }

        private Object parseValue() {
            if (pos >= src.length()) throw new RuntimeException("unexpected end");
            char c = src.charAt(pos);
            switch (c) {
                case '{': return parseObject();
                case '[': return parseArray();
                case '"': return parseString();
                case 't':
                    expect("true");
                    return Boolean.TRUE;
                case 'f':
                    expect("false");
                    return Boolean.FALSE;
                case 'n':
                    expect("null");
                    return null;
                default:
                    return parseNumber();
            }
        }

        private void expect(String literal) {
            if (!src.regionMatches(pos, literal, 0, literal.length())) {
                throw new RuntimeException("expected " + literal);
            }
            pos += literal.length();
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new LinkedHashMap<>();
            pos++; // {
            skipWhitespace();
            if (peek() == '}') {
                pos++;
                return map;
            }
            while (true) {
                skipWhitespace();
                if (peek() != '"') throw new RuntimeException("expected string key");
                String key = parseString();
                skipWhitespace();
                if (peek() != ':') throw new RuntimeException("expected colon");
                pos++;
                skipWhitespace();
                Object value = parseValue();
                map.put(key, value);
                skipWhitespace();
                char ch = peek();
                if (ch == ',') {
                    pos++;
                } else if (ch == '}') {
                    pos++;
                    break;
                } else {
                    throw new RuntimeException("expected , or }");
                }
            }
            return map;
        }

        private List<Object> parseArray() {
            List<Object> list = new ArrayList<>();
            pos++; // [
            skipWhitespace();
            if (peek() == ']') {
                pos++;
                return list;
            }
            while (true) {
                skipWhitespace();
                list.add(parseValue());
                skipWhitespace();
                char ch = peek();
                if (ch == ',') {
                    pos++;
                } else if (ch == ']') {
                    pos++;
                    break;
                } else {
                    throw new RuntimeException("expected , or ]");
                }
            }
            return list;
        }

        private String parseString() {
            StringBuilder sb = new StringBuilder();
            pos++; // opening quote
            while (true) {
                if (pos >= src.length()) throw new RuntimeException("unterminated string");
                char c = src.charAt(pos++);
                if (c == '"') break;
                if (c == '\\') {
                    if (pos >= src.length()) throw new RuntimeException("bad escape");
                    char esc = src.charAt(pos++);
                    switch (esc) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u':
                            String hex = src.substring(pos, pos + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            pos += 4;
                            break;
                        default:
                            throw new RuntimeException("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object parseNumber() {
            int start = pos;
            if (peek() == '-') pos++;
            while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            boolean isDouble = false;
            if (pos < src.length() && src.charAt(pos) == '.') {
                isDouble = true;
                pos++;
                while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            }
            if (pos < src.length() && (src.charAt(pos) == 'e' || src.charAt(pos) == 'E')) {
                isDouble = true;
                pos++;
                if (pos < src.length() && (src.charAt(pos) == '+' || src.charAt(pos) == '-')) pos++;
                while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
            }
            String numStr = src.substring(start, pos);
            if (numStr.isEmpty() || "-".equals(numStr)) throw new RuntimeException("invalid number");
            if (isDouble) {
                return Double.parseDouble(numStr);
            }
            try {
                return Long.parseLong(numStr);
            } catch (NumberFormatException e) {
                return Double.parseDouble(numStr);
            }
        }

        private char peek() {
            if (pos >= src.length()) throw new RuntimeException("unexpected end");
            return src.charAt(pos);
        }

        private void skipWhitespace() {
            while (pos < src.length() && Character.isWhitespace(src.charAt(pos))) pos++;
        }

        static String stringify(Object value) {
            StringBuilder sb = new StringBuilder();
            stringify(value, sb);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void stringify(Object value, StringBuilder sb) {
            if (value == null) {
                sb.append("null");
            } else if (value instanceof String) {
                sb.append('"');
                for (char c : ((String) value).toCharArray()) {
                    switch (c) {
                        case '"': sb.append("\\\""); break;
                        case '\\': sb.append("\\\\"); break;
                        case '\n': sb.append("\\n"); break;
                        case '\r': sb.append("\\r"); break;
                        case '\t': sb.append("\\t"); break;
                        default:
                            if (c < 0x20) {
                                sb.append(String.format("\\u%04x", (int) c));
                            } else {
                                sb.append(c);
                            }
                    }
                }
                sb.append('"');
            } else if (value instanceof Boolean) {
                sb.append(value.toString());
            } else if (value instanceof Long || value instanceof Integer) {
                sb.append(value.toString());
            } else if (value instanceof Double || value instanceof Float) {
                double d = ((Number) value).doubleValue();
                if (d == Math.rint(d) && !Double.isInfinite(d)) {
                    sb.append((long) d);
                } else {
                    sb.append(d);
                }
            } else if (value instanceof Map) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> e : ((Map<String, Object>) value).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    stringify(e.getKey(), sb);
                    sb.append(':');
                    stringify(e.getValue(), sb);
                }
                sb.append('}');
            } else if (value instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object item : (List<Object>) value) {
                    if (!first) sb.append(',');
                    first = false;
                    stringify(item, sb);
                }
                sb.append(']');
            } else {
                throw new RuntimeException("cannot stringify " + value.getClass());
            }
        }
    }
}
