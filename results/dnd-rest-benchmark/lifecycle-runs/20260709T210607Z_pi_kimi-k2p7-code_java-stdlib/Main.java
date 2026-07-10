import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    private static final Map<String, Integer> CR_XP = new HashMap<>();
    private static final int[][] THRESHOLDS = new int[4][4]; // level 3 thresholds

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

        THRESHOLDS[3][0] = 75;  // easy
        THRESHOLDS[3][1] = 150; // medium
        THRESHOLDS[3][2] = 225; // hard
        THRESHOLDS[3][3] = 400; // deadly
    }

    private static final Map<String, CombatSession> SESSIONS = new HashMap<>();

    public static void main(String[] args) throws Exception {
        String portStr = System.getenv("PORT");
        if (portStr == null || portStr.isEmpty()) {
            System.err.println("PORT environment variable not set");
            System.exit(1);
        }
        int port = Integer.parseInt(portStr);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", Main::handleHealth);
        server.createContext("/v1/dice/stats", Main::handleDiceStats);
        server.createContext("/v1/checks/ability", Main::handleAbilityCheck);
        server.createContext("/v1/encounters/adjusted-xp", Main::handleAdjustedXp);
        server.createContext("/v1/initiative/order", Main::handleInitiative);
        server.createContext("/v1/combat/sessions", Main::handleCreateCombatSession);
        server.createContext("/v1/combat/sessions/", Main::handleCombatSessionSub);
        server.createContext("/v1/characters/ability-modifier", Main::handleAbilityModifier);
        server.createContext("/v1/characters/proficiency", Main::handleProficiency);
        server.createContext("/v1/characters/derived-stats", Main::handleDerivedStats);
        server.setExecutor(null);
        server.start();
        Thread.currentThread().join();
    }

    private static void handleHealth(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        sendJson(exchange, 200, "{\"ok\":true}");
    }

    private static void handleDiceStats(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            String expression = body.getString("expression").trim();
            Pattern pattern = Pattern.compile("^(\\d+)d(\\d+)(?:\\+(\\d+)|-(\\d+))?$");
            Matcher matcher = pattern.matcher(expression);
            if (!matcher.matches()) {
                sendError(exchange, 400, "Invalid expression");
                return;
            }
            int count = Integer.parseInt(matcher.group(1));
            int sides = Integer.parseInt(matcher.group(2));
            int modifier = 0;
            if (matcher.group(3) != null) {
                modifier = Integer.parseInt(matcher.group(3));
            } else if (matcher.group(4) != null) {
                modifier = -Integer.parseInt(matcher.group(4));
            }
            if (count <= 0 || sides <= 0) {
                sendError(exchange, 400, "Invalid expression");
                return;
            }
            int min = count + modifier;
            int max = count * sides + modifier;
            double average = (min + max) / 2.0;
            StringBuilder sb = new StringBuilder();
            sb.append("{\"dice_count\":").append(count)
              .append(",\"sides\":").append(sides)
              .append(",\"modifier\":").append(modifier)
              .append(",\"min\":").append(min)
              .append(",\"max\":").append(max)
              .append(",\"average\":").append(formatNumber(average))
              .append("}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleAbilityCheck(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            int roll = body.getInt("roll");
            int modifier = body.getInt("modifier");
            int dc = body.getInt("dc");
            int total = roll + modifier;
            boolean success = total >= dc;
            int margin = total - dc;
            StringBuilder sb = new StringBuilder();
            sb.append("{\"total\":").append(total)
              .append(",\"success\":").append(success)
              .append(",\"margin\":").append(margin)
              .append("}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleAdjustedXp(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            JsonArray party = body.getArray("party");
            JsonArray monsters = body.getArray("monsters");

            int easy = 0, medium = 0, hard = 0, deadly = 0;
            for (JsonValue p : party.getValues()) {
                int level = p.asObject().getInt("level");
                if (level < 0 || level >= THRESHOLDS.length) {
                    throw new IllegalArgumentException("Unsupported level");
                }
                easy += THRESHOLDS[level][0];
                medium += THRESHOLDS[level][1];
                hard += THRESHOLDS[level][2];
                deadly += THRESHOLDS[level][3];
            }

            int baseXp = 0;
            int monsterCount = 0;
            for (JsonValue m : monsters.getValues()) {
                JsonObject monster = m.asObject();
                String cr = monster.getString("cr");
                int count = monster.getInt("count");
                Integer xp = CR_XP.get(cr);
                if (xp == null) {
                    throw new IllegalArgumentException("Unsupported CR");
                }
                baseXp += xp * count;
                monsterCount += count;
            }

            double multiplier = getMultiplier(monsterCount);
            long adjustedXp = Math.round(baseXp * multiplier);

            String difficulty = "trivial";
            if (adjustedXp >= deadly) difficulty = "deadly";
            else if (adjustedXp >= hard) difficulty = "hard";
            else if (adjustedXp >= medium) difficulty = "medium";
            else if (adjustedXp >= easy) difficulty = "easy";

            StringBuilder sb = new StringBuilder();
            sb.append("{\"base_xp\":").append(baseXp)
              .append(",\"monster_count\":").append(monsterCount)
              .append(",\"multiplier\":").append(formatNumber(multiplier))
              .append(",\"adjusted_xp\":").append(adjustedXp)
              .append(",\"difficulty\":").append(Json.escape(difficulty))
              .append(",\"thresholds\":{\"easy\":").append(easy)
              .append(",\"medium\":").append(medium)
              .append(",\"hard\":").append(hard)
              .append(",\"deadly\":").append(deadly)
              .append("}}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static double getMultiplier(int count) {
        if (count == 1) return 1.0;
        if (count == 2) return 1.5;
        if (count >= 3 && count <= 6) return 2.0;
        if (count >= 7 && count <= 10) return 2.5;
        if (count >= 11 && count <= 14) return 3.0;
        return 4.0;
    }

    private static String formatNumber(double d) {
        if (d == Math.floor(d)) {
            return String.valueOf((long) d);
        }
        return String.valueOf(d);
    }

    private static void handleInitiative(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            JsonArray combatants = body.getArray("combatants");
            List<Combatant> list = new ArrayList<>();
            for (JsonValue c : combatants.getValues()) {
                JsonObject obj = c.asObject();
                String name = obj.getString("name");
                int dex = obj.getInt("dex");
                int roll = obj.getInt("roll");
                list.add(new Combatant(name, dex, roll + dex));
            }
            list.sort((a, b) -> {
                if (b.score != a.score) return Integer.compare(b.score, a.score);
                if (b.dex != a.dex) return Integer.compare(b.dex, a.dex);
                return a.name.compareTo(b.name);
            });
            StringBuilder sb = new StringBuilder();
            sb.append("{\"order\":[");
            for (int i = 0; i < list.size(); i++) {
                Combatant c = list.get(i);
                if (i > 0) sb.append(",");
                sb.append("{\"name\":").append(Json.escape(c.name))
                  .append(",\"score\":").append(c.score)
                  .append("}");
            }
            sb.append("]}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static int abilityModifier(int score) {
        if (score < 1 || score > 30) {
            throw new IllegalArgumentException("Invalid score");
        }
        return Math.floorDiv(score - 10, 2);
    }

    private static int proficiencyBonus(int level) {
        if (level < 1 || level > 20) {
            throw new IllegalArgumentException("Invalid level");
        }
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    private static void handleAbilityModifier(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            int score = body.getInt("score");
            int modifier = abilityModifier(score);
            StringBuilder sb = new StringBuilder();
            sb.append("{\"score\":").append(score)
              .append(",\"modifier\":").append(modifier)
              .append("}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleProficiency(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            int level = body.getInt("level");
            int bonus = proficiencyBonus(level);
            StringBuilder sb = new StringBuilder();
            sb.append("{\"level\":").append(level)
              .append(",\"proficiency_bonus\":").append(bonus)
              .append("}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleDerivedStats(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            int level = body.getInt("level");
            int proficiency = proficiencyBonus(level);
            JsonObject abilities = body.getObject("abilities");
            int strMod = abilityModifier(abilities.getInt("str"));
            int dexMod = abilityModifier(abilities.getInt("dex"));
            int conMod = abilityModifier(abilities.getInt("con"));
            int intMod = abilityModifier(abilities.getInt("int"));
            int wisMod = abilityModifier(abilities.getInt("wis"));
            int chaMod = abilityModifier(abilities.getInt("cha"));
            int hpMax = level * (6 + conMod);
            JsonObject armor = body.getObject("armor");
            int base = armor.getInt("base");
            boolean shield = armor.getBool("shield");
            int dexCap = armor.getInt("dex_cap");
            int shieldBonus = shield ? 2 : 0;
            int armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;
            StringBuilder sb = new StringBuilder();
            sb.append("{\"level\":").append(level)
              .append(",\"proficiency_bonus\":").append(proficiency)
              .append(",\"hp_max\":").append(hpMax)
              .append(",\"armor_class\":").append(armorClass)
              .append(",\"modifiers\":{")
              .append("\"str\":").append(strMod)
              .append(",\"dex\":").append(dexMod)
              .append(",\"con\":").append(conMod)
              .append(",\"int\":").append(intMod)
              .append(",\"wis\":").append(wisMod)
              .append(",\"cha\":").append(chaMod)
              .append("}}");
            sendJson(exchange, 200, sb.toString());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleCreateCombatSession(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            String id = body.getString("id");
            if (SESSIONS.containsKey(id)) {
                throw new IllegalArgumentException("Session already exists");
            }
            JsonArray combatants = body.getArray("combatants");
            List<Combatant> list = new ArrayList<>();
            for (JsonValue c : combatants.getValues()) {
                JsonObject obj = c.asObject();
                String name = obj.getString("name");
                int dex = obj.getInt("dex");
                int roll = obj.getInt("roll");
                list.add(new Combatant(name, dex, roll + dex));
            }
            if (list.isEmpty()) {
                throw new IllegalArgumentException("No combatants");
            }
            list.sort((a, b) -> {
                if (b.score != a.score) return Integer.compare(b.score, a.score);
                if (b.dex != a.dex) return Integer.compare(b.dex, a.dex);
                return a.name.compareTo(b.name);
            });
            CombatSession session = new CombatSession(id, list);
            SESSIONS.put(id, session);
            sendJson(exchange, 200, buildCombatSessionResponse(session, false));
        } catch (IllegalArgumentException e) {
            sendError(exchange, 400, e.getMessage());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleCombatSessionSub(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/combat/sessions/";
        if (!path.startsWith(prefix)) {
            sendError(exchange, 404, "Not Found");
            return;
        }
        String rest = path.substring(prefix.length());
        int slash = rest.indexOf('/');
        if (slash < 0) {
            sendError(exchange, 404, "Not Found");
            return;
        }
        String id = rest.substring(0, slash);
        String action = rest.substring(slash + 1);
        CombatSession session = SESSIONS.get(id);
        if (session == null) {
            sendError(exchange, 404, "Session not found");
            return;
        }
        if ("conditions".equals(action)) {
            handleAddCondition(exchange, session);
        } else if ("advance".equals(action)) {
            handleAdvanceTurn(exchange, session);
        } else {
            sendError(exchange, 404, "Not Found");
        }
    }

    private static void handleAddCondition(HttpExchange exchange, CombatSession session) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            JsonObject body = Json.parse(readBody(exchange)).asObject();
            String target = body.getString("target");
            String condition = body.getString("condition");
            int duration = body.getInt("duration_rounds");
            if (duration <= 0) {
                throw new IllegalArgumentException("duration_rounds must be positive");
            }
            boolean found = false;
            for (Combatant c : session.order) {
                if (c.name.equals(target)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                throw new IllegalArgumentException("Unknown target");
            }
            session.conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(new Condition(condition, duration));
            sendJson(exchange, 200, buildConditionResponse(target, session.conditions.get(target)));
        } catch (IllegalArgumentException e) {
            sendError(exchange, 400, e.getMessage());
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static void handleAdvanceTurn(HttpExchange exchange, CombatSession session) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            sendError(exchange, 405, "Method Not Allowed");
            return;
        }
        try {
            session.turnIndex++;
            if (session.turnIndex >= session.order.size()) {
                session.turnIndex = 0;
                session.round++;
            }
            Combatant active = session.order.get(session.turnIndex);
            List<Condition> activeConditions = session.conditions.get(active.name);
            if (activeConditions != null) {
                activeConditions.removeIf(c -> {
                    c.remainingRounds--;
                    return c.remainingRounds <= 0;
                });
                // Keep the target key even when its condition list becomes empty,
                // so previously-targeted combatants are still present in the response.
            }
            sendJson(exchange, 200, buildCombatSessionResponse(session, true));
        } catch (Exception e) {
            sendError(exchange, 400, "Bad Request");
        }
    }

    private static String buildCombatSessionResponse(CombatSession session, boolean includeConditions) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"id\":").append(Json.escape(session.id))
          .append(",\"round\":").append(session.round)
          .append(",\"turn_index\":").append(session.turnIndex)
          .append(",\"active\":").append(buildCombatantJson(session.order.get(session.turnIndex)))
          .append(",\"order\":[");
        for (int i = 0; i < session.order.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(buildCombatantJson(session.order.get(i)));
        }
        sb.append("]");
        if (includeConditions) {
            sb.append(",\"conditions\":{");
            boolean first = true;
            for (Map.Entry<String, List<Condition>> entry : session.conditions.entrySet()) {
                if (!first) sb.append(",");
                first = false;
                sb.append(Json.escape(entry.getKey())).append(":[");
                List<Condition> list = entry.getValue();
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) sb.append(",");
                    sb.append("{\"condition\":").append(Json.escape(list.get(i).condition))
                      .append(",\"remaining_rounds\":").append(list.get(i).remainingRounds)
                      .append("}");
                }
                sb.append("]");
            }
            sb.append("}");
        }
        sb.append("}");
        return sb.toString();
    }

    private static String buildCombatantJson(Combatant c) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"name\":").append(Json.escape(c.name))
          .append(",\"score\":").append(c.score)
          .append("}");
        return sb.toString();
    }

    private static String buildConditionResponse(String target, List<Condition> conditions) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"target\":").append(Json.escape(target)).append(",\"conditions\":[");
        for (int i = 0; i < conditions.size(); i++) {
            if (i > 0) sb.append(",");
            Condition c = conditions.get(i);
            sb.append("{\"condition\":").append(Json.escape(c.condition))
              .append(",\"remaining_rounds\":").append(c.remainingRounds)
              .append("}");
        }
        sb.append("]}");
        return sb.toString();
    }

    private static String readBody(HttpExchange exchange) throws IOException {
        return new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    }

    private static void sendJson(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static void sendError(HttpExchange exchange, int status, String message) throws IOException {
        sendJson(exchange, status, "{\"error\":" + Json.escape(message) + "}");
    }

    private static class Combatant {
        final String name;
        final int dex;
        final int score;

        Combatant(String name, int dex, int score) {
            this.name = name;
            this.dex = dex;
            this.score = score;
        }
    }

    private static class CombatSession {
        final String id;
        int round;
        int turnIndex;
        final List<Combatant> order;
        final Map<String, List<Condition>> conditions;

        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.round = 1;
            this.turnIndex = 0;
            this.order = order;
            this.conditions = new TreeMap<>();
        }
    }

    private static class Condition {
        final String condition;
        int remainingRounds;

        Condition(String condition, int remainingRounds) {
            this.condition = condition;
            this.remainingRounds = remainingRounds;
        }
    }

    // Minimal JSON parser/serializer for the shapes used by this API.
    static class Json {
        static String escape(String s) {
            StringBuilder sb = new StringBuilder();
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
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
            sb.append('"');
            return sb.toString();
        }

        static JsonValue parse(String s) {
            Parser p = new Parser(s);
            JsonValue v = p.parseValue();
            p.skipWhitespace();
            if (p.pos != p.length) throw new RuntimeException("Trailing data");
            return v;
        }

        static class Parser {
            final String s;
            int pos;
            final int length;

            Parser(String s) {
                this.s = s;
                this.length = s.length();
            }

            void skipWhitespace() {
                while (pos < length && Character.isWhitespace(s.charAt(pos))) pos++;
            }

            char peek() {
                skipWhitespace();
                if (pos >= length) throw new RuntimeException("Unexpected end of input");
                return s.charAt(pos);
            }

            JsonValue parseValue() {
                skipWhitespace();
                if (pos >= length) throw new RuntimeException("Unexpected end of input");
                char c = s.charAt(pos);
                switch (c) {
                    case '{': return parseObject();
                    case '[': return parseArray();
                    case '"': return parseString();
                    case 't': return parseLiteral("true", new JsonBool(true));
                    case 'f': return parseLiteral("false", new JsonBool(false));
                    case 'n': return parseLiteral("null", new JsonNull());
                    default: return parseNumber();
                }
            }

            JsonObject parseObject() {
                pos++; // {
                Map<String, JsonValue> map = new LinkedHashMap<>();
                skipWhitespace();
                if (peek() == '}') {
                    pos++;
                    return new JsonObject(map);
                }
                while (true) {
                    skipWhitespace();
                    String key = parseString().asString();
                    skipWhitespace();
                    if (pos >= length || s.charAt(pos) != ':') throw new RuntimeException("Expected ':'");
                    pos++;
                    JsonValue value = parseValue();
                    map.put(key, value);
                    skipWhitespace();
                    if (pos >= length) throw new RuntimeException("Expected ',' or '}'");
                    char c = s.charAt(pos++);
                    if (c == '}') break;
                    if (c != ',') throw new RuntimeException("Expected ',' or '}'");
                }
                return new JsonObject(map);
            }

            JsonArray parseArray() {
                pos++; // [
                List<JsonValue> list = new ArrayList<>();
                skipWhitespace();
                if (peek() == ']') {
                    pos++;
                    return new JsonArray(list);
                }
                while (true) {
                    JsonValue value = parseValue();
                    list.add(value);
                    skipWhitespace();
                    if (pos >= length) throw new RuntimeException("Expected ',' or ']'");
                    char c = s.charAt(pos++);
                    if (c == ']') break;
                    if (c != ',') throw new RuntimeException("Expected ',' or ']'");
                }
                return new JsonArray(list);
            }

            JsonString parseString() {
                if (s.charAt(pos) != '"') throw new RuntimeException("Expected string");
                pos++;
                StringBuilder sb = new StringBuilder();
                while (pos < length) {
                    char c = s.charAt(pos++);
                    if (c == '"') break;
                    if (c == '\\') {
                        if (pos >= length) throw new RuntimeException("Invalid escape");
                        char esc = s.charAt(pos++);
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
                                if (pos + 4 > length) throw new RuntimeException("Invalid unicode escape");
                                String hex = s.substring(pos, pos + 4);
                                sb.append((char) Integer.parseInt(hex, 16));
                                pos += 4;
                                break;
                            default: throw new RuntimeException("Invalid escape");
                        }
                    } else {
                        sb.append(c);
                    }
                }
                return new JsonString(sb.toString());
            }

            JsonValue parseLiteral(String literal, JsonValue value) {
                if (s.startsWith(literal, pos)) {
                    pos += literal.length();
                    return value;
                }
                throw new RuntimeException("Expected " + literal);
            }

            JsonNumber parseNumber() {
                int start = pos;
                if (s.charAt(pos) == '-') pos++;
                while (pos < length && Character.isDigit(s.charAt(pos))) pos++;
                if (pos < length && s.charAt(pos) == '.') {
                    pos++;
                    while (pos < length && Character.isDigit(s.charAt(pos))) pos++;
                }
                if (pos < length && (s.charAt(pos) == 'e' || s.charAt(pos) == 'E')) {
                    pos++;
                    if (pos < length && (s.charAt(pos) == '+' || s.charAt(pos) == '-')) pos++;
                    while (pos < length && Character.isDigit(s.charAt(pos))) pos++;
                }
                if (start == pos) throw new RuntimeException("Expected number");
                long value = (long) Double.parseDouble(s.substring(start, pos));
                return new JsonNumber(value);
            }
        }
    }

    static abstract class JsonValue {
        JsonObject asObject() { return (JsonObject) this; }
        JsonArray asArray() { return (JsonArray) this; }
        String asString() { return ((JsonString) this).value; }
        long asLong() { return ((JsonNumber) this).value; }
        int asInt() { return (int) asLong(); }
        boolean asBool() { return ((JsonBool) this).value; }
    }

    static class JsonObject extends JsonValue {
        final Map<String, JsonValue> map;
        JsonObject(Map<String, JsonValue> map) { this.map = map; }
        JsonValue get(String key) { return map.get(key); }
        String getString(String key) { return get(key).asString(); }
        long getLong(String key) { return get(key).asLong(); }
        int getInt(String key) { return get(key).asInt(); }
        JsonArray getArray(String key) { return get(key).asArray(); }
        JsonObject getObject(String key) { return get(key).asObject(); }
        boolean getBool(String key) { return get(key).asBool(); }
    }

    static class JsonArray extends JsonValue {
        final List<JsonValue> list;
        JsonArray(List<JsonValue> list) { this.list = list; }
        List<JsonValue> getValues() { return list; }
    }

    static class JsonString extends JsonValue {
        final String value;
        JsonString(String value) { this.value = value; }
    }

    static class JsonNumber extends JsonValue {
        final long value;
        JsonNumber(long value) { this.value = value; }
    }

    static class JsonBool extends JsonValue {
        final boolean value;
        JsonBool(boolean value) { this.value = value; }
    }

    static class JsonNull extends JsonValue {
    }
}
