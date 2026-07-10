import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpExchange;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

public class Main {

    // ---- D&D data tables ---------------------------------------------------

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

    // <count>d<sides>[+/-<modifier>]
    private static final Pattern DICE_EXPR =
            Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

    // In-memory combat sessions, keyed by client-supplied id
    private static final Map<String, CombatSession> SESSIONS =
            new java.util.concurrent.ConcurrentHashMap<>();

    // ----------------------------------------------------------------------

    public static void main(String[] args) throws IOException {
        int port = 8080;
        String portEnv = System.getenv("PORT");
        if (portEnv != null && !portEnv.isEmpty()) {
            try {
                port = Integer.parseInt(portEnv.trim());
            } catch (NumberFormatException ignored) {
                port = 8080;
            }
        }
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/", new Router());
        server.setExecutor(null);
        server.start();
        System.out.println("listening on 127.0.0.1:" + port);
    }

    // ---- HTTP plumbing -----------------------------------------------------

    private static final class Response {
        final int code;
        final Object body;
        Response(int code, Object body) {
            this.code = code;
            this.body = body;
        }
    }

    private static final class HttpError extends Exception {
        final int code;
        HttpError(int code, String msg) {
            super(msg);
            this.code = code;
        }
    }

    private static final class Router implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            Response r;
            try {
                String method = ex.getRequestMethod();
                String path = ex.getRequestURI().getPath();
                if (method.equals("POST") && path.equals("/v1/combat/sessions")) {
                    r = createCombatSession(parseBody(ex));
                } else if (method.equals("POST") && path.startsWith("/v1/combat/sessions/")) {
                    r = routeCombatSession(path, ex);
                } else {
                    String key = method + " " + path;
                    switch (key) {
                        case "GET /health":
                            r = health();
                            break;
                        case "POST /v1/dice/stats":
                            r = diceStats(parseBody(ex));
                            break;
                        case "POST /v1/checks/ability":
                            r = abilityCheck(parseBody(ex));
                            break;
                        case "POST /v1/encounters/adjusted-xp":
                            r = adjustedXp(parseBody(ex));
                            break;
                        case "POST /v1/initiative/order":
                            r = initiativeOrder(parseBody(ex));
                            break;
                        case "POST /v1/characters/ability-modifier":
                            r = abilityModifier(parseBody(ex));
                            break;
                        case "POST /v1/characters/proficiency":
                            r = proficiency(parseBody(ex));
                            break;
                        case "POST /v1/characters/derived-stats":
                            r = derivedStats(parseBody(ex));
                            break;
                        default:
                            r = new Response(404, err("not found"));
                    }
                }
            } catch (HttpError e) {
                r = new Response(e.code, err(e.getMessage()));
            } catch (Exception e) {
                r = new Response(500, err("internal error"));
            }
            sendJson(ex, r.code, r.body);
            ex.close();
        }
    }

    private static Response routeCombatSession(String path, HttpExchange ex)
            throws HttpError, IOException {
        String rest = path.substring("/v1/combat/sessions/".length());
        int slash = rest.indexOf('/');
        if (slash > 0) {
            String sessionId = rest.substring(0, slash);
            String action = rest.substring(slash + 1);
            if (action.equals("conditions")) {
                return addCondition(sessionId, parseBody(ex));
            }
            if (action.equals("advance")) {
                drainBody(ex);
                return advanceTurn(sessionId);
            }
        }
        drainBody(ex);
        return new Response(404, err("not found"));
    }

    private static void sendJson(HttpExchange ex, int code, Object body) throws IOException {
        byte[] bytes = Json.stringify(body).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static String readBody(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) != -1) {
                bos.write(buf, 0, n);
            }
            return bos.toString(StandardCharsets.UTF_8);
        }
    }

    private static void drainBody(HttpExchange ex) {
        try (InputStream is = ex.getRequestBody()) {
            byte[] buf = new byte[4096];
            while (is.read(buf) != -1) {
                // discard any request body so the connection stays usable
            }
        } catch (IOException ignored) {
        }
    }

    private static Object parseBody(HttpExchange ex) throws HttpError {
        String s;
        try {
            s = readBody(ex);
        } catch (IOException e) {
            throw new HttpError(400, "invalid body");
        }
        if (s == null || s.trim().isEmpty()) {
            throw new HttpError(400, "empty body");
        }
        try {
            return Json.parse(s);
        } catch (Exception e) {
            throw new HttpError(400, "invalid json");
        }
    }

    private static Map<String, Object> err(String msg) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("error", msg);
        return m;
    }

    // ---- endpoints ---------------------------------------------------------

    private static Response health() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", true);
        return new Response(200, m);
    }

    private static Response diceStats(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        Object exprObj = m.get("expression");
        if (!(exprObj instanceof String)) {
            throw new HttpError(400, "invalid expression");
        }
        String expr = ((String) exprObj).trim();
        java.util.regex.Matcher mt = DICE_EXPR.matcher(expr);
        if (!mt.matches()) {
            throw new HttpError(400, "invalid expression");
        }
        long count = Long.parseLong(mt.group(1));
        long sides = Long.parseLong(mt.group(2));
        long modifier = 0L;
        if (mt.group(3) != null) {
            modifier = Long.parseLong(mt.group(4));
            if (mt.group(3).equals("-")) {
                modifier = -modifier;
            }
        }
        if (count <= 0 || sides <= 0) {
            throw new HttpError(400, "invalid expression");
        }
        long min = count + modifier;
        long max = count * sides + modifier;
        double average = count * (sides + 1) / 2.0 + modifier;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("dice_count", count);
        res.put("sides", sides);
        res.put("modifier", modifier);
        res.put("min", min);
        res.put("max", max);
        res.put("average", average);
        return new Response(200, res);
    }

    private static Response abilityCheck(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        long roll = asLong(m.get("roll"));
        long modifier = asLong(m.get("modifier"));
        long dc = asLong(m.get("dc"));
        long total = roll + modifier;
        boolean success = total >= dc;
        long margin = total - dc;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("total", total);
        res.put("success", success);
        res.put("margin", margin);
        return new Response(200, res);
    }

    private static Response adjustedXp(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        Object monstersObj = m.get("monsters");
        if (!(monstersObj instanceof List)) {
            throw new HttpError(400, "invalid monsters");
        }
        @SuppressWarnings("unchecked")
        List<Object> monsters = (List<Object>) monstersObj;

        long baseXp = 0L;
        long monsterCount = 0L;
        for (Object o : monsters) {
            Map<String, Object> mo = asMap(o);
            String cr = crToString(mo.get("cr"));
            Long xp = CR_XP.get(cr);
            if (xp == null) {
                throw new HttpError(400, "unknown cr");
            }
            long cnt = asLong(mo.get("count"));
            baseXp += xp * cnt;
            monsterCount += cnt;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjusted = baseXp * multiplier;

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        Object partyObj = m.get("party");
        if (partyObj instanceof List) {
            @SuppressWarnings("unchecked")
            List<Object> party = (List<Object>) partyObj;
            for (Object o : party) {
                Map<String, Object> pm = asMap(o);
                long lvl = asLong(pm.get("level"));
                long[] t = thresholdsForLevel(lvl);
                easy += t[0];
                medium += t[1];
                hard += t[2];
                deadly += t[3];
            }
        }

        String difficulty;
        if (adjusted >= deadly) {
            difficulty = "deadly";
        } else if (adjusted >= hard) {
            difficulty = "hard";
        } else if (adjusted >= medium) {
            difficulty = "medium";
        } else if (adjusted >= easy) {
            difficulty = "easy";
        } else {
            difficulty = "trivial";
        }

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("base_xp", baseXp);
        res.put("monster_count", monsterCount);
        res.put("multiplier", multiplier);
        res.put("adjusted_xp", adjusted);
        res.put("difficulty", difficulty);
        res.put("thresholds", thresholds);
        return new Response(200, res);
    }

    private static double multiplierFor(long count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    private static long[] thresholdsForLevel(long level) {
        if (level == 3) {
            return new long[]{75L, 150L, 225L, 400L};
        }
        return new long[]{0L, 0L, 0L, 0L};
    }

    private static Response initiativeOrder(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        Object cObj = m.get("combatants");
        if (!(cObj instanceof List)) {
            throw new HttpError(400, "invalid combatants");
        }
        @SuppressWarnings("unchecked")
        List<Object> combatants = (List<Object>) cObj;

        List<Combatant> list = new ArrayList<>();
        for (Object o : combatants) {
            Map<String, Object> cm = asMap(o);
            String name = asString(cm.get("name"));
            long dex = asLong(cm.get("dex"));
            long roll = asLong(cm.get("roll"));
            list.add(new Combatant(name, dex, roll));
        }

        list.sort((a, b) -> {
            if (a.score != b.score) return Long.compare(b.score, a.score); // score desc
            if (a.dex != b.dex) return Long.compare(b.dex, a.dex);         // dex desc
            return a.name.compareTo(b.name);                               // name asc
        });

        List<Object> order = new ArrayList<>();
        for (Combatant c : list) {
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("name", c.name);
            e.put("score", c.score);
            order.add(e);
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("order", order);
        return new Response(200, res);
    }

    private static final class Combatant {
        final String name;
        final long dex;
        final long score;
        Combatant(String name, long dex, long roll) {
            this.name = name;
            this.dex = dex;
            this.score = roll + dex;
        }
    }

    // ---- combat sessions ---------------------------------------------------

    private static final class Condition {
        final String condition;
        long remaining;
        Condition(String condition, long remaining) {
            this.condition = condition;
            this.remaining = remaining;
        }
    }

    private static final class SessionCombatant {
        final String name;
        final long dex;
        final long score;
        final List<Condition> conditions = new ArrayList<>();
        SessionCombatant(String name, long dex, long score) {
            this.name = name;
            this.dex = dex;
            this.score = score;
        }
    }

    private static final class CombatSession {
        final String id;
        final List<SessionCombatant> order;
        int round;
        int turnIndex;
        CombatSession(String id, List<SessionCombatant> order) {
            this.id = id;
            this.order = order;
            this.round = 1;
            this.turnIndex = 0;
        }
    }

    private static Response createCombatSession(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        String id = requireString(m.get("id"), "id");
        Object cObj = m.get("combatants");
        if (!(cObj instanceof List)) {
            throw new HttpError(400, "invalid combatants");
        }
        @SuppressWarnings("unchecked")
        List<Object> combatants = (List<Object>) cObj;
        if (combatants.isEmpty()) {
            throw new HttpError(400, "invalid combatants");
        }
        List<SessionCombatant> list = new ArrayList<>();
        for (Object o : combatants) {
            Map<String, Object> cm = asMap(o);
            String name = requireString(cm.get("name"), "name");
            long dex = requireInt(cm.get("dex"), "dex");
            long roll = requireInt(cm.get("roll"), "roll");
            list.add(new SessionCombatant(name, dex, roll + dex));
        }
        list.sort((a, b) -> {
            if (a.score != b.score) return Long.compare(b.score, a.score); // score desc
            if (a.dex != b.dex) return Long.compare(b.dex, a.dex);         // dex desc
            return a.name.compareTo(b.name);                               // name asc
        });
        CombatSession session = new CombatSession(id, list);
        SESSIONS.put(id, session);
        return new Response(200, sessionView(session));
    }

    private static Response addCondition(String sessionId, Object body) throws HttpError {
        CombatSession session = SESSIONS.get(sessionId);
        if (session == null) {
            throw new HttpError(404, "unknown session");
        }
        synchronized (session) {
            Map<String, Object> m = asMap(body);
            String target = requireString(m.get("target"), "target");
            String condition = requireString(m.get("condition"), "condition");
            long duration = requireInt(m.get("duration_rounds"), "duration_rounds");
            if (duration <= 0) {
                throw new HttpError(400, "invalid duration_rounds");
            }
            SessionCombatant targetCombatant = null;
            for (SessionCombatant c : session.order) {
                if (c.name.equals(target)) {
                    targetCombatant = c;
                    break;
                }
            }
            if (targetCombatant == null) {
                throw new HttpError(400, "unknown target");
            }
            targetCombatant.conditions.add(new Condition(condition, duration));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("target", target);
            res.put("conditions", conditionsView(targetCombatant.conditions));
            return new Response(200, res);
        }
    }

    private static Response advanceTurn(String sessionId) throws HttpError {
        CombatSession session = SESSIONS.get(sessionId);
        if (session == null) {
            throw new HttpError(404, "unknown session");
        }
        synchronized (session) {
            int next = session.turnIndex + 1;
            if (next >= session.order.size()) {
                next = 0;
                session.round++;
            }
            session.turnIndex = next;
            SessionCombatant active = session.order.get(next);
            // At the start of this combatant's turn, tick down their conditions
            Iterator<Condition> it = active.conditions.iterator();
            while (it.hasNext()) {
                Condition c = it.next();
                c.remaining--;
                if (c.remaining <= 0) {
                    it.remove();
                }
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", session.id);
            res.put("round", (long) session.round);
            res.put("turn_index", (long) session.turnIndex);
            res.put("active", combatantView(active));
            res.put("conditions", allConditionsView(session));
            return new Response(200, res);
        }
    }

    private static Map<String, Object> sessionView(CombatSession session) {
        SessionCombatant active = session.order.get(session.turnIndex);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", session.id);
        res.put("round", (long) session.round);
        res.put("turn_index", (long) session.turnIndex);
        res.put("active", combatantView(active));
        res.put("order", orderView(session.order));
        return res;
    }

    private static Map<String, Object> combatantView(SessionCombatant c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", c.name);
        m.put("score", c.score);
        return m;
    }

    private static List<Object> orderView(List<SessionCombatant> order) {
        List<Object> list = new ArrayList<>();
        for (SessionCombatant c : order) {
            list.add(combatantView(c));
        }
        return list;
    }

    private static List<Object> conditionsView(List<Condition> conds) {
        List<Object> list = new ArrayList<>();
        for (Condition c : conds) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("condition", c.condition);
            m.put("remaining_rounds", c.remaining);
            list.add(m);
        }
        return list;
    }

    // The advance response's "conditions" map lists every combatant in the
    // initiative order, each with their (possibly empty) condition list. This
    // keeps a combatant present with an empty array after its last condition
    // expires on its own turn, which the suite checks for.
    private static Map<String, Object> allConditionsView(CombatSession session) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (SessionCombatant c : session.order) {
            map.put(c.name, conditionsView(c.conditions));
        }
        return map;
    }

    // ---- character rules ---------------------------------------------------

    private static long abilityMod(long score) {
        return Math.floorDiv(score - 10L, 2L);
    }

    private static long proficiencyBonus(long level) {
        if (level <= 4) return 2L;
        if (level <= 8) return 3L;
        if (level <= 12) return 4L;
        if (level <= 16) return 5L;
        return 6L;
    }

    private static Response abilityModifier(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        long score = requireInt(m.get("score"), "score");
        if (score < 1 || score > 30) {
            throw new HttpError(400, "score out of range");
        }
        long modifier = abilityMod(score);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("score", score);
        res.put("modifier", modifier);
        return new Response(200, res);
    }

    private static Response proficiency(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        long level = requireInt(m.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new HttpError(400, "level out of range");
        }
        long bonus = proficiencyBonus(level);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("level", level);
        res.put("proficiency_bonus", bonus);
        return new Response(200, res);
    }

    private static Response derivedStats(Object body) throws HttpError {
        Map<String, Object> m = asMap(body);
        long level = requireInt(m.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new HttpError(400, "level out of range");
        }
        Map<String, Object> abilities = asMap(m.get("abilities"));
        long str = requireInt(abilities.get("str"), "str");
        long dex = requireInt(abilities.get("dex"), "dex");
        long con = requireInt(abilities.get("con"), "con");
        long intel = requireInt(abilities.get("int"), "int");
        long wis = requireInt(abilities.get("wis"), "wis");
        long cha = requireInt(abilities.get("cha"), "cha");

        Map<String, Object> armor = asMap(m.get("armor"));
        long base = requireInt(armor.get("base"), "base");
        boolean shield = asBool(armor.get("shield"));
        long dexCap = requireInt(armor.get("dex_cap"), "dex_cap");

        long conMod = abilityMod(con);
        long dexMod = abilityMod(dex);
        long proficiency = proficiencyBonus(level);
        long hpMax = level * (6L + conMod);
        long shieldBonus = shield ? 2L : 0L;
        long armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;

        Map<String, Object> mods = new LinkedHashMap<>();
        mods.put("str", abilityMod(str));
        mods.put("dex", dexMod);
        mods.put("con", conMod);
        mods.put("int", abilityMod(intel));
        mods.put("wis", abilityMod(wis));
        mods.put("cha", abilityMod(cha));

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("level", level);
        res.put("proficiency_bonus", proficiency);
        res.put("hp_max", hpMax);
        res.put("armor_class", armorClass);
        res.put("modifiers", mods);
        return new Response(200, res);
    }

    // ---- coercion helpers --------------------------------------------------

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) throws HttpError {
        if (!(o instanceof Map)) {
            throw new HttpError(400, "invalid object");
        }
        return (Map<String, Object>) o;
    }

    private static long asLong(Object o) {
        if (o == null) return 0L;
        if (o instanceof Long) return (Long) o;
        if (o instanceof Double) return ((Double) o).longValue();
        if (o instanceof String) {
            try {
                return Long.parseLong(((String) o).trim());
            } catch (Exception ignored) {
                return 0L;
            }
        }
        if (o instanceof Boolean) return ((Boolean) o) ? 1L : 0L;
        return 0L;
    }

    private static String asString(Object o) {
        return o == null ? "" : o.toString();
    }

    private static String requireString(Object o, String field) throws HttpError {
        if (!(o instanceof String) || ((String) o).isEmpty()) {
            throw new HttpError(400, "invalid " + field);
        }
        return (String) o;
    }

    private static long requireInt(Object o, String field) throws HttpError {
        if (o == null) throw new HttpError(400, "invalid " + field);
        if (o instanceof Long) return (Long) o;
        if (o instanceof Double) {
            double d = (Double) o;
            if (Double.isInfinite(d) || Double.isNaN(d) || d != Math.floor(d)) {
                throw new HttpError(400, "invalid " + field);
            }
            return (long) d;
        }
        throw new HttpError(400, "invalid " + field);
    }

    private static boolean asBool(Object o) {
        if (o instanceof Boolean) return (Boolean) o;
        return false;
    }

    private static String crToString(Object o) throws HttpError {
        if (o == null) throw new HttpError(400, "invalid cr");
        if (o instanceof String) return ((String) o).trim();
        if (o instanceof Long) return Long.toString((Long) o);
        if (o instanceof Double) {
            double d = (Double) o;
            if (d == Math.floor(d) && !Double.isInfinite(d)) {
                return Long.toString((long) d);
            }
            return Double.toString(d);
        }
        throw new HttpError(400, "invalid cr");
    }

    // ---- minimal JSON ------------------------------------------------------

    private static final class Json {
        private Json() {}

        static Object parse(String s) throws Exception {
            Parser p = new Parser(s);
            p.skipWs();
            Object v = p.parseValue();
            p.skipWs();
            if (p.pos < p.src.length()) {
                throw new Exception("trailing content");
            }
            return v;
        }

        static String stringify(Object v) {
            StringBuilder sb = new StringBuilder();
            writeValue(sb, v);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(StringBuilder sb, Object v) {
            if (v == null) {
                sb.append("null");
            } else if (v instanceof Map) {
                Map<String, Object> m = (Map<String, Object>) v;
                sb.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> e : m.entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    writeString(sb, e.getKey());
                    sb.append(':');
                    writeValue(sb, e.getValue());
                }
                sb.append('}');
            } else if (v instanceof List) {
                List<Object> a = (List<Object>) v;
                sb.append('[');
                boolean first = true;
                for (Object o : a) {
                    if (!first) sb.append(',');
                    first = false;
                    writeValue(sb, o);
                }
                sb.append(']');
            } else if (v instanceof String) {
                writeString(sb, (String) v);
            } else if (v instanceof Boolean) {
                sb.append(((Boolean) v) ? "true" : "false");
            } else if (v instanceof Long) {
                sb.append(((Long) v).toString());
            } else if (v instanceof Double) {
                double d = (Double) v;
                if (Double.isInfinite(d) || Double.isNaN(d)) {
                    sb.append("null");
                } else if (d == Math.floor(d) && Math.abs(d) < 1e15) {
                    sb.append(Long.toString((long) d));
                } else {
                    sb.append(Double.toString(d));
                }
            } else {
                writeString(sb, v.toString());
            }
        }

        private static void writeString(StringBuilder sb, String s) {
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"':  sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\b': sb.append("\\b");  break;
                    case '\f': sb.append("\\f");  break;
                    case '\n': sb.append("\\n");  break;
                    case '\r': sb.append("\\r");  break;
                    case '\t': sb.append("\\t");  break;
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

        private static final class Parser {
            final String src;
            int pos;

            Parser(String s) {
                this.src = s;
                this.pos = 0;
            }

            void skipWs() {
                while (pos < src.length()
                        && Character.isWhitespace(src.charAt(pos))) {
                    pos++;
                }
            }

            Object parseValue() throws Exception {
                skipWs();
                if (pos >= src.length()) throw new Exception("unexpected end");
                char c = src.charAt(pos);
                switch (c) {
                    case '{': return parseObject();
                    case '[': return parseArray();
                    case '"': return parseString();
                    case 't': case 'f': return parseBool();
                    case 'n': return parseNull();
                    default:  return parseNumber();
                }
            }

            Map<String, Object> parseObject() throws Exception {
                Map<String, Object> m = new LinkedHashMap<>();
                expect('{');
                skipWs();
                if (peek() == '}') { pos++; return m; }
                while (true) {
                    skipWs();
                    String key = parseString();
                    skipWs();
                    expect(':');
                    Object val = parseValue();
                    m.put(key, val);
                    skipWs();
                    char c = next();
                    if (c == ',') continue;
                    if (c == '}') break;
                    throw new Exception("expected , or }");
                }
                return m;
            }

            List<Object> parseArray() throws Exception {
                List<Object> a = new ArrayList<>();
                expect('[');
                skipWs();
                if (peek() == ']') { pos++; return a; }
                while (true) {
                    Object val = parseValue();
                    a.add(val);
                    skipWs();
                    char c = next();
                    if (c == ',') continue;
                    if (c == ']') break;
                    throw new Exception("expected , or ]");
                }
                return a;
            }

            String parseString() throws Exception {
                expect('"');
                StringBuilder sb = new StringBuilder();
                while (true) {
                    if (pos >= src.length()) throw new Exception("unterminated string");
                    char c = src.charAt(pos++);
                    if (c == '"') break;
                    if (c == '\\') {
                        if (pos >= src.length()) throw new Exception("bad escape");
                        char e = src.charAt(pos++);
                        switch (e) {
                            case '"':  sb.append('"');  break;
                            case '\\': sb.append('\\'); break;
                            case '/':  sb.append('/');  break;
                            case 'b':  sb.append('\b'); break;
                            case 'f':  sb.append('\f'); break;
                            case 'n':  sb.append('\n'); break;
                            case 'r':  sb.append('\r'); break;
                            case 't':  sb.append('\t'); break;
                            case 'u':
                                if (pos + 4 > src.length()) {
                                    throw new Exception("bad unicode escape");
                                }
                                sb.append((char) Integer.parseInt(src.substring(pos, pos + 4), 16));
                                pos += 4;
                                break;
                            default: throw new Exception("bad escape");
                        }
                    } else {
                        sb.append(c);
                    }
                }
                return sb.toString();
            }

            Object parseNumber() throws Exception {
                int start = pos;
                char c = peek();
                if (c == '-' || c == '+') pos++;
                while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
                boolean isDouble = false;
                if (pos < src.length() && src.charAt(pos) == '.') {
                    isDouble = true;
                    pos++;
                    while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
                }
                if (pos < src.length()
                        && (src.charAt(pos) == 'e' || src.charAt(pos) == 'E')) {
                    isDouble = true;
                    pos++;
                    if (pos < src.length()
                            && (src.charAt(pos) == '+' || src.charAt(pos) == '-')) {
                        pos++;
                    }
                    while (pos < src.length() && Character.isDigit(src.charAt(pos))) pos++;
                }
                String num = src.substring(start, pos);
                if (num.isEmpty() || num.equals("-") || num.equals("+")) {
                    throw new Exception("invalid number");
                }
                try {
                    if (isDouble) return Double.parseDouble(num);
                    return Long.parseLong(num);
                } catch (NumberFormatException ex) {
                    throw new Exception("invalid number");
                }
            }

            Boolean parseBool() throws Exception {
                if (src.startsWith("true", pos)) { pos += 4; return Boolean.TRUE; }
                if (src.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
                throw new Exception("invalid literal");
            }

            Object parseNull() throws Exception {
                if (src.startsWith("null", pos)) { pos += 4; return null; }
                throw new Exception("invalid literal");
            }

            char peek() {
                return pos < src.length() ? src.charAt(pos) : '\0';
            }

            char next() throws Exception {
                if (pos >= src.length()) throw new Exception("unexpected end");
                return src.charAt(pos++);
            }

            void expect(char c) throws Exception {
                if (next() != c) throw new Exception("expected " + c);
            }
        }
    }
}
