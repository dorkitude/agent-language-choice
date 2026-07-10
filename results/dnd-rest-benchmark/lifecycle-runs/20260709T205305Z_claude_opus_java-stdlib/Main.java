import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Core D&D REST engine using only the Java standard library.
 */
public class Main {

    public static void main(String[] args) throws IOException {
        int port = 8080;
        String env = System.getenv("PORT");
        if (env != null && !env.isBlank()) {
            port = Integer.parseInt(env.trim());
        }

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", exchange -> handle(exchange, Main::health));
        server.createContext("/v1/dice/stats", exchange -> handle(exchange, Main::diceStats));
        server.createContext("/v1/checks/ability", exchange -> handle(exchange, Main::abilityCheck));
        server.createContext("/v1/encounters/adjusted-xp", exchange -> handle(exchange, Main::adjustedXp));
        server.createContext("/v1/initiative/order", exchange -> handle(exchange, Main::initiativeOrder));
        server.createContext("/v1/characters/ability-modifier", exchange -> handle(exchange, Main::abilityModifier));
        server.createContext("/v1/characters/proficiency", exchange -> handle(exchange, Main::proficiency));
        server.createContext("/v1/characters/derived-stats", exchange -> handle(exchange, Main::derivedStats));
        server.createContext("/v1/combat/sessions", exchange -> handle(exchange, Main::combatRouter));
        server.setExecutor(null);
        server.start();
    }

    // ----- Routing helpers -------------------------------------------------

    @FunctionalInterface
    interface Route {
        Object apply(HttpExchange exchange) throws Exception;
    }

    /** A route may throw HttpError to signal a specific status code. */
    static final class HttpError extends RuntimeException {
        final int status;
        HttpError(int status, String message) {
            super(message);
            this.status = status;
        }
    }

    static void handle(HttpExchange exchange, Route route) throws IOException {
        try {
            Object body = route.apply(exchange);
            sendJson(exchange, 200, body);
        } catch (HttpError e) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", e.getMessage());
            sendJson(exchange, e.status, err);
        } catch (Exception e) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "internal error");
            sendJson(exchange, 500, err);
        }
    }

    static String readBody(HttpExchange exchange) throws IOException {
        try (InputStream in = exchange.getRequestBody()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static Map<String, Object> readJsonObject(HttpExchange exchange) throws IOException {
        String raw = readBody(exchange);
        Object parsed;
        try {
            parsed = Json.parse(raw);
        } catch (RuntimeException e) {
            throw new HttpError(400, "invalid JSON");
        }
        if (!(parsed instanceof Map)) {
            throw new HttpError(400, "expected JSON object");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> map = (Map<String, Object>) parsed;
        return map;
    }

    static void sendJson(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] bytes = Json.write(body).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    // ----- Endpoints -------------------------------------------------------

    static Object health(HttpExchange exchange) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("ok", true);
        return res;
    }

    static final Pattern DICE = Pattern.compile("^\\s*(\\d+)d(\\d+)([+-]\\d+)?\\s*$");

    static Object diceStats(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);
        Object exprObj = req.get("expression");
        if (!(exprObj instanceof String)) {
            throw new HttpError(400, "expression required");
        }
        Matcher m = DICE.matcher((String) exprObj);
        if (!m.matches()) {
            throw new HttpError(400, "invalid expression");
        }
        long count = Long.parseLong(m.group(1));
        long sides = Long.parseLong(m.group(2));
        long modifier = m.group(3) == null ? 0 : Long.parseLong(m.group(3));
        if (count <= 0 || sides <= 0) {
            throw new HttpError(400, "count and sides must be positive");
        }
        long min = count + modifier;
        long max = count * sides + modifier;
        double average = (min + max) / 2.0;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("dice_count", count);
        res.put("sides", sides);
        res.put("modifier", modifier);
        res.put("min", min);
        res.put("max", max);
        res.put("average", average);
        return res;
    }

    static Object abilityCheck(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);
        long roll = asLong(req.get("roll"), "roll");
        long modifier = asLong(req.get("modifier"), "modifier");
        long dc = asLong(req.get("dc"), "dc");

        long total = roll + modifier;
        boolean success = total >= dc;
        long margin = total - dc;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("total", total);
        res.put("success", success);
        res.put("margin", margin);
        return res;
    }

    static final Map<String, Long> CR_XP = new LinkedHashMap<>();
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
    static final Map<Long, long[]> THRESHOLDS = new LinkedHashMap<>();
    static {
        THRESHOLDS.put(3L, new long[]{75, 150, 225, 400});
    }

    @SuppressWarnings("unchecked")
    static Object adjustedXp(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);

        Object partyObj = req.get("party");
        Object monstersObj = req.get("monsters");
        if (!(partyObj instanceof List) || !(monstersObj instanceof List)) {
            throw new HttpError(400, "party and monsters required");
        }
        List<Object> party = (List<Object>) partyObj;
        List<Object> monsters = (List<Object>) monstersObj;

        long baseXp = 0;
        long monsterCount = 0;
        for (Object mo : monsters) {
            if (!(mo instanceof Map)) {
                throw new HttpError(400, "invalid monster");
            }
            Map<String, Object> monster = (Map<String, Object>) mo;
            Object crObj = monster.get("cr");
            if (!(crObj instanceof String)) {
                throw new HttpError(400, "invalid cr");
            }
            String cr = (String) crObj;
            Long xp = CR_XP.get(cr);
            if (xp == null) {
                throw new HttpError(400, "unsupported cr: " + cr);
            }
            long cnt = asLong(monster.get("count"), "count");
            if (cnt < 0) {
                throw new HttpError(400, "count must be non-negative");
            }
            baseXp += xp * cnt;
            monsterCount += cnt;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjustedDouble = baseXp * multiplier;
        long adjustedXp = Math.round(adjustedDouble);

        // Sum party thresholds.
        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object po : party) {
            if (!(po instanceof Map)) {
                throw new HttpError(400, "invalid party member");
            }
            Map<String, Object> member = (Map<String, Object>) po;
            long level = asLong(member.get("level"), "level");
            long[] t = THRESHOLDS.get(level);
            if (t == null) {
                throw new HttpError(400, "unsupported level: " + level);
            }
            easy += t[0];
            medium += t[1];
            hard += t[2];
            deadly += t[3];
        }

        String difficulty = "trivial";
        if (adjustedXp >= deadly) {
            difficulty = "deadly";
        } else if (adjustedXp >= hard) {
            difficulty = "hard";
        } else if (adjustedXp >= medium) {
            difficulty = "medium";
        } else if (adjustedXp >= easy) {
            difficulty = "easy";
        }

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("base_xp", baseXp);
        res.put("monster_count", monsterCount);
        res.put("multiplier", numberOut(multiplier));
        res.put("adjusted_xp", adjustedXp);
        res.put("difficulty", difficulty);
        res.put("thresholds", thresholds);
        return res;
    }

    static double multiplierFor(long count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    @SuppressWarnings("unchecked")
    static Object initiativeOrder(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);
        Object combatantsObj = req.get("combatants");
        if (!(combatantsObj instanceof List)) {
            throw new HttpError(400, "combatants required");
        }
        List<Object> combatants = (List<Object>) combatantsObj;

        List<Combatant> list = new ArrayList<>();
        for (Object co : combatants) {
            if (!(co instanceof Map)) {
                throw new HttpError(400, "invalid combatant");
            }
            Map<String, Object> c = (Map<String, Object>) co;
            Object nameObj = c.get("name");
            if (!(nameObj instanceof String)) {
                throw new HttpError(400, "name required");
            }
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            list.add(new Combatant((String) nameObj, dex, roll));
        }

        list.sort(Comparator
                .comparingLong((Combatant c) -> c.roll + c.dex).reversed()
                .thenComparing(Comparator.comparingLong((Combatant c) -> c.dex).reversed())
                .thenComparing(c -> c.name));

        List<Object> order = new ArrayList<>();
        for (Combatant c : list) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", c.name);
            entry.put("score", c.roll + c.dex);
            order.add(entry);
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("order", order);
        return res;
    }

    record Combatant(String name, long dex, long roll) {}

    // ----- Character rules -------------------------------------------------

    /** floor((score - 10) / 2), flooring negative halves correctly. */
    static long abilityModifierValue(long score) {
        return Math.floorDiv(score - 10, 2);
    }

    static long proficiencyBonusValue(long level) {
        return (level + 3) / 4 + 1;
    }

    static Object abilityModifier(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);
        long score = asLong(req.get("score"), "score");
        if (score < 1 || score > 30) {
            throw new HttpError(400, "score must be between 1 and 30");
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("score", score);
        res.put("modifier", abilityModifierValue(score));
        return res;
    }

    static Object proficiency(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);
        long level = asLong(req.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new HttpError(400, "level must be between 1 and 20");
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("level", level);
        res.put("proficiency_bonus", proficiencyBonusValue(level));
        return res;
    }

    static final String[] ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"};

    @SuppressWarnings("unchecked")
    static Object derivedStats(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);

        long level = asLong(req.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new HttpError(400, "level must be between 1 and 20");
        }

        Object abilitiesObj = req.get("abilities");
        if (!(abilitiesObj instanceof Map)) {
            throw new HttpError(400, "abilities required");
        }
        Map<String, Object> abilities = (Map<String, Object>) abilitiesObj;

        Map<String, Object> modifiers = new LinkedHashMap<>();
        for (String key : ABILITY_KEYS) {
            long score = asLong(abilities.get(key), key);
            if (score < 1 || score > 30) {
                throw new HttpError(400, key + " must be between 1 and 30");
            }
            modifiers.put(key, abilityModifierValue(score));
        }
        long conMod = (Long) modifiers.get("con");
        long dexMod = (Long) modifiers.get("dex");

        Object armorObj = req.get("armor");
        if (!(armorObj instanceof Map)) {
            throw new HttpError(400, "armor required");
        }
        Map<String, Object> armor = (Map<String, Object>) armorObj;
        long base = asLong(armor.get("base"), "armor.base");
        long dexCap = asLong(armor.get("dex_cap"), "armor.dex_cap");
        Object shieldObj = armor.get("shield");
        if (!(shieldObj instanceof Boolean)) {
            throw new HttpError(400, "armor.shield required");
        }
        long shieldBonus = ((Boolean) shieldObj) ? 2 : 0;

        long proficiencyBonus = proficiencyBonusValue(level);
        long hpMax = level * (6 + conMod);
        long armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("level", level);
        res.put("proficiency_bonus", proficiencyBonus);
        res.put("hp_max", hpMax);
        res.put("armor_class", armorClass);
        res.put("modifiers", modifiers);
        return res;
    }

    // ----- Stateful combat -------------------------------------------------

    static final class Condition {
        final String condition;
        long remaining;
        Condition(String condition, long remaining) {
            this.condition = condition;
            this.remaining = remaining;
        }
    }

    static final class CombatantState {
        final String name;
        final long dex;
        final long score;
        final List<Condition> conditions = new ArrayList<>();
        CombatantState(String name, long dex, long score) {
            this.name = name;
            this.dex = dex;
            this.score = score;
        }
    }

    static final class Session {
        final String id;
        long round = 1;
        int turnIndex = 0;
        final List<CombatantState> order = new ArrayList<>();
        Session(String id) {
            this.id = id;
        }
    }

    static final Map<String, Session> SESSIONS = new LinkedHashMap<>();

    static final Pattern CONDITIONS_PATH =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/conditions/?$");
    static final Pattern ADVANCE_PATH =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/advance/?$");

    static Object combatRouter(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();

        if (path.equals("/v1/combat/sessions") || path.equals("/v1/combat/sessions/")) {
            if (!"POST".equalsIgnoreCase(method)) {
                throw new HttpError(405, "method not allowed");
            }
            return createSession(exchange);
        }

        Matcher cond = CONDITIONS_PATH.matcher(path);
        if (cond.matches()) {
            if (!"POST".equalsIgnoreCase(method)) {
                throw new HttpError(405, "method not allowed");
            }
            return addCondition(exchange, decode(cond.group(1)));
        }

        Matcher adv = ADVANCE_PATH.matcher(path);
        if (adv.matches()) {
            if (!"POST".equalsIgnoreCase(method)) {
                throw new HttpError(405, "method not allowed");
            }
            return advanceTurn(decode(adv.group(1)));
        }

        throw new HttpError(404, "not found");
    }

    static String decode(String raw) {
        return java.net.URLDecoder.decode(raw, StandardCharsets.UTF_8);
    }

    @SuppressWarnings("unchecked")
    static Object createSession(HttpExchange exchange) throws IOException {
        Map<String, Object> req = readJsonObject(exchange);

        Object idObj = req.get("id");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
            throw new HttpError(400, "id required");
        }
        String id = (String) idObj;
        if (SESSIONS.containsKey(id)) {
            throw new HttpError(400, "session id already exists");
        }

        Object combatantsObj = req.get("combatants");
        if (!(combatantsObj instanceof List)) {
            throw new HttpError(400, "combatants required");
        }
        List<Object> combatants = (List<Object>) combatantsObj;
        if (combatants.isEmpty()) {
            throw new HttpError(400, "combatants must not be empty");
        }

        Session session = new Session(id);
        for (Object co : combatants) {
            if (!(co instanceof Map)) {
                throw new HttpError(400, "invalid combatant");
            }
            Map<String, Object> c = (Map<String, Object>) co;
            Object nameObj = c.get("name");
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                throw new HttpError(400, "name required");
            }
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            session.order.add(new CombatantState((String) nameObj, dex, roll + dex));
        }

        session.order.sort(Comparator
                .comparingLong((CombatantState c) -> c.score).reversed()
                .thenComparing(Comparator.comparingLong((CombatantState c) -> c.dex).reversed())
                .thenComparing(c -> c.name));

        SESSIONS.put(id, session);
        return sessionCreateResponse(session);
    }

    @SuppressWarnings("unchecked")
    static Object addCondition(HttpExchange exchange, String id) throws IOException {
        Session session = SESSIONS.get(id);
        if (session == null) {
            throw new HttpError(404, "unknown session");
        }
        Map<String, Object> req = readJsonObject(exchange);

        Object targetObj = req.get("target");
        if (!(targetObj instanceof String)) {
            throw new HttpError(400, "target required");
        }
        String target = (String) targetObj;

        Object conditionObj = req.get("condition");
        if (!(conditionObj instanceof String) || ((String) conditionObj).isEmpty()) {
            throw new HttpError(400, "condition required");
        }
        String condition = (String) conditionObj;

        long duration = asLong(req.get("duration_rounds"), "duration_rounds");
        if (duration <= 0) {
            throw new HttpError(400, "duration_rounds must be positive");
        }

        CombatantState combatant = null;
        for (CombatantState c : session.order) {
            if (c.name.equals(target)) {
                combatant = c;
                break;
            }
        }
        if (combatant == null) {
            throw new HttpError(400, "target not in session");
        }

        combatant.conditions.add(new Condition(condition, duration));

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("target", target);
        res.put("conditions", conditionList(combatant));
        return res;
    }

    static Object advanceTurn(String id) {
        Session session = SESSIONS.get(id);
        if (session == null) {
            throw new HttpError(404, "unknown session");
        }

        session.turnIndex++;
        if (session.turnIndex >= session.order.size()) {
            session.turnIndex = 0;
            session.round++;
        }

        CombatantState active = session.order.get(session.turnIndex);
        Iterator<Condition> it = active.conditions.iterator();
        while (it.hasNext()) {
            Condition c = it.next();
            c.remaining--;
            if (c.remaining <= 0) {
                it.remove();
            }
        }

        Map<String, Object> conditions = new LinkedHashMap<>();
        for (CombatantState c : session.order) {
            if (!c.conditions.isEmpty()) {
                conditions.put(c.name, conditionList(c));
            }
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", session.id);
        res.put("round", session.round);
        res.put("turn_index", (long) session.turnIndex);
        res.put("active", combatantSummary(active));
        res.put("conditions", conditions);
        return res;
    }

    static Object sessionCreateResponse(Session session) {
        List<Object> order = new ArrayList<>();
        for (CombatantState c : session.order) {
            order.add(combatantSummary(c));
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", session.id);
        res.put("round", session.round);
        res.put("turn_index", (long) session.turnIndex);
        res.put("active", combatantSummary(session.order.get(session.turnIndex)));
        res.put("order", order);
        return res;
    }

    static Map<String, Object> combatantSummary(CombatantState c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", c.name);
        m.put("score", c.score);
        return m;
    }

    static List<Object> conditionList(CombatantState c) {
        List<Object> list = new ArrayList<>();
        for (Condition cond : c.conditions) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("condition", cond.condition);
            m.put("remaining_rounds", cond.remaining);
            list.add(m);
        }
        return list;
    }

    // ----- Value helpers ---------------------------------------------------

    static long asLong(Object o, String field) {
        if (o instanceof Number) {
            double d = ((Number) o).doubleValue();
            if (d == Math.rint(d) && !Double.isInfinite(d)) {
                return (long) d;
            }
            throw new HttpError(400, field + " must be an integer");
        }
        throw new HttpError(400, field + " required");
    }

    /** Emit a whole-valued double as a long so JSON shows "2" rather than "2.0". */
    static Object numberOut(double d) {
        if (d == Math.rint(d) && !Double.isInfinite(d)) {
            return (long) d;
        }
        return d;
    }

    // ----- Minimal JSON ----------------------------------------------------

    static final class Json {
        private final String s;
        private int i;

        private Json(String s) {
            this.s = s;
        }

        static Object parse(String s) {
            Json j = new Json(s);
            j.ws();
            Object v = j.value();
            j.ws();
            if (j.i != s.length()) {
                throw new RuntimeException("trailing content");
            }
            return v;
        }

        private void ws() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
                i++;
            }
        }

        private Object value() {
            if (i >= s.length()) {
                throw new RuntimeException("unexpected end");
            }
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': case 'f': return bool();
                case 'n': return nul();
                default: return number();
            }
        }

        private Map<String, Object> object() {
            Map<String, Object> map = new LinkedHashMap<>();
            i++; // {
            ws();
            if (i < s.length() && s.charAt(i) == '}') {
                i++;
                return map;
            }
            while (true) {
                ws();
                if (s.charAt(i) != '"') {
                    throw new RuntimeException("expected key");
                }
                String key = string();
                ws();
                if (s.charAt(i) != ':') {
                    throw new RuntimeException("expected colon");
                }
                i++;
                ws();
                map.put(key, value());
                ws();
                char c = s.charAt(i);
                if (c == ',') {
                    i++;
                } else if (c == '}') {
                    i++;
                    return map;
                } else {
                    throw new RuntimeException("expected , or }");
                }
            }
        }

        private List<Object> array() {
            List<Object> list = new ArrayList<>();
            i++; // [
            ws();
            if (i < s.length() && s.charAt(i) == ']') {
                i++;
                return list;
            }
            while (true) {
                ws();
                list.add(value());
                ws();
                char c = s.charAt(i);
                if (c == ',') {
                    i++;
                } else if (c == ']') {
                    i++;
                    return list;
                } else {
                    throw new RuntimeException("expected , or ]");
                }
            }
        }

        private String string() {
            StringBuilder sb = new StringBuilder();
            i++; // opening quote
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') {
                    return sb.toString();
                }
                if (c == '\\') {
                    char e = s.charAt(i++);
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
                            sb.append((char) Integer.parseInt(hex, 16));
                            i += 4;
                            break;
                        default: throw new RuntimeException("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new RuntimeException("unterminated string");
        }

        private Boolean bool() {
            if (s.startsWith("true", i)) {
                i += 4;
                return Boolean.TRUE;
            }
            if (s.startsWith("false", i)) {
                i += 5;
                return Boolean.FALSE;
            }
            throw new RuntimeException("bad literal");
        }

        private Object nul() {
            if (s.startsWith("null", i)) {
                i += 4;
                return null;
            }
            throw new RuntimeException("bad literal");
        }

        private Number number() {
            int start = i;
            if (i < s.length() && (s.charAt(i) == '-' || s.charAt(i) == '+')) {
                i++;
            }
            boolean isDouble = false;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c >= '0' && c <= '9') {
                    i++;
                } else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                    isDouble = true;
                    i++;
                } else {
                    break;
                }
            }
            String num = s.substring(start, i);
            if (num.isEmpty()) {
                throw new RuntimeException("bad number");
            }
            if (isDouble) {
                return Double.parseDouble(num);
            }
            try {
                return Long.parseLong(num);
            } catch (NumberFormatException e) {
                return Double.parseDouble(num);
            }
        }

        // --- serialization ---

        static String write(Object o) {
            StringBuilder sb = new StringBuilder();
            writeValue(sb, o);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(StringBuilder sb, Object o) {
            if (o == null) {
                sb.append("null");
            } else if (o instanceof Map) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    writeString(sb, e.getKey());
                    sb.append(':');
                    writeValue(sb, e.getValue());
                }
                sb.append('}');
            } else if (o instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object item : (List<Object>) o) {
                    if (!first) sb.append(',');
                    first = false;
                    writeValue(sb, item);
                }
                sb.append(']');
            } else if (o instanceof String) {
                writeString(sb, (String) o);
            } else if (o instanceof Boolean) {
                sb.append(o.toString());
            } else if (o instanceof Double || o instanceof Float) {
                double d = ((Number) o).doubleValue();
                if (d == Math.rint(d) && !Double.isInfinite(d)) {
                    sb.append(Long.toString((long) d));
                } else {
                    sb.append(Double.toString(d));
                }
            } else if (o instanceof Number) {
                sb.append(o.toString());
            } else {
                writeString(sb, o.toString());
            }
        }

        private static void writeString(StringBuilder sb, String s) {
            sb.append('"');
            for (int k = 0; k < s.length(); k++) {
                char c = s.charAt(k);
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
