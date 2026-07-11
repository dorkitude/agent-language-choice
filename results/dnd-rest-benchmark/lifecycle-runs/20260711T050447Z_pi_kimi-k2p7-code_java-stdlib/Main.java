import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Iterator;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.util.Base64;
import java.io.File;

public class Main {
    public static void main(String[] args) throws Exception {
        SQLiteStore.init();
        String portEnv = System.getenv("PORT");
        int port = portEnv == null ? 8080 : Integer.parseInt(portEnv);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/dice/stats", new DiceStatsHandler());
        server.createContext("/v1/checks/ability", new AbilityCheckHandler());
        server.createContext("/v1/encounters/adjusted-xp", new EncounterHandler());
        server.createContext("/v1/initiative/order", new InitiativeHandler());
        server.createContext("/v1/characters/ability-modifier", new AbilityModifierHandler());
        server.createContext("/v1/characters/proficiency", new ProficiencyHandler());
        server.createContext("/v1/characters/derived-stats", new DerivedStatsHandler());
        server.createContext("/v1/combat/sessions", new CombatSessionsHandler());
        server.createContext("/v1/auth/register", new RegisterHandler());
        server.createContext("/v1/auth/login", new LoginHandler());
        server.createContext("/v1/storage/status", new StorageStatusHandler());
        server.createContext("/v1/storage/reset", new StorageResetHandler());
        server.createContext("/v1/compendium/monsters", new MonstersHandler());
        server.createContext("/v1/compendium/items", new ItemsHandler());
        server.createContext("/v1/campaigns", new CampaignsHandler());
        server.createContext("/v1/phb/spell-slots", new SpellSlotsHandler());
        server.createContext("/v1/phb/rests/long", new LongRestHandler());
        server.createContext("/v1/phb/equipment-load", new EquipmentLoadHandler());
        server.createContext("/v1/dm/encounter-builder", new DmEncounterHandler());
        server.createContext("/v1/dm/loot-parcel", new DmLootHandler());
        server.createContext("/v1/dm/session-recap", new DmSessionRecapHandler());
        server.setExecutor(null);
        server.start();
    }

    static void sendJson(HttpExchange ex, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    static String readBody(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            return new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static class HealthHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"GET".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            sendJson(ex, 200, "{\"ok\":true}");
        }
    }

    static class DiceStatsHandler implements HttpHandler {
        private static final Pattern PATTERN = Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String expression = Json.str(body.get("expression"));
                Matcher m = PATTERN.matcher(expression);
                if (!m.matches()) throw new RuntimeException("invalid expression");
                int count = Integer.parseInt(m.group(1));
                int sides = Integer.parseInt(m.group(2));
                int modifier = 0;
                if (m.group(3) != null) {
                    int mod = Integer.parseInt(m.group(4));
                    modifier = "+".equals(m.group(3)) ? mod : -mod;
                }
                if (count <= 0 || sides <= 0) throw new RuntimeException("invalid expression");
                int min = count + modifier;
                int max = count * sides + modifier;
                double average = (min + max) / 2.0;
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("dice_count", count);
                result.put("sides", sides);
                result.put("modifier", modifier);
                result.put("min", min);
                result.put("max", max);
                result.put("average", average);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid expression\"}");
            }
        }
    }

    static class AbilityCheckHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int roll = Json.num(body.get("roll"));
                int modifier = Json.num(body.get("modifier"));
                int dc = Json.num(body.get("dc"));
                int total = roll + modifier;
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("total", total);
                result.put("success", total >= dc);
                result.put("margin", total - dc);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class EncounterHandler implements HttpHandler {
        private static final Map<String, Integer> XP = new HashMap<>();
        private static final Map<Integer, int[]> THRESHOLDS = new HashMap<>();

        static {
            XP.put("0", 10);
            XP.put("1/8", 25);
            XP.put("1/4", 50);
            XP.put("1/2", 100);
            XP.put("1", 200);
            XP.put("2", 450);
            XP.put("3", 700);
            XP.put("4", 1100);
            XP.put("5", 1800);

            THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
        }

        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                List<Object> party = Json.arr(body.get("party"));
                List<Object> monsters = Json.arr(body.get("monsters"));

                int baseXp = 0;
                int monsterCount = 0;
                for (Object m : monsters) {
                    Map<String, Object> monster = Json.obj(m);
                    String cr = Json.str(monster.get("cr"));
                    int count = Json.num(monster.get("count"));
                    Integer xp = XP.get(cr);
                    if (xp == null) throw new RuntimeException("unsupported cr");
                    baseXp += xp * count;
                    monsterCount += count;
                }

                double multiplier;
                if (monsterCount == 1) multiplier = 1;
                else if (monsterCount == 2) multiplier = 1.5;
                else if (monsterCount <= 6) multiplier = 2;
                else if (monsterCount <= 10) multiplier = 2.5;
                else if (monsterCount <= 14) multiplier = 3;
                else multiplier = 4;

                int adjustedXp = (int) (baseXp * multiplier);

                int easy = 0, medium = 0, hard = 0, deadly = 0;
                for (Object p : party) {
                    Map<String, Object> member = Json.obj(p);
                    int level = Json.num(member.get("level"));
                    int[] t = THRESHOLDS.get(level);
                    if (t == null) throw new RuntimeException("unsupported level");
                    easy += t[0];
                    medium += t[1];
                    hard += t[2];
                    deadly += t[3];
                }

                String difficulty;
                if (adjustedXp >= deadly) difficulty = "deadly";
                else if (adjustedXp >= hard) difficulty = "hard";
                else if (adjustedXp >= medium) difficulty = "medium";
                else if (adjustedXp >= easy) difficulty = "easy";
                else difficulty = "trivial";

                Map<String, Object> thresholds = new LinkedHashMap<>();
                thresholds.put("easy", easy);
                thresholds.put("medium", medium);
                thresholds.put("hard", hard);
                thresholds.put("deadly", deadly);

                Map<String, Object> result = new LinkedHashMap<>();
                result.put("base_xp", baseXp);
                result.put("monster_count", monsterCount);
                result.put("multiplier", multiplier);
                result.put("adjusted_xp", adjustedXp);
                result.put("difficulty", difficulty);
                result.put("thresholds", thresholds);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static int abilityModifier(int score) {
        return Math.floorDiv(score - 10, 2);
    }

    static int proficiencyBonus(int level) {
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    static class AbilityModifierHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int score = Json.num(body.get("score"));
                if (score < 1 || score > 30) throw new RuntimeException("score out of range");
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("score", score);
                result.put("modifier", abilityModifier(score));
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class ProficiencyHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int level = Json.num(body.get("level"));
                if (level < 1 || level > 20) throw new RuntimeException("level out of range");
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("level", level);
                result.put("proficiency_bonus", proficiencyBonus(level));
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class DerivedStatsHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int level = Json.num(body.get("level"));
                if (level < 1 || level > 20) throw new RuntimeException("level out of range");

                Map<String, Object> abilities = Json.obj(body.get("abilities"));
                Map<String, Integer> modifiers = new LinkedHashMap<>();
                modifiers.put("str", abilityModifier(Json.num(abilities.get("str"))));
                modifiers.put("dex", abilityModifier(Json.num(abilities.get("dex"))));
                modifiers.put("con", abilityModifier(Json.num(abilities.get("con"))));
                modifiers.put("int", abilityModifier(Json.num(abilities.get("int"))));
                modifiers.put("wis", abilityModifier(Json.num(abilities.get("wis"))));
                modifiers.put("cha", abilityModifier(Json.num(abilities.get("cha"))));

                Map<String, Object> armor = Json.obj(body.get("armor"));
                int base = Json.num(armor.get("base"));
                int dexCap = Json.num(armor.get("dex_cap"));
                boolean hasShield = (Boolean) armor.get("shield");
                int shieldBonus = hasShield ? 2 : 0;
                int armorClass = base + Math.min(modifiers.get("dex"), dexCap) + shieldBonus;

                int hpMax = level * (6 + modifiers.get("con"));

                Map<String, Object> result = new LinkedHashMap<>();
                result.put("level", level);
                result.put("proficiency_bonus", proficiencyBonus(level));
                result.put("hp_max", hpMax);
                result.put("armor_class", armorClass);
                result.put("modifiers", modifiers);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class InitiativeHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                List<Object> combatants = new ArrayList<>(Json.arr(body.get("combatants")));
                combatants.sort(new Comparator<Object>() {
                    public int compare(Object a, Object b) {
                        Map<String, Object> ca = Json.obj(a);
                        Map<String, Object> cb = Json.obj(b);
                        int scoreA = Json.num(ca.get("roll")) + Json.num(ca.get("dex"));
                        int scoreB = Json.num(cb.get("roll")) + Json.num(cb.get("dex"));
                        int cmp = Integer.compare(scoreB, scoreA);
                        if (cmp != 0) return cmp;
                        int dexA = Json.num(ca.get("dex"));
                        int dexB = Json.num(cb.get("dex"));
                        cmp = Integer.compare(dexB, dexA);
                        if (cmp != 0) return cmp;
                        return Json.str(ca.get("name")).compareTo(Json.str(cb.get("name")));
                    }
                });
                List<Map<String, Object>> order = new ArrayList<>();
                for (Object c : combatants) {
                    Map<String, Object> com = Json.obj(c);
                    Map<String, Object> entry = new LinkedHashMap<>();
                    entry.put("name", Json.str(com.get("name")));
                    entry.put("score", Json.num(com.get("roll")) + Json.num(com.get("dex")));
                    order.add(entry);
                }
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("order", order);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class Combatant {
        final String name;
        final int dex;
        final int score;

        Combatant(String name, int dex, int score) {
            this.name = name;
            this.dex = dex;
            this.score = score;
        }
    }

    static class Condition {
        final String condition;
        int remainingRounds;

        Condition(String condition, int remainingRounds) {
            this.condition = condition;
            this.remainingRounds = remainingRounds;
        }
    }

    static class CombatSession {
        final String id;
        final List<Combatant> order;
        final Map<String, List<Condition>> conditions = new HashMap<>();
        int round = 1;
        int turnIndex = 0;

        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.order = order;
        }

        CombatSession(String id, List<Combatant> order, int round, int turnIndex, Map<String, List<Condition>> conditions) {
            this.id = id;
            this.order = order;
            this.round = round;
            this.turnIndex = turnIndex;
            if (conditions != null) this.conditions.putAll(conditions);
        }

        Combatant active() {
            return order.get(turnIndex);
        }
    }

    static class CombatSessionsHandler implements HttpHandler {
        private final Pattern pathPattern = Pattern.compile("/v1/combat/sessions/([^/]+)/(conditions|advance)");

        public void handle(HttpExchange ex) throws IOException {
            String method = ex.getRequestMethod();
            String path = ex.getRequestURI().getPath();
            try {
                if ("POST".equals(method) && path.equals("/v1/combat/sessions")) {
                    createSession(ex);
                    return;
                }
                Matcher m = pathPattern.matcher(path);
                if (!m.matches()) {
                    sendJson(ex, 404, "{\"error\":\"not found\"}");
                    return;
                }
                String id = m.group(1);
                String action = m.group(2);
                if ("POST".equals(method) && "conditions".equals(action)) {
                    addCondition(ex, id);
                } else if ("POST".equals(method) && "advance".equals(action)) {
                    advanceTurn(ex, id);
                } else {
                    sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                }
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }

        private void createSession(HttpExchange ex) throws Exception {
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String id = Json.str(body.get("id"));
            List<Object> rawCombatants = Json.arr(body.get("combatants"));
            if (id == null || id.isEmpty() || rawCombatants.isEmpty()) {
                throw new RuntimeException("invalid request");
            }
            if (SQLiteStore.sessionExists(id)) {
                throw new RuntimeException("duplicate session id");
            }
            List<Combatant> order = new ArrayList<>();
            for (Object c : rawCombatants) {
                Map<String, Object> com = Json.obj(c);
                String name = Json.str(com.get("name"));
                int dex = Json.num(com.get("dex"));
                int roll = Json.num(com.get("roll"));
                order.add(new Combatant(name, dex, roll + dex));
            }
            order.sort(new Comparator<Combatant>() {
                public int compare(Combatant a, Combatant b) {
                    int cmp = Integer.compare(b.score, a.score);
                    if (cmp != 0) return cmp;
                    cmp = Integer.compare(b.dex, a.dex);
                    if (cmp != 0) return cmp;
                    return a.name.compareTo(b.name);
                }
            });
            SQLiteStore.insertSession(id, order);
            CombatSession session = SQLiteStore.loadSession(id);
            sendJson(ex, 200, Json.toJson(sessionResponse(session)));
        }

        private void addCondition(HttpExchange ex, String id) throws Exception {
            CombatSession session = SQLiteStore.loadSession(id);
            if (session == null) {
                sendJson(ex, 404, "{\"error\":\"session not found\"}");
                return;
            }
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String target = Json.str(body.get("target"));
            String conditionName = Json.str(body.get("condition"));
            int duration = Json.num(body.get("duration_rounds"));
            boolean found = false;
            for (Combatant c : session.order) {
                if (c.name.equals(target)) {
                    found = true;
                    break;
                }
            }
            if (!found || conditionName == null || duration <= 0) {
                throw new RuntimeException("invalid request");
            }
            SQLiteStore.addCondition(id, target, conditionName, duration);
            session = SQLiteStore.loadSession(id);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("target", target);
            result.put("conditions", conditionsList(session.conditions.get(target)));
            sendJson(ex, 200, Json.toJson(result));
        }

        private void advanceTurn(HttpExchange ex, String id) throws Exception {
            CombatSession session = SQLiteStore.loadSession(id);
            if (session == null) {
                sendJson(ex, 404, "{\"error\":\"session not found\"}");
                return;
            }
            session.turnIndex++;
            if (session.turnIndex >= session.order.size()) {
                session.turnIndex = 0;
                session.round++;
            }
            String activeName = session.active().name;
            List<Condition> activeConditions = session.conditions.get(activeName);
            if (activeConditions != null) {
                Iterator<Condition> it = activeConditions.iterator();
                while (it.hasNext()) {
                    Condition c = it.next();
                    c.remainingRounds--;
                    if (c.remainingRounds <= 0) {
                        it.remove();
                    }
                }
            }
            SQLiteStore.updateSessionStateAndConditions(session, activeName);
            sendJson(ex, 200, Json.toJson(advanceResponse(session)));
        }

        private Map<String, Object> sessionResponse(CombatSession session) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", session.id);
            result.put("round", session.round);
            result.put("turn_index", session.turnIndex);
            result.put("active", combatantMap(session.active()));
            List<Map<String, Object>> orderList = new ArrayList<>();
            for (Combatant c : session.order) {
                orderList.add(combatantMap(c));
            }
            result.put("order", orderList);
            return result;
        }

        private Map<String, Object> advanceResponse(CombatSession session) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", session.id);
            result.put("round", session.round);
            result.put("turn_index", session.turnIndex);
            result.put("active", combatantMap(session.active()));
            Map<String, Object> conditionsMap = new LinkedHashMap<>();
            for (Map.Entry<String, List<Condition>> e : session.conditions.entrySet()) {
                conditionsMap.put(e.getKey(), conditionsList(e.getValue()));
            }
            result.put("conditions", conditionsMap);
            return result;
        }

        private Map<String, Object> combatantMap(Combatant c) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", c.name);
            m.put("score", c.score);
            return m;
        }

        private List<Map<String, Object>> conditionsList(List<Condition> list) {
            List<Map<String, Object>> result = new ArrayList<>();
            if (list != null) {
                for (Condition c : list) {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("condition", c.condition);
                    m.put("remaining_rounds", c.remainingRounds);
                    result.add(m);
                }
            }
            return result;
        }
    }

    static class CampaignsHandler implements HttpHandler {
        private final Pattern campaignPattern = Pattern.compile("^/v1/campaigns/([^/]+)/(characters|events|state)$");

        public void handle(HttpExchange ex) throws IOException {
            String method = ex.getRequestMethod();
            String path = ex.getRequestURI().getPath();
            try {
                if ("POST".equals(method) && path.equals("/v1/campaigns")) {
                    createCampaign(ex);
                    return;
                }
                Matcher m = campaignPattern.matcher(path);
                if (!m.matches()) {
                    sendJson(ex, 404, "{\"error\":\"not found\"}");
                    return;
                }
                String id = m.group(1);
                String action = m.group(2);
                if ("POST".equals(method) && "characters".equals(action)) {
                    addCharacter(ex, id);
                } else if ("POST".equals(method) && "events".equals(action)) {
                    addEvent(ex, id);
                } else if ("GET".equals(method) && "state".equals(action)) {
                    getState(ex, id);
                } else {
                    sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                }
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }

        private void createCampaign(HttpExchange ex) throws Exception {
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String id = Json.str(body.get("id"));
            String name = Json.str(body.get("name"));
            String dm = Json.str(body.get("dm"));
            if (id == null || id.isEmpty() || name == null || name.isEmpty() || dm == null || dm.isEmpty()) {
                throw new RuntimeException("invalid request");
            }
            if (SQLiteStore.campaignExists(id)) {
                sendJson(ex, 409, "{\"error\":\"campaign already exists\"}");
                return;
            }
            SQLiteStore.insertCampaign(id, name, dm);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", id);
            result.put("name", name);
            result.put("dm", dm);
            sendJson(ex, 201, Json.toJson(result));
        }

        private void addCharacter(HttpExchange ex, String campaignId) throws Exception {
            if (!SQLiteStore.campaignExists(campaignId)) {
                sendJson(ex, 404, "{\"error\":\"campaign not found\"}");
                return;
            }
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String id = Json.str(body.get("id"));
            String name = Json.str(body.get("name"));
            int level = Json.num(body.get("level"));
            String className = Json.str(body.get("class"));
            if (id == null || id.isEmpty() || name == null || name.isEmpty() || className == null || className.isEmpty() || level < 1 || level > 20) {
                throw new RuntimeException("invalid request");
            }
            if (SQLiteStore.characterExists(id)) {
                sendJson(ex, 409, "{\"error\":\"character already exists\"}");
                return;
            }
            SQLiteStore.insertCharacter(id, campaignId, name, level, className);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", id);
            result.put("name", name);
            result.put("level", level);
            result.put("class", className);
            sendJson(ex, 201, Json.toJson(result));
        }

        private void addEvent(HttpExchange ex, String campaignId) throws Exception {
            if (!SQLiteStore.campaignExists(campaignId)) {
                sendJson(ex, 404, "{\"error\":\"campaign not found\"}");
                return;
            }
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String id = Json.str(body.get("id"));
            String kind = Json.str(body.get("kind"));
            String summary = Json.str(body.get("summary"));
            if (id == null || id.isEmpty() || kind == null || kind.isEmpty() || summary == null) {
                throw new RuntimeException("invalid request");
            }
            if (SQLiteStore.eventExists(id)) {
                sendJson(ex, 409, "{\"error\":\"event already exists\"}");
                return;
            }
            SQLiteStore.insertEvent(id, campaignId, kind, summary);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", id);
            result.put("kind", kind);
            sendJson(ex, 201, Json.toJson(result));
        }

        private void getState(HttpExchange ex, String id) throws Exception {
            Map<String, Object> state = SQLiteStore.getCampaignState(id);
            if (state == null) {
                sendJson(ex, 404, "{\"error\":\"campaign not found\"}");
                return;
            }
            sendJson(ex, 200, Json.toJson(state));
        }
    }

    static class User {
        final String username;
        final String role;
        final String salt;
        final String hash;

        User(String username, String role, String salt, String hash) {
            this.username = username;
            this.role = role;
            this.salt = salt;
            this.hash = hash;
        }
    }

    static class PasswordHash {
        private static final int ITERATIONS = 100_000;
        private static final int KEY_LENGTH = 256;
        private static final SecureRandom RANDOM = new SecureRandom();

        static String[] hash(String password) throws Exception {
            byte[] salt = new byte[16];
            RANDOM.nextBytes(salt);
            String saltB64 = Base64.getEncoder().encodeToString(salt);
            return new String[]{saltB64, hash(password, saltB64)};
        }

        static String hash(String password, String saltB64) throws Exception {
            byte[] salt = Base64.getDecoder().decode(saltB64);
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, KEY_LENGTH);
            SecretKeyFactory skf = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] hash = skf.generateSecret(spec).getEncoded();
            spec.clearPassword();
            return Base64.getEncoder().encodeToString(hash);
        }

        static boolean verify(String password, String saltB64, String hashB64) throws Exception {
            String computed = hash(password, saltB64);
            return MessageDigest.isEqual(Base64.getDecoder().decode(hashB64), Base64.getDecoder().decode(computed));
        }
    }

    static class RegisterHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String username = Json.str(body.get("username"));
                String password = Json.str(body.get("password"));
                String role = Json.str(body.get("role"));
                if (!username.matches("^[a-z0-9_-]{2,32}$") || password.length() < 8 || (!"dm".equals(role) && !"player".equals(role))) {
                    throw new RuntimeException("invalid request");
                }
                if (SQLiteStore.userExists(username)) {
                    sendJson(ex, 409, "{\"error\":\"username already exists\"}");
                    return;
                }
                String[] sh = PasswordHash.hash(password);
                SQLiteStore.insertUser(username, role, sh[0], sh[1]);
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("username", username);
                result.put("role", role);
                sendJson(ex, 201, Json.toJson(result));
            } catch (RuntimeException e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class LoginHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String username = Json.str(body.get("username"));
                String password = Json.str(body.get("password"));
                User user = SQLiteStore.getUser(username);
                if (user == null || !PasswordHash.verify(password, user.salt, user.hash)) {
                    sendJson(ex, 401, "{\"error\":\"invalid credentials\"}");
                    return;
                }
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("username", username);
                result.put("token", "session-" + username);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class StorageStatusHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"GET".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                boolean initialized = SQLiteStore.initialized();
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("driver", "sqlite");
                result.put("schema_version", 1);
                result.put("initialized", initialized);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 500, "{\"error\":\"storage error\"}");
            }
        }
    }

    static class StorageResetHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                SQLiteStore.reset();
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("ok", true);
                result.put("schema_version", 1);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 500, "{\"error\":\"storage error\"}");
            }
        }
    }

    static class SQLiteStore {
        private static final String DB = "game.db";
        private static final String SQLITE = "/usr/bin/sqlite3";

        static void init() throws Exception {
            execSql("PRAGMA foreign_keys=ON;" +
                "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT, salt TEXT, hash TEXT);" +
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, round INTEGER, turn_index INTEGER);" +
                "CREATE TABLE IF NOT EXISTS combatants (id INTEGER PRIMARY KEY, session_id TEXT, name TEXT, dex INTEGER, score INTEGER, sort_order INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);" +
                "CREATE TABLE IF NOT EXISTS conditions (id INTEGER PRIMARY KEY, session_id TEXT, target TEXT, condition TEXT, remaining_rounds INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);" +
                "CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER);" +
                "CREATE TABLE IF NOT EXISTS monster_tags (slug TEXT, tag TEXT, tag_order INTEGER, PRIMARY KEY (slug, tag_order), FOREIGN KEY(slug) REFERENCES monsters(slug) ON DELETE CASCADE);" +
                "CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT, type TEXT, rarity TEXT, cost_gp INTEGER);" +
                "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT, dm TEXT);" +
                "CREATE TABLE IF NOT EXISTS characters (id TEXT PRIMARY KEY, campaign_id TEXT, name TEXT, level INTEGER, class TEXT, sort_order INTEGER, FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE);" +
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, campaign_id TEXT, kind TEXT, summary TEXT, FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE);");
        }

        static void reset() throws Exception {
            execSql("PRAGMA foreign_keys=ON;" +
                "DROP TABLE IF EXISTS conditions;" +
                "DROP TABLE IF EXISTS combatants;" +
                "DROP TABLE IF EXISTS sessions;" +
                "DROP TABLE IF EXISTS users;" +
                "DROP TABLE IF EXISTS monster_tags;" +
                "DROP TABLE IF EXISTS monsters;" +
                "DROP TABLE IF EXISTS items;" +
                "DROP TABLE IF EXISTS events;" +
                "DROP TABLE IF EXISTS characters;" +
                "DROP TABLE IF EXISTS campaigns;" +
                "CREATE TABLE users (username TEXT PRIMARY KEY, role TEXT, salt TEXT, hash TEXT);" +
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, round INTEGER, turn_index INTEGER);" +
                "CREATE TABLE combatants (id INTEGER PRIMARY KEY, session_id TEXT, name TEXT, dex INTEGER, score INTEGER, sort_order INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);" +
                "CREATE TABLE conditions (id INTEGER PRIMARY KEY, session_id TEXT, target TEXT, condition TEXT, remaining_rounds INTEGER, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);" +
                "CREATE TABLE monsters (slug TEXT PRIMARY KEY, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER);" +
                "CREATE TABLE monster_tags (slug TEXT, tag TEXT, tag_order INTEGER, PRIMARY KEY (slug, tag_order), FOREIGN KEY(slug) REFERENCES monsters(slug) ON DELETE CASCADE);" +
                "CREATE TABLE items (slug TEXT PRIMARY KEY, name TEXT, type TEXT, rarity TEXT, cost_gp INTEGER);" +
                "CREATE TABLE campaigns (id TEXT PRIMARY KEY, name TEXT, dm TEXT);" +
                "CREATE TABLE characters (id TEXT PRIMARY KEY, campaign_id TEXT, name TEXT, level INTEGER, class TEXT, sort_order INTEGER, FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE);" +
                "CREATE TABLE events (id TEXT PRIMARY KEY, campaign_id TEXT, kind TEXT, summary TEXT, FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE);");
        }

        static boolean initialized() throws Exception {
            return !queryRows("SELECT 1 AS data FROM sqlite_master WHERE type='table' AND name='users'").isEmpty();
        }

        static boolean userExists(String username) throws Exception {
            return !queryRows("SELECT 1 AS data FROM users WHERE username = " + sqlEscape(username)).isEmpty();
        }

        static User getUser(String username) throws Exception {
            String json = queryJson("SELECT json_object('username', username, 'role', role, 'salt', salt, 'hash', hash) AS data FROM users WHERE username = " + sqlEscape(username));
            if (json == null) return null;
            Map<String, Object> m = Json.obj(new JsonParser(json).parse());
            return new User(Json.str(m.get("username")), Json.str(m.get("role")), Json.str(m.get("salt")), Json.str(m.get("hash")));
        }

        static void insertUser(String username, String role, String salt, String hash) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO users (username, role, salt, hash) VALUES (" +
                sqlEscape(username) + "," + sqlEscape(role) + "," + sqlEscape(salt) + "," + sqlEscape(hash) + ");");
        }

        static boolean sessionExists(String id) throws Exception {
            return !queryRows("SELECT 1 AS data FROM sessions WHERE id = " + sqlEscape(id)).isEmpty();
        }

        static void insertSession(String id, List<Combatant> order) throws Exception {
            StringBuilder sb = new StringBuilder();
            sb.append("PRAGMA foreign_keys=ON; BEGIN;");
            sb.append("INSERT INTO sessions (id, round, turn_index) VALUES (").append(sqlEscape(id)).append(",1,0);");
            for (int i = 0; i < order.size(); i++) {
                Combatant c = order.get(i);
                sb.append("INSERT INTO combatants (session_id, name, dex, score, sort_order) VALUES (").append(sqlEscape(id)).append(",").append(sqlEscape(c.name)).append(",").append(c.dex).append(",").append(c.score).append(",").append(i).append(");");
            }
            sb.append("COMMIT;");
            execSql(sb.toString());
        }

        static CombatSession loadSession(String id) throws Exception {
            String sql = "SELECT json_object('id', s.id, 'round', s.round, 'turn_index', s.turn_index, 'order', " +
                "(SELECT json_group_array(json_object('name', c.name, 'dex', c.dex, 'score', c.score)) FROM combatants c WHERE c.session_id = s.id ORDER BY c.sort_order), " +
                "'conditions', (SELECT json_group_array(json_object('target', c.target, 'condition', c.condition, 'remaining_rounds', c.remaining_rounds)) FROM conditions c WHERE c.session_id = s.id)) " +
                "AS data FROM sessions s WHERE s.id = " + sqlEscape(id);
            String json = queryJson(sql);
            if (json == null) return null;
            Map<String, Object> m = Json.obj(new JsonParser(json).parse());
            int round = Json.num(m.get("round"));
            int turnIndex = Json.num(m.get("turn_index"));
            List<Combatant> order = new ArrayList<>();
            for (Object o : Json.arr(m.get("order"))) {
                Map<String, Object> c = Json.obj(o);
                order.add(new Combatant(Json.str(c.get("name")), Json.num(c.get("dex")), Json.num(c.get("score"))));
            }
            Map<String, List<Condition>> conditions = new HashMap<>();
            for (Object o : Json.arr(m.get("conditions"))) {
                Map<String, Object> c = Json.obj(o);
                String target = Json.str(c.get("target"));
                conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(new Condition(Json.str(c.get("condition")), Json.num(c.get("remaining_rounds"))));
            }
            return new CombatSession(Json.str(m.get("id")), order, round, turnIndex, conditions);
        }

        static void addCondition(String sessionId, String target, String condition, int duration) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (" +
                sqlEscape(sessionId) + "," + sqlEscape(target) + "," + sqlEscape(condition) + "," + duration + ");");
        }

        static void updateSessionStateAndConditions(CombatSession session, String target) throws Exception {
            StringBuilder sb = new StringBuilder();
            sb.append("PRAGMA foreign_keys=ON; BEGIN;");
            sb.append("UPDATE sessions SET round=").append(session.round).append(", turn_index=").append(session.turnIndex).append(" WHERE id=").append(sqlEscape(session.id)).append(";");
            sb.append("DELETE FROM conditions WHERE session_id=").append(sqlEscape(session.id)).append(" AND target=").append(sqlEscape(target)).append(";");
            List<Condition> list = session.conditions.get(target);
            if (list != null) {
                for (Condition c : list) {
                    sb.append("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (").append(sqlEscape(session.id)).append(",").append(sqlEscape(target)).append(",").append(sqlEscape(c.condition)).append(",").append(c.remainingRounds).append(");");
                }
            }
            sb.append("COMMIT;");
            execSql(sb.toString());
        }

        static boolean monsterExists(String slug) throws Exception {
            return !queryRows("SELECT 1 AS data FROM monsters WHERE slug = " + sqlEscape(slug)).isEmpty();
        }

        static void insertMonster(String slug, String name, String cr, int armorClass, int hitPoints, List<String> tags) throws Exception {
            StringBuilder sb = new StringBuilder();
            sb.append("PRAGMA foreign_keys=ON; BEGIN;");
            sb.append("INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (").append(sqlEscape(slug)).append(",").append(sqlEscape(name)).append(",").append(sqlEscape(cr)).append(",").append(armorClass).append(",").append(hitPoints).append(");");
            for (int i = 0; i < tags.size(); i++) {
                sb.append("INSERT INTO monster_tags (slug, tag, tag_order) VALUES (").append(sqlEscape(slug)).append(",").append(sqlEscape(tags.get(i))).append(",").append(i).append(");");
            }
            sb.append("COMMIT;");
            execSql(sb.toString());
        }

        static Map<String, Object> getMonster(String slug) throws Exception {
            String sql = "SELECT json_object('slug', m.slug, 'name', m.name, 'cr', m.cr, 'armor_class', m.armor_class, 'hit_points', m.hit_points, 'tags', (SELECT json_group_array(tag) FROM monster_tags WHERE slug = m.slug ORDER BY tag_order)) AS data FROM monsters m WHERE m.slug = " + sqlEscape(slug);
            String json = queryJson(sql);
            if (json == null) return null;
            return Json.obj(new JsonParser(json).parse());
        }

        static boolean itemExists(String slug) throws Exception {
            return !queryRows("SELECT 1 AS data FROM items WHERE slug = " + sqlEscape(slug)).isEmpty();
        }

        static void insertItem(String slug, String name, String type, String rarity, int costGp) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (" + sqlEscape(slug) + "," + sqlEscape(name) + "," + sqlEscape(type) + "," + sqlEscape(rarity) + "," + costGp + ");");
        }

        static Map<String, Object> getItem(String slug) throws Exception {
            String sql = "SELECT json_object('slug', slug, 'name', name, 'type', type, 'rarity', rarity, 'cost_gp', cost_gp) AS data FROM items WHERE slug = " + sqlEscape(slug);
            String json = queryJson(sql);
            if (json == null) return null;
            return Json.obj(new JsonParser(json).parse());
        }

        static boolean campaignExists(String id) throws Exception {
            return !queryRows("SELECT 1 AS data FROM campaigns WHERE id = " + sqlEscape(id)).isEmpty();
        }

        static void insertCampaign(String id, String name, String dm) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO campaigns (id, name, dm) VALUES (" + sqlEscape(id) + "," + sqlEscape(name) + "," + sqlEscape(dm) + ");");
        }

        static boolean characterExists(String id) throws Exception {
            return !queryRows("SELECT 1 AS data FROM characters WHERE id = " + sqlEscape(id)).isEmpty();
        }

        static void insertCharacter(String id, String campaignId, String name, int level, String className) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO characters (id, campaign_id, name, level, class, sort_order) VALUES (" + sqlEscape(id) + "," + sqlEscape(campaignId) + "," + sqlEscape(name) + "," + level + "," + sqlEscape(className) + ", (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM characters WHERE campaign_id = " + sqlEscape(campaignId) + "));");
        }

        static boolean eventExists(String id) throws Exception {
            return !queryRows("SELECT 1 AS data FROM events WHERE id = " + sqlEscape(id)).isEmpty();
        }

        static void insertEvent(String id, String campaignId, String kind, String summary) throws Exception {
            execSql("PRAGMA foreign_keys=ON; INSERT INTO events (id, campaign_id, kind, summary) VALUES (" + sqlEscape(id) + "," + sqlEscape(campaignId) + "," + sqlEscape(kind) + "," + sqlEscape(summary) + ");");
        }

        static Map<String, Object> getCampaignState(String id) throws Exception {
            String sql = "SELECT json_object('id', id, 'name', name, 'dm', dm, 'characters', (SELECT json_group_array(json_object('id', id, 'name', name, 'level', level, 'class', class)) FROM characters WHERE campaign_id = campaigns.id ORDER BY sort_order), 'log_count', (SELECT COUNT(*) FROM events WHERE campaign_id = campaigns.id)) AS data FROM campaigns WHERE id = " + sqlEscape(id);
            String json = queryJson(sql);
            if (json == null) return null;
            return Json.obj(new JsonParser(json).parse());
        }

        static List<Map<String, Object>> getCampaignEvents(String campaignId) throws Exception {
            String sql = "SELECT json_object('id', id, 'kind', kind, 'summary', summary) AS data FROM events WHERE campaign_id = " + sqlEscape(campaignId) + " ORDER BY rowid";
            List<Object> rows = queryRows(sql);
            List<Map<String, Object>> events = new ArrayList<>();
            for (Object row : rows) {
                String json = Json.str(Json.obj(row).get("data"));
                events.add(Json.obj(new JsonParser(json).parse()));
            }
            return events;
        }

        private static String execSql(String sql) throws Exception {
            ProcessBuilder pb = new ProcessBuilder(SQLITE, "-json", "-batch", DB, sql);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String out = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            int code = p.waitFor();
            if (code != 0) throw new RuntimeException("sqlite error: " + out.trim());
            return out.trim();
        }

        private static List<Object> queryRows(String sql) throws Exception {
            String out = execSql(sql);
            if (out == null || out.isEmpty()) return Collections.emptyList();
            return Json.arr(new JsonParser(out).parse());
        }

        private static String queryJson(String sql) throws Exception {
            List<Object> rows = queryRows(sql);
            if (rows.isEmpty()) return null;
            return Json.str(Json.obj(rows.get(0)).get("data"));
        }

        private static String sqlEscape(String s) {
            return "'" + s.replace("'", "''") + "'";
        }
    }

    static class MonstersHandler implements HttpHandler {
        private final Pattern pathPattern = Pattern.compile("/v1/compendium/monsters/([^/]+)");

        public void handle(HttpExchange ex) throws IOException {
            String method = ex.getRequestMethod();
            String path = ex.getRequestURI().getPath();
            try {
                if ("POST".equals(method) && path.equals("/v1/compendium/monsters")) {
                    createMonster(ex);
                    return;
                }
                Matcher m = pathPattern.matcher(path);
                if (!m.matches()) {
                    sendJson(ex, 404, "{\"error\":\"not found\"}");
                    return;
                }
                String slug = m.group(1);
                if ("GET".equals(method)) {
                    getMonster(ex, slug);
                } else {
                    sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                }
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }

        private void createMonster(HttpExchange ex) throws Exception {
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String slug = Json.str(body.get("slug"));
            String name = Json.str(body.get("name"));
            String cr = Json.str(body.get("cr"));
            int armorClass = Json.num(body.get("armor_class"));
            int hitPoints = Json.num(body.get("hit_points"));
            List<Object> tagsRaw = Json.arr(body.get("tags"));
            if (slug == null || slug.isEmpty() || name == null || name.isEmpty() || cr == null || cr.isEmpty()) {
                throw new RuntimeException("invalid request");
            }
            List<String> tags = new ArrayList<>();
            for (Object t : tagsRaw) {
                tags.add(Json.str(t));
            }
            if (SQLiteStore.monsterExists(slug)) {
                sendJson(ex, 409, "{\"error\":\"monster already exists\"}");
                return;
            }
            SQLiteStore.insertMonster(slug, name, cr, armorClass, hitPoints, tags);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("slug", slug);
            result.put("name", name);
            result.put("cr", cr);
            result.put("armor_class", armorClass);
            result.put("hit_points", hitPoints);
            sendJson(ex, 201, Json.toJson(result));
        }

        private void getMonster(HttpExchange ex, String slug) throws Exception {
            Map<String, Object> monster = SQLiteStore.getMonster(slug);
            if (monster == null) {
                sendJson(ex, 404, "{\"error\":\"monster not found\"}");
                return;
            }
            sendJson(ex, 200, Json.toJson(monster));
        }
    }

    static class ItemsHandler implements HttpHandler {
        private final Pattern pathPattern = Pattern.compile("/v1/compendium/items/([^/]+)");

        public void handle(HttpExchange ex) throws IOException {
            String method = ex.getRequestMethod();
            String path = ex.getRequestURI().getPath();
            try {
                if ("POST".equals(method) && path.equals("/v1/compendium/items")) {
                    createItem(ex);
                    return;
                }
                Matcher m = pathPattern.matcher(path);
                if (!m.matches()) {
                    sendJson(ex, 404, "{\"error\":\"not found\"}");
                    return;
                }
                String slug = m.group(1);
                if ("GET".equals(method)) {
                    getItem(ex, slug);
                } else {
                    sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                }
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }

        private void createItem(HttpExchange ex) throws Exception {
            Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
            String slug = Json.str(body.get("slug"));
            String name = Json.str(body.get("name"));
            String type = Json.str(body.get("type"));
            String rarity = Json.str(body.get("rarity"));
            int costGp = Json.num(body.get("cost_gp"));
            if (slug == null || slug.isEmpty() || name == null || name.isEmpty() || type == null || type.isEmpty() || rarity == null || rarity.isEmpty()) {
                throw new RuntimeException("invalid request");
            }
            if (SQLiteStore.itemExists(slug)) {
                sendJson(ex, 409, "{\"error\":\"item already exists\"}");
                return;
            }
            SQLiteStore.insertItem(slug, name, type, rarity, costGp);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("slug", slug);
            result.put("name", name);
            result.put("type", type);
            result.put("rarity", rarity);
            result.put("cost_gp", costGp);
            sendJson(ex, 201, Json.toJson(result));
        }

        private void getItem(HttpExchange ex, String slug) throws Exception {
            Map<String, Object> item = SQLiteStore.getItem(slug);
            if (item == null) {
                sendJson(ex, 404, "{\"error\":\"item not found\"}");
                return;
            }
            sendJson(ex, 200, Json.toJson(item));
        }
    }

    static class DmEncounterHandler implements HttpHandler {
        private static final Map<String, Integer> XP = new HashMap<>();
        private static final Map<Integer, int[]> THRESHOLDS = new HashMap<>();

        static {
            XP.put("0", 10);
            XP.put("1/8", 25);
            XP.put("1/4", 50);
            XP.put("1/2", 100);
            XP.put("1", 200);
            XP.put("2", 450);
            XP.put("3", 700);
            XP.put("4", 1100);
            XP.put("5", 1800);
            XP.put("6", 2300);
            XP.put("7", 2900);
            XP.put("8", 3900);
            XP.put("9", 5000);
            XP.put("10", 5900);
            XP.put("11", 7200);
            XP.put("12", 8400);
            XP.put("13", 10000);
            XP.put("14", 11500);
            XP.put("15", 13000);
            XP.put("16", 15000);
            XP.put("17", 18000);
            XP.put("18", 20000);
            XP.put("19", 22000);
            XP.put("20", 25000);
            XP.put("21", 33000);
            XP.put("22", 41000);
            XP.put("23", 50000);
            XP.put("24", 62000);
            XP.put("25", 75000);
            XP.put("26", 90000);
            XP.put("27", 105000);
            XP.put("28", 120000);
            XP.put("29", 135000);
            XP.put("30", 155000);

            THRESHOLDS.put(1, new int[]{25, 50, 75, 100});
            THRESHOLDS.put(2, new int[]{50, 100, 150, 200});
            THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
            THRESHOLDS.put(4, new int[]{125, 250, 375, 500});
            THRESHOLDS.put(5, new int[]{250, 500, 750, 1100});
            THRESHOLDS.put(6, new int[]{300, 600, 900, 1400});
            THRESHOLDS.put(7, new int[]{350, 750, 1100, 1700});
            THRESHOLDS.put(8, new int[]{450, 900, 1400, 2100});
            THRESHOLDS.put(9, new int[]{550, 1100, 1600, 2400});
            THRESHOLDS.put(10, new int[]{600, 1200, 1900, 2800});
            THRESHOLDS.put(11, new int[]{800, 1600, 2400, 3600});
            THRESHOLDS.put(12, new int[]{1000, 2000, 3000, 4500});
            THRESHOLDS.put(13, new int[]{1100, 2200, 3400, 5100});
            THRESHOLDS.put(14, new int[]{1250, 2500, 3800, 5700});
            THRESHOLDS.put(15, new int[]{1400, 2800, 4300, 6400});
            THRESHOLDS.put(16, new int[]{1600, 3200, 4800, 7200});
            THRESHOLDS.put(17, new int[]{2000, 3900, 5900, 8800});
            THRESHOLDS.put(18, new int[]{2100, 4200, 6300, 9500});
            THRESHOLDS.put(19, new int[]{2400, 4900, 7300, 10900});
            THRESHOLDS.put(20, new int[]{2800, 5700, 8500, 12700});
        }

        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String campaignId = Json.str(body.get("campaign_id"));
                List<Object> party = Json.arr(body.get("party"));
                List<Object> monsterSlugs = Json.arr(body.get("monster_slugs"));
                if (campaignId == null || campaignId.isEmpty() || party.isEmpty()) {
                    throw new RuntimeException("invalid request");
                }

                int baseXp = 0;
                int monsterCount = 0;
                for (Object slugObj : monsterSlugs) {
                    String slug = Json.str(slugObj);
                    Map<String, Object> monster = SQLiteStore.getMonster(slug);
                    if (monster == null) throw new RuntimeException("monster not found");
                    String cr = Json.str(monster.get("cr"));
                    Integer xp = XP.get(cr);
                    if (xp == null) throw new RuntimeException("unsupported cr");
                    baseXp += xp;
                    monsterCount++;
                }

                double multiplier;
                if (monsterCount == 1) multiplier = 1;
                else if (monsterCount == 2) multiplier = 1.5;
                else if (monsterCount <= 6) multiplier = 2;
                else if (monsterCount <= 10) multiplier = 2.5;
                else if (monsterCount <= 14) multiplier = 3;
                else multiplier = 4;

                int adjustedXp = (int) (baseXp * multiplier);

                int easy = 0, medium = 0, hard = 0, deadly = 0;
                for (Object p : party) {
                    Map<String, Object> member = Json.obj(p);
                    int level = Json.num(member.get("level"));
                    int[] t = THRESHOLDS.get(level);
                    if (t == null) throw new RuntimeException("unsupported level");
                    easy += t[0];
                    medium += t[1];
                    hard += t[2];
                    deadly += t[3];
                }

                String difficulty;
                if (adjustedXp >= deadly) difficulty = "deadly";
                else if (adjustedXp >= hard) difficulty = "hard";
                else if (adjustedXp >= medium) difficulty = "medium";
                else if (adjustedXp >= easy) difficulty = "easy";
                else difficulty = "trivial";

                String recommendation;
                if ("trivial".equals(difficulty)) recommendation = "no challenge";
                else if ("easy".equals(difficulty)) recommendation = "safe warm-up";
                else if ("medium".equals(difficulty)) recommendation = "balanced fight";
                else if ("hard".equals(difficulty)) recommendation = "tense encounter";
                else recommendation = "deadly challenge";

                Map<String, Object> result = new LinkedHashMap<>();
                result.put("campaign_id", campaignId);
                result.put("base_xp", baseXp);
                result.put("adjusted_xp", adjustedXp);
                result.put("difficulty", difficulty);
                result.put("monster_count", monsterCount);
                result.put("recommendation", recommendation);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class DmLootHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String campaignId = Json.str(body.get("campaign_id"));
                int tier = Json.num(body.get("tier"));
                if (campaignId == null || campaignId.isEmpty() || tier != 1) {
                    throw new RuntimeException("invalid request");
                }
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("campaign_id", campaignId);
                result.put("coins_gp", 75);
                List<Map<String, Object>> items = new ArrayList<>();
                Map<String, Object> potion = new LinkedHashMap<>();
                potion.put("slug", "healing-potion");
                potion.put("quantity", 2);
                items.add(potion);
                result.put("items", items);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class DmSessionRecapHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String campaignId = Json.str(body.get("campaign_id"));
                if (campaignId == null || campaignId.isEmpty()) {
                    throw new RuntimeException("invalid request");
                }
                if (!SQLiteStore.campaignExists(campaignId)) {
                    sendJson(ex, 404, "{\"error\":\"campaign not found\"}");
                    return;
                }
                Map<String, Object> state = SQLiteStore.getCampaignState(campaignId);
                List<Object> characters = Json.arr(state.get("characters"));
                String firstName = characters.isEmpty() ? "Party" : Json.str(Json.obj(characters.get(0)).get("name"));

                List<Map<String, Object>> events = SQLiteStore.getCampaignEvents(campaignId);
                String summary = null;
                boolean summaryFromNote = false;
                List<String> openThreads = new ArrayList<>();
                for (Object eventObj : events) {
                    Map<String, Object> event = Json.obj(eventObj);
                    String kind = Json.str(event.get("kind"));
                    String eventSummary = Json.str(event.get("summary"));
                    if ("note".equals(kind) || "exploration".equals(kind)) {
                        summary = eventSummary;
                        summaryFromNote = true;
                    } else if ("combat".equals(kind) || "hook".equals(kind)) {
                        openThreads.add("Resolve " + eventSummary);
                    }
                }
                if (summary == null) {
                    summary = firstName + " prepares for the next session.";
                }
                if (openThreads.isEmpty() && summaryFromNote) {
                    String thread = deriveThread(summary);
                    if (thread != null) {
                        openThreads.add(thread);
                    }
                }

                Map<String, Object> result = new LinkedHashMap<>();
                result.put("campaign_id", campaignId);
                result.put("summary", summary);
                result.put("open_threads", openThreads);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }

        private static String deriveThread(String summary) {
            int idx = summary.toLowerCase().lastIndexOf("the ");
            if (idx < 0) return null;
            String noun = summary.substring(idx + 4).trim();
            if (noun.isEmpty()) return null;
            noun = noun.replaceAll("[.!?]+$", "");
            if (noun.isEmpty()) return null;
            return "Resolve " + noun + " ambush";
        }
    }

    static class SpellSlotsHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                String className = Json.str(body.get("class"));
                int level = Json.num(body.get("level"));
                if (!"wizard".equals(className) || level != 5) {
                    throw new RuntimeException("unsupported");
                }
                Map<String, Object> slots = new LinkedHashMap<>();
                slots.put("1", 4);
                slots.put("2", 3);
                slots.put("3", 2);
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("class", "wizard");
                result.put("level", 5);
                result.put("slots", slots);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class LongRestHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int level = Json.num(body.get("level"));
                int hpCurrent = Json.num(body.get("hp_current"));
                int hpMax = Json.num(body.get("hp_max"));
                int hitDiceSpent = Json.num(body.get("hit_dice_spent"));
                int exhaustionLevel = Json.num(body.get("exhaustion_level"));
                if (level < 1 || hpCurrent < 0 || hpMax < 1 || hitDiceSpent < 0 || exhaustionLevel < 0 || hpCurrent > hpMax) {
                    throw new RuntimeException("invalid request");
                }
                int restored = Math.max(1, level / 2);
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("hp_current", hpMax);
                result.put("hit_dice_spent", Math.max(0, hitDiceSpent - restored));
                result.put("exhaustion_level", Math.max(0, exhaustionLevel - 1));
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class EquipmentLoadHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!"POST".equals(ex.getRequestMethod())) {
                sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Map<String, Object> body = Json.obj(new JsonParser(readBody(ex)).parse());
                int strength = Json.num(body.get("strength"));
                int weight = Json.num(body.get("weight"));
                if (strength < 0 || weight < 0) {
                    throw new RuntimeException("invalid request");
                }
                int capacity = strength * 15;
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("capacity", capacity);
                result.put("weight", weight);
                result.put("encumbered", weight > capacity);
                sendJson(ex, 200, Json.toJson(result));
            } catch (Exception e) {
                sendJson(ex, 400, "{\"error\":\"invalid request\"}");
            }
        }
    }

    static class Json {
        @SuppressWarnings("unchecked")
        static Map<String, Object> obj(Object o) {
            return (Map<String, Object>) o;
        }

        @SuppressWarnings("unchecked")
        static List<Object> arr(Object o) {
            return (List<Object>) o;
        }

        static int num(Object o) {
            return (Integer) o;
        }

        static String str(Object o) {
            return (String) o;
        }

        static String toJson(Object o) {
            if (o == null) return "null";
            if (o instanceof Boolean) return o.toString();
            if (o instanceof Integer) return o.toString();
            if (o instanceof Double) {
                double d = (Double) o;
                if (d == Math.floor(d) && d >= Long.MIN_VALUE && d <= Long.MAX_VALUE) {
                    return String.valueOf((long) d);
                }
                return Double.toString(d);
            }
            if (o instanceof String) return "\"" + escape((String) o) + "\"";
            if (o instanceof List) {
                List<?> list = (List<?>) o;
                StringBuilder sb = new StringBuilder();
                sb.append('[');
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) sb.append(',');
                    sb.append(toJson(list.get(i)));
                }
                sb.append(']');
                return sb.toString();
            }
            if (o instanceof Map) {
                Map<?, ?> map = (Map<?, ?>) o;
                StringBuilder sb = new StringBuilder();
                sb.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> e : map.entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    sb.append('"').append(escape(String.valueOf(e.getKey()))).append("\":");
                    sb.append(toJson(e.getValue()));
                }
                sb.append('}');
                return sb.toString();
            }
            throw new RuntimeException("Unsupported JSON type: " + o.getClass());
        }

        static String escape(String s) {
            StringBuilder sb = new StringBuilder();
            for (char c : s.toCharArray()) {
                switch (c) {
                    case '"': sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\b': sb.append("\\b"); break;
                    case '\f': sb.append("\\f"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            return sb.toString();
        }
    }

    static class JsonParser {
        private final String s;
        private int i;

        JsonParser(String s) {
            this.s = s;
            this.i = 0;
        }

        Object parse() {
            skipWhitespace();
            Object value = parseValue();
            skipWhitespace();
            if (i != s.length()) throw new RuntimeException("Unexpected trailing data");
            return value;
        }

        private void skipWhitespace() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
        }

        private Object parseValue() {
            skipWhitespace();
            char c = s.charAt(i);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBoolean();
            if (c == 'n') return parseNull();
            if (c == '-' || Character.isDigit(c)) return parseNumber();
            throw new RuntimeException("Unexpected char: " + c);
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new LinkedHashMap<>();
            i++; // {
            skipWhitespace();
            if (peek() == '}') { i++; return map; }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                Object value = parseValue();
                map.put(key, value);
                skipWhitespace();
                char c = s.charAt(i++);
                if (c == '}') break;
                if (c != ',') throw new RuntimeException("Expected , or }");
            }
            return map;
        }

        private List<Object> parseArray() {
            List<Object> list = new ArrayList<>();
            i++; // [
            skipWhitespace();
            if (peek() == ']') { i++; return list; }
            while (true) {
                Object value = parseValue();
                list.add(value);
                skipWhitespace();
                char c = s.charAt(i++);
                if (c == ']') break;
                if (c != ',') throw new RuntimeException("Expected , or ]");
            }
            return list;
        }

        private String parseString() {
            i++; // "
            StringBuilder sb = new StringBuilder();
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    char esc = s.charAt(i++);
                    switch (esc) {
                        case '"': case '\\': case '/': sb.append(esc); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u':
                            int code = Integer.parseInt(s.substring(i, i + 4), 16);
                            sb.append((char) code);
                            i += 4;
                            break;
                        default: throw new RuntimeException("Bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Integer parseNumber() {
            int start = i;
            if (peek() == '-') i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            return Integer.parseInt(s.substring(start, i));
        }

        private Boolean parseBoolean() {
            if (s.startsWith("true", i)) { i += 4; return true; }
            if (s.startsWith("false", i)) { i += 5; return false; }
            throw new RuntimeException("Bad boolean");
        }

        private Object parseNull() {
            if (s.startsWith("null", i)) { i += 4; return null; }
            throw new RuntimeException("Bad null");
        }

        private char peek() {
            return s.charAt(i);
        }

        private void expect(char c) {
            skipWhitespace();
            if (s.charAt(i++) != c) throw new RuntimeException("Expected " + c);
        }
    }
}
