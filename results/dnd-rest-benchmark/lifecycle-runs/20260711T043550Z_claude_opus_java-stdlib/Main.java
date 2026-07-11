import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Core D&D REST engine on the Java standard library. */
public class Main {

    public static void main(String[] args) throws IOException {
        String portEnv = System.getenv("PORT");
        int port = (portEnv == null || portEnv.isEmpty()) ? 8080 : Integer.parseInt(portEnv.trim());

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);

        server.createContext("/health", exchange -> {
            if (!requireMethod(exchange, "GET")) return;
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("ok", true);
            respond(exchange, 200, body);
        });

        server.createContext("/v1/dice/stats", exchange -> handle(exchange, Main::diceStats));
        server.createContext("/v1/checks/ability", exchange -> handle(exchange, Main::abilityCheck));
        server.createContext("/v1/encounters/adjusted-xp", exchange -> handle(exchange, Main::adjustedXp));
        server.createContext("/v1/initiative/order", exchange -> handle(exchange, Main::initiativeOrder));
        server.createContext("/v1/characters/ability-modifier", exchange -> handle(exchange, Main::abilityModifier));
        server.createContext("/v1/characters/proficiency", exchange -> handle(exchange, Main::proficiency));
        server.createContext("/v1/characters/derived-stats", exchange -> handle(exchange, Main::derivedStats));
        server.createContext("/v1/combat/sessions", Main::combat);
        server.createContext("/v1/auth/register", exchange -> handleAuth(exchange, Main::register));
        server.createContext("/v1/auth/login", exchange -> handleAuth(exchange, Main::login));

        server.setExecutor(null);
        server.start();
    }

    // ---- Routing helpers ----

    private interface Handler {
        Object apply(Object request) throws BadRequest;
    }

    private static class BadRequest extends Exception {
        BadRequest(String msg) { super(msg); }
    }

    private static void handle(HttpExchange exchange, Handler handler) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        Object request;
        try {
            String raw = new String(readAll(exchange.getRequestBody()), StandardCharsets.UTF_8);
            request = Json.parse(raw);
        } catch (Exception e) {
            respondError(exchange, 400, "invalid JSON");
            return;
        }
        try {
            Object result = handler.apply(request);
            respond(exchange, 200, result);
        } catch (BadRequest e) {
            respondError(exchange, 400, e.getMessage());
        } catch (Exception e) {
            respondError(exchange, 400, "bad request");
        }
    }

    private static boolean requireMethod(HttpExchange exchange, String method) throws IOException {
        if (!method.equalsIgnoreCase(exchange.getRequestMethod())) {
            respondError(exchange, 405, "method not allowed");
            return false;
        }
        return true;
    }

    // ---- Endpoint logic ----

    private static final Pattern DICE = Pattern.compile("^\\s*(\\d+)d(\\d+)([+-]\\d+)?\\s*$");

    private static Object diceStats(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        Object exprVal = obj.get("expression");
        if (!(exprVal instanceof String)) throw new BadRequest("expression required");
        Matcher m = DICE.matcher((String) exprVal);
        if (!m.matches()) throw new BadRequest("invalid expression");

        long count = Long.parseLong(m.group(1));
        long sides = Long.parseLong(m.group(2));
        long modifier = m.group(3) == null ? 0 : Long.parseLong(m.group(3));
        if (count <= 0 || sides <= 0) throw new BadRequest("count and sides must be positive");

        long min = count * 1 + modifier;
        long max = count * sides + modifier;
        double average = count * (1 + sides) / 2.0 + modifier;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("dice_count", count);
        out.put("sides", sides);
        out.put("modifier", modifier);
        out.put("min", min);
        out.put("max", max);
        out.put("average", average);
        return out;
    }

    private static Object abilityCheck(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        long roll = asLong(obj.get("roll"), "roll");
        long modifier = asLong(obj.get("modifier"), "modifier");
        long dc = asLong(obj.get("dc"), "dc");

        long total = roll + modifier;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total);
        out.put("success", total >= dc);
        out.put("margin", total - dc);
        return out;
    }

    private static final Map<String, Long> CR_XP = new LinkedHashMap<>();
    static {
        CR_XP.put("0", 10L);
        CR_XP.put("1/8", 25L);
        CR_XP.put("1/4", 50L);
        CR_XP.put("1/2", 100L);
        CR_XP.put("1", 200L);
        CR_XP.put("2", 450L);
        CR_XP.put("3", 700L);
        CR_XP.put("4", 1100L);
        CR_XP.put("5", 1800L);
    }

    // Level -> {easy, medium, hard, deadly}
    private static final Map<Long, long[]> LEVEL_THRESHOLDS = new LinkedHashMap<>();
    static {
        LEVEL_THRESHOLDS.put(3L, new long[]{75, 150, 225, 400});
    }

    private static Object adjustedXp(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        List<Object> party = asArray(obj.get("party"), "party");
        List<Object> monsters = asArray(obj.get("monsters"), "monsters");

        long baseXp = 0;
        long monsterCount = 0;
        for (Object mo : monsters) {
            Map<String, Object> monster = asObject(mo);
            Object crVal = monster.get("cr");
            String cr;
            if (crVal instanceof String) {
                cr = (String) crVal;
            } else if (crVal instanceof Long) {
                cr = String.valueOf((long) (Long) crVal);
            } else if (crVal instanceof Double) {
                cr = trimNumber((Double) crVal);
            } else {
                throw new BadRequest("cr required");
            }
            Long xp = CR_XP.get(cr);
            if (xp == null) throw new BadRequest("unsupported cr: " + cr);
            long count = asLong(monster.get("count"), "count");
            if (count < 0) throw new BadRequest("count must be non-negative");
            baseXp += xp * count;
            monsterCount += count;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjustedRaw = baseXp * multiplier;
        long adjustedXp = Math.round(adjustedRaw);

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object po : party) {
            Map<String, Object> member = asObject(po);
            long level = asLong(member.get("level"), "level");
            long[] t = LEVEL_THRESHOLDS.get(level);
            if (t == null) throw new BadRequest("unsupported level: " + level);
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

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("base_xp", baseXp);
        out.put("monster_count", monsterCount);
        out.put("multiplier", numberOrInt(multiplier));
        out.put("adjusted_xp", adjustedXp);
        out.put("difficulty", difficulty);
        out.put("thresholds", thresholds);
        return out;
    }

    private static double multiplierFor(long monsterCount) {
        if (monsterCount <= 1) return 1.0;
        if (monsterCount == 2) return 1.5;
        if (monsterCount <= 6) return 2.0;
        if (monsterCount <= 10) return 2.5;
        if (monsterCount <= 14) return 3.0;
        return 4.0;
    }

    private static Object initiativeOrder(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        List<Object> combatants = asArray(obj.get("combatants"), "combatants");

        List<Map<String, Object>> parsed = new ArrayList<>();
        for (Object co : combatants) {
            Map<String, Object> c = asObject(co);
            Object nameVal = c.get("name");
            if (!(nameVal instanceof String)) throw new BadRequest("name required");
            String name = (String) nameVal;
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            long score = roll + dex;

            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", name);
            entry.put("dex", dex);
            entry.put("score", score);
            parsed.add(entry);
        }

        parsed.sort((a, b) -> {
            long sa = (Long) a.get("score"), sb = (Long) b.get("score");
            if (sa != sb) return Long.compare(sb, sa);
            long da = (Long) a.get("dex"), db = (Long) b.get("dex");
            if (da != db) return Long.compare(db, da);
            return ((String) a.get("name")).compareTo((String) b.get("name"));
        });

        List<Object> order = new ArrayList<>();
        for (Map<String, Object> entry : parsed) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("name", entry.get("name"));
            out.put("score", entry.get("score"));
            order.add(out);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("order", order);
        return out;
    }

    // ---- Combat sessions ----

    private static class NotFound extends Exception {
        NotFound(String msg) { super(msg); }
    }

    private static final class Combatant {
        final String name;
        final long score;
        final long dex;
        final List<Map<String, Object>> conditions = new ArrayList<>();
        boolean everHadCondition = false;

        Combatant(String name, long dex, long score) {
            this.name = name;
            this.dex = dex;
            this.score = score;
        }
    }

    private static final class Session {
        final String id;
        int round = 1;
        int turnIndex = 0;
        final List<Combatant> order = new ArrayList<>();

        Session(String id) { this.id = id; }

        Combatant find(String name) {
            for (Combatant c : order) {
                if (c.name.equals(name)) return c;
            }
            return null;
        }
    }

    private static final Map<String, Session> SESSIONS = new ConcurrentHashMap<>();

    private static void combat(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        String path = exchange.getRequestURI().getPath();
        String rest = path.substring("/v1/combat/sessions".length());
        if (rest.startsWith("/")) rest = rest.substring(1);
        if (rest.endsWith("/")) rest = rest.substring(0, rest.length() - 1);

        byte[] rawBytes;
        try {
            rawBytes = readAll(exchange.getRequestBody());
        } catch (Exception e) {
            respondError(exchange, 400, "bad request");
            return;
        }

        try {
            Object result;
            if (rest.isEmpty()) {
                result = createSession(parseBody(rawBytes));
            } else {
                int slash = rest.indexOf('/');
                if (slash < 0) throw new BadRequest("unknown route");
                String id = urlDecode(rest.substring(0, slash));
                String action = rest.substring(slash + 1);
                Session session = SESSIONS.get(id);
                if (session == null) throw new NotFound("unknown session: " + id);
                if (action.equals("conditions")) {
                    result = addCondition(session, parseBody(rawBytes));
                } else if (action.equals("advance")) {
                    result = advanceTurn(session);
                } else {
                    throw new BadRequest("unknown route");
                }
            }
            respond(exchange, 200, result);
        } catch (NotFound e) {
            respondError(exchange, 404, e.getMessage());
        } catch (BadRequest e) {
            respondError(exchange, 400, e.getMessage());
        } catch (Exception e) {
            respondError(exchange, 400, "bad request");
        }
    }

    private static Object parseBody(byte[] rawBytes) throws BadRequest {
        try {
            String raw = new String(rawBytes, StandardCharsets.UTF_8);
            return Json.parse(raw);
        } catch (Exception e) {
            throw new BadRequest("invalid JSON");
        }
    }

    private static String urlDecode(String s) {
        return java.net.URLDecoder.decode(s, StandardCharsets.UTF_8);
    }

    private static Object createSession(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        Object idVal = obj.get("id");
        if (!(idVal instanceof String) || ((String) idVal).isEmpty()) throw new BadRequest("id required");
        String id = (String) idVal;
        if (SESSIONS.containsKey(id)) throw new BadRequest("session id already exists: " + id);

        List<Object> combatants = asArray(obj.get("combatants"), "combatants");
        if (combatants.isEmpty()) throw new BadRequest("combatants required");

        Session session = new Session(id);
        for (Object co : combatants) {
            Map<String, Object> c = asObject(co);
            Object nameVal = c.get("name");
            if (!(nameVal instanceof String)) throw new BadRequest("name required");
            String name = (String) nameVal;
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            session.order.add(new Combatant(name, dex, roll + dex));
        }

        session.order.sort((a, b) -> {
            if (a.score != b.score) return Long.compare(b.score, a.score);
            if (a.dex != b.dex) return Long.compare(b.dex, a.dex);
            return a.name.compareTo(b.name);
        });

        SESSIONS.put(id, session);
        return sessionSummary(session);
    }

    private static Object addCondition(Session session, Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        Object targetVal = obj.get("target");
        if (!(targetVal instanceof String)) throw new BadRequest("target required");
        Combatant target = session.find((String) targetVal);
        if (target == null) throw new BadRequest("unknown target: " + targetVal);

        Object condVal = obj.get("condition");
        if (!(condVal instanceof String) || ((String) condVal).isEmpty()) throw new BadRequest("condition required");
        long duration = asLong(obj.get("duration_rounds"), "duration_rounds");
        if (duration <= 0) throw new BadRequest("duration_rounds must be a positive integer");

        Map<String, Object> cond = new LinkedHashMap<>();
        cond.put("condition", condVal);
        cond.put("remaining_rounds", duration);
        target.conditions.add(cond);
        target.everHadCondition = true;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("target", target.name);
        out.put("conditions", conditionsCopy(target.conditions));
        return out;
    }

    private static Object advanceTurn(Session session) {
        int n = session.order.size();
        session.turnIndex++;
        if (session.turnIndex >= n) {
            session.turnIndex = 0;
            session.round++;
        }

        Combatant active = session.order.get(session.turnIndex);
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map<String, Object> cond : active.conditions) {
            long remaining = (Long) cond.get("remaining_rounds") - 1;
            if (remaining > 0) {
                cond.put("remaining_rounds", remaining);
                kept.add(cond);
            }
        }
        active.conditions.clear();
        active.conditions.addAll(kept);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", session.id);
        out.put("round", (long) session.round);
        out.put("turn_index", (long) session.turnIndex);
        out.put("active", combatantRef(active));
        out.put("conditions", allConditions(session));
        return out;
    }

    private static Object sessionSummary(Session session) {
        List<Object> order = new ArrayList<>();
        for (Combatant c : session.order) {
            order.add(combatantRef(c));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", session.id);
        out.put("round", (long) session.round);
        out.put("turn_index", (long) session.turnIndex);
        out.put("active", combatantRef(session.order.get(session.turnIndex)));
        out.put("order", order);
        return out;
    }

    private static Map<String, Object> combatantRef(Combatant c) {
        Map<String, Object> ref = new LinkedHashMap<>();
        ref.put("name", c.name);
        ref.put("score", c.score);
        return ref;
    }

    private static List<Object> conditionsCopy(List<Map<String, Object>> conditions) {
        List<Object> out = new ArrayList<>();
        for (Map<String, Object> cond : conditions) {
            Map<String, Object> copy = new LinkedHashMap<>();
            copy.put("condition", cond.get("condition"));
            copy.put("remaining_rounds", cond.get("remaining_rounds"));
            out.add(copy);
        }
        return out;
    }

    private static Map<String, Object> allConditions(Session session) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Combatant c : session.order) {
            if (c.everHadCondition) {
                out.put(c.name, conditionsCopy(c.conditions));
            }
        }
        return out;
    }

    // ---- Character rules ----

    private static long abilityModifierFor(long score) throws BadRequest {
        if (score < 1 || score > 30) throw new BadRequest("score must be 1-30");
        return Math.floorDiv(score - 10, 2);
    }

    private static long proficiencyFor(long level) throws BadRequest {
        if (level < 1 || level > 20) throw new BadRequest("level must be 1-20");
        return (level - 1) / 4 + 2;
    }

    private static Object abilityModifier(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        long score = asLong(obj.get("score"), "score");
        long modifier = abilityModifierFor(score);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("score", score);
        out.put("modifier", modifier);
        return out;
    }

    private static Object proficiency(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        long level = asLong(obj.get("level"), "level");
        long bonus = proficiencyFor(level);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("level", level);
        out.put("proficiency_bonus", bonus);
        return out;
    }

    private static final String[] ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"};

    private static Object derivedStats(Object request) throws BadRequest {
        Map<String, Object> obj = asObject(request);
        long level = asLong(obj.get("level"), "level");
        long proficiencyBonus = proficiencyFor(level);

        Map<String, Object> abilities = asObject(obj.get("abilities"));
        Map<String, Object> modifiers = new LinkedHashMap<>();
        for (String key : ABILITY_KEYS) {
            long score = asLong(abilities.get(key), key);
            modifiers.put(key, abilityModifierFor(score));
        }

        long conMod = (Long) modifiers.get("con");
        long dexMod = (Long) modifiers.get("dex");
        long hpMax = level * (6 + conMod);

        Map<String, Object> armor = asObject(obj.get("armor"));
        long base = asLong(armor.get("base"), "armor.base");
        long dexCap = asLong(armor.get("dex_cap"), "armor.dex_cap");
        Object shieldVal = armor.get("shield");
        if (!(shieldVal instanceof Boolean)) throw new BadRequest("armor.shield must be a boolean");
        long shieldBonus = ((Boolean) shieldVal) ? 2 : 0;
        long armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("level", level);
        out.put("proficiency_bonus", proficiencyBonus);
        out.put("hp_max", hpMax);
        out.put("armor_class", armorClass);
        out.put("modifiers", modifiers);
        return out;
    }

    // ---- Coercion helpers ----

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asObject(Object value) throws BadRequest {
        if (!(value instanceof Map)) throw new BadRequest("expected object");
        return (Map<String, Object>) value;
    }

    @SuppressWarnings("unchecked")
    private static List<Object> asArray(Object value, String field) throws BadRequest {
        if (!(value instanceof List)) throw new BadRequest(field + " must be an array");
        return (List<Object>) value;
    }

    private static long asLong(Object value, String field) throws BadRequest {
        if (value instanceof Long) return (Long) value;
        if (value instanceof Double) {
            double d = (Double) value;
            if (d == Math.rint(d) && !Double.isInfinite(d)) return (long) d;
        }
        throw new BadRequest(field + " must be an integer");
    }

    private static String trimNumber(double d) {
        if (d == Math.rint(d) && !Double.isInfinite(d)) return String.valueOf((long) d);
        return String.valueOf(d);
    }

    private static Object numberOrInt(double d) {
        if (d == Math.rint(d) && !Double.isInfinite(d)) return (long) d;
        return d;
    }

    // ---- HTTP I/O ----

    private static byte[] readAll(InputStream in) throws IOException {
        return in.readAllBytes();
    }

    private static void respond(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] bytes = Json.stringify(body).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static void respondError(HttpExchange exchange, int status, String message) throws IOException {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", message);
        respond(exchange, status, body);
    }

    // ---- Minimal JSON parser / serializer ----

    private static final class Json {
        private final String s;
        private int i;

        private Json(String s) { this.s = s; }

        static Object parse(String s) {
            Json p = new Json(s);
            p.skipWs();
            Object v = p.parseValue();
            p.skipWs();
            if (p.i != s.length()) throw new IllegalArgumentException("trailing content");
            return v;
        }

        private Object parseValue() {
            skipWs();
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            char c = s.charAt(i);
            switch (c) {
                case '{': return parseObject();
                case '[': return parseArray();
                case '"': return parseString();
                case 't': case 'f': return parseBool();
                case 'n': return parseNull();
                default: return parseNumber();
            }
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> obj = new LinkedHashMap<>();
            expect('{');
            skipWs();
            if (peek() == '}') { i++; return obj; }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                expect(':');
                Object value = parseValue();
                obj.put(key, value);
                skipWs();
                char c = next();
                if (c == '}') break;
                if (c != ',') throw new IllegalArgumentException("expected , or }");
            }
            return obj;
        }

        private List<Object> parseArray() {
            List<Object> arr = new ArrayList<>();
            expect('[');
            skipWs();
            if (peek() == ']') { i++; return arr; }
            while (true) {
                Object value = parseValue();
                arr.add(value);
                skipWs();
                char c = next();
                if (c == ']') break;
                if (c != ',') throw new IllegalArgumentException("expected , or ]");
            }
            return arr;
        }

        private String parseString() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (true) {
                char c = next();
                if (c == '"') break;
                if (c == '\\') {
                    char e = next();
                    switch (e) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u':
                            String hex = s.substring(i, i + 4);
                            i += 4;
                            sb.append((char) Integer.parseInt(hex, 16));
                            break;
                        default: throw new IllegalArgumentException("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object parseNumber() {
            int start = i;
            boolean isDouble = false;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '-' || c == '+' || (c >= '0' && c <= '9')) {
                    i++;
                } else if (c == '.' || c == 'e' || c == 'E') {
                    isDouble = true;
                    i++;
                } else {
                    break;
                }
            }
            String num = s.substring(start, i);
            if (num.isEmpty()) throw new IllegalArgumentException("invalid number");
            if (isDouble) return Double.parseDouble(num);
            try {
                return Long.parseLong(num);
            } catch (NumberFormatException e) {
                return Double.parseDouble(num);
            }
        }

        private Boolean parseBool() {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            throw new IllegalArgumentException("invalid literal");
        }

        private Object parseNull() {
            if (s.startsWith("null", i)) { i += 4; return null; }
            throw new IllegalArgumentException("invalid literal");
        }

        private void skipWs() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        private char peek() {
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            return s.charAt(i);
        }

        private char next() {
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            return s.charAt(i++);
        }

        private void expect(char c) {
            if (next() != c) throw new IllegalArgumentException("expected " + c);
        }

        // ---- Serialization ----

        static String stringify(Object value) {
            StringBuilder sb = new StringBuilder();
            write(sb, value);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void write(StringBuilder sb, Object value) {
            if (value == null) {
                sb.append("null");
            } else if (value instanceof Map) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> e : ((Map<String, Object>) value).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    writeString(sb, e.getKey());
                    sb.append(':');
                    write(sb, e.getValue());
                }
                sb.append('}');
            } else if (value instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object item : (List<Object>) value) {
                    if (!first) sb.append(',');
                    first = false;
                    write(sb, item);
                }
                sb.append(']');
            } else if (value instanceof String) {
                writeString(sb, (String) value);
            } else if (value instanceof Boolean) {
                sb.append(value.toString());
            } else if (value instanceof Double) {
                double d = (Double) value;
                if (d == Math.rint(d) && !Double.isInfinite(d)) {
                    sb.append(Long.toString((long) d));
                } else {
                    sb.append(Double.toString(d));
                }
            } else if (value instanceof Number) {
                sb.append(value.toString());
            } else {
                writeString(sb, value.toString());
            }
        }

        private static void writeString(StringBuilder sb, String s) {
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
                        if (c < 0x20) {
                            sb.append(String.format("\\u%04x", (int) c));
                        } else {
                            sb.append(c);
                        }
                }
            }
            sb.append('"');
        }
    }
}
