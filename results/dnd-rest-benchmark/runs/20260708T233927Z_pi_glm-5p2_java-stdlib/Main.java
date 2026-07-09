import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {

    // ------------------------------------------------------------------ setup

    public static void main(String[] args) throws IOException {
        int port = 8080;
        String portEnv = System.getenv("PORT");
        if (portEnv != null && !portEnv.isEmpty()) {
            port = Integer.parseInt(portEnv.trim());
        }
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/dice/stats", new DiceStatsHandler());
        server.createContext("/v1/checks/ability", new AbilityCheckHandler());
        server.createContext("/v1/encounters/adjusted-xp", new AdjustedXpHandler());
        server.createContext("/v1/initiative/order", new InitiativeHandler());
        server.createContext("/", new NotFoundHandler());
        server.setExecutor(null);
        server.start();
        System.err.println("D&D REST engine listening on 127.0.0.1:" + port);
    }

    // --------------------------------------------------------------- handlers

    static class HealthHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!pathIs(ex, "/health")) { sendCode(ex, 404); return; }
            if (!ex.getRequestMethod().equals("GET")) { sendCode(ex, 405); return; }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("ok", true);
            sendJson(ex, 200, res);
        }
    }

    static class DiceStatsHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!pathIs(ex, "/v1/dice/stats")) { sendCode(ex, 404); return; }
            if (!ex.getRequestMethod().equals("POST")) { sendCode(ex, 405); return; }
            try {
                Map<String, Object> req = asMap(Json.parse(readBody(ex)));
                sendJson(ex, 200, diceStats(asString(req.get("expression"))));
            } catch (Exception e) {
                sendJson(ex, 400, errBody(e));
            }
        }
    }

    static class AbilityCheckHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!pathIs(ex, "/v1/checks/ability")) { sendCode(ex, 404); return; }
            if (!ex.getRequestMethod().equals("POST")) { sendCode(ex, 405); return; }
            try {
                Map<String, Object> req = asMap(Json.parse(readBody(ex)));
                long roll = asLong(req.get("roll"));
                long modifier = asLong(req.get("modifier"));
                long dc = asLong(req.get("dc"));
                long total = roll + modifier;
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("total", total);
                res.put("success", total >= dc);
                res.put("margin", total - dc);
                sendJson(ex, 200, res);
            } catch (Exception e) {
                sendJson(ex, 400, errBody(e));
            }
        }
    }

    static class AdjustedXpHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!pathIs(ex, "/v1/encounters/adjusted-xp")) { sendCode(ex, 404); return; }
            if (!ex.getRequestMethod().equals("POST")) { sendCode(ex, 405); return; }
            try {
                sendJson(ex, 200, adjustedXp(Json.parse(readBody(ex))));
            } catch (Exception e) {
                sendJson(ex, 400, errBody(e));
            }
        }
    }

    static class InitiativeHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!pathIs(ex, "/v1/initiative/order")) { sendCode(ex, 404); return; }
            if (!ex.getRequestMethod().equals("POST")) { sendCode(ex, 405); return; }
            try {
                sendJson(ex, 200, initiative(Json.parse(readBody(ex))));
            } catch (Exception e) {
                sendJson(ex, 400, errBody(e));
            }
        }
    }

    static class NotFoundHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            sendCode(ex, 404);
        }
    }

    // -------------------------------------------------------------- endpoints

    private static final Pattern DICE = Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

    static Object diceStats(String expr) {
        if (expr == null) throw new Bad("missing expression");
        Matcher m = DICE.matcher(expr);
        if (!m.matches()) throw new Bad("invalid expression");
        long count = Long.parseLong(m.group(1));
        long sides = Long.parseLong(m.group(2));
        if (count <= 0 || sides <= 0) throw new Bad("invalid expression");
        long modifier = 0;
        if (m.group(3) != null) {
            modifier = Long.parseLong(m.group(4));
            if (m.group(3).equals("-")) modifier = -modifier;
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
        return res;
    }

    private static final Map<String, Long> CR_XP = new HashMap<>();
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

    // level -> {easy, medium, hard, deadly}
    private static final Map<Long, long[]> LEVEL_THRESH = new HashMap<>();
    static {
        LEVEL_THRESH.put(3L, new long[]{75, 150, 225, 400});
    }

    static double multiplierFor(long count) {
        if (count <= 0) return 1.0;
        if (count == 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    @SuppressWarnings("unchecked")
    static Object adjustedXp(Object body) {
        Map<String, Object> req = asMap(body);
        List<Object> party = asList(req.get("party"));
        List<Object> monsters = asList(req.get("monsters"));

        long baseXp = 0;
        long monsterCount = 0;
        for (Object mo : monsters) {
            Map<String, Object> mm = asMap(mo);
            String cr = asString(mm.get("cr"));
            long count = asLong(mm.get("count"));
            Long xp = CR_XP.get(cr);
            if (xp == null) throw new Bad("unknown cr: " + cr);
            if (count < 0) throw new Bad("negative count");
            baseXp += xp * count;
            monsterCount += count;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjusted = baseXp * multiplier;

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object po : party) {
            Map<String, Object> pm = asMap(po);
            long level = asLong(pm.get("level"));
            long[] t = LEVEL_THRESH.get(level);
            if (t == null) t = LEVEL_THRESH.get(3L);
            easy += t[0];
            medium += t[1];
            hard += t[2];
            deadly += t[3];
        }

        String difficulty;
        if (adjusted >= deadly) difficulty = "deadly";
        else if (adjusted >= hard) difficulty = "hard";
        else if (adjusted >= medium) difficulty = "medium";
        else if (adjusted >= easy) difficulty = "easy";
        else difficulty = "trivial";

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
        return res;
    }

    @SuppressWarnings("unchecked")
    static Object initiative(Object body) {
        Map<String, Object> req = asMap(body);
        List<Object> combatants = asList(req.get("combatants"));
        List<Map<String, Object>> list = new ArrayList<>();
        for (Object co : combatants) list.add(asMap(co));

        list.sort((a, b) -> {
            long sa = asLong(a.get("roll")) + asLong(a.get("dex"));
            long sb = asLong(b.get("roll")) + asLong(b.get("dex"));
            if (sb != sa) return Long.compare(sb, sa);          // score desc
            long da = asLong(a.get("dex"));
            long db = asLong(b.get("dex"));
            if (db != da) return Long.compare(db, da);          // dex desc
            return asString(a.get("name")).compareTo(asString(b.get("name"))); // name asc
        });

        List<Object> order = new ArrayList<>();
        for (Map<String, Object> c : list) {
            long score = asLong(c.get("roll")) + asLong(c.get("dex"));
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("name", asString(c.get("name")));
            e.put("score", score);
            order.add(e);
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("order", order);
        return res;
    }

    // ---------------------------------------------------------------- helpers

    static boolean pathIs(HttpExchange ex, String p) {
        return p.equals(ex.getRequestURI().getPath());
    }

    static String readBody(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            return new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static void sendJson(HttpExchange ex, int code, Object json) throws IOException {
        byte[] body = Json.serialize(json).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    static void sendCode(HttpExchange ex, int code) throws IOException {
        byte[] body = "{}".getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    static Object errBody(Exception e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("error", e.getMessage() == null ? "bad request" : e.getMessage());
        return m;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> asMap(Object o) {
        if (!(o instanceof Map)) throw new Bad("expected object");
        return (Map<String, Object>) o;
    }

    @SuppressWarnings("unchecked")
    static List<Object> asList(Object o) {
        if (!(o instanceof List)) throw new Bad("expected array");
        return (List<Object>) o;
    }

    static long asLong(Object o) {
        if (o instanceof Long) return (Long) o;
        if (o instanceof Integer) return (Integer) o;
        if (o instanceof Double) {
            double d = (Double) o;
            if (d == Math.rint(d) && !Double.isInfinite(d)) return (long) d;
            throw new Bad("expected integer");
        }
        if (o == null) throw new Bad("missing value");
        throw new Bad("expected number");
    }

    static String asString(Object o) {
        if (o instanceof String) return (String) o;
        if (o == null) throw new Bad("missing value");
        throw new Bad("expected string");
    }

    static class Bad extends RuntimeException {
        Bad(String msg) { super(msg); }
    }

    // --------------------------------------------------------------- JSON I/O

    static final class Json {
        static Object parse(String s) {
            Parser p = new Parser(s);
            p.skipWs();
            Object v = p.parseValue();
            p.skipWs();
            if (p.pos != p.s.length()) throw new Bad("trailing content");
            return v;
        }

        static String serialize(Object o) {
            StringBuilder sb = new StringBuilder();
            writeValue(sb, o);
            return sb.toString();
        }

        static void writeValue(StringBuilder sb, Object o) {
            if (o == null) sb.append("null");
            else if (o instanceof Boolean) sb.append(((Boolean) o) ? "true" : "false");
            else if (o instanceof Long) sb.append(((Long) o).longValue());
            else if (o instanceof Integer) sb.append(((Integer) o).intValue());
            else if (o instanceof Double) {
                double d = (Double) o;
                if (d == Math.rint(d) && !Double.isInfinite(d) && Math.abs(d) < 1e15) {
                    sb.append(Long.toString((long) d));
                } else {
                    sb.append(Double.toString(d));
                }
            } else if (o instanceof String) writeString(sb, (String) o);
            else if (o instanceof Map) writeObject(sb, (Map<String, Object>) o);
            else if (o instanceof List) writeArray(sb, (List<Object>) o);
            else throw new Bad("cannot serialize " + o.getClass());
        }

        static void writeString(StringBuilder sb, String s) {
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
        }

        @SuppressWarnings("unchecked")
        static void writeObject(StringBuilder sb, Map<String, Object> m) {
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
        }

        @SuppressWarnings("unchecked")
        static void writeArray(StringBuilder sb, List<Object> l) {
            sb.append('[');
            boolean first = true;
            for (Object o : l) {
                if (!first) sb.append(',');
                first = false;
                writeValue(sb, o);
            }
            sb.append(']');
        }

        static final class Parser {
            final String s;
            int pos;

            Parser(String s) { this.s = s; }

            void skipWs() {
                while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) pos++;
            }

            Object parseValue() {
                skipWs();
                if (pos >= s.length()) throw new Bad("unexpected end of input");
                char c = s.charAt(pos);
                switch (c) {
                    case '{': return parseObject();
                    case '[': return parseArray();
                    case '"': return parseString();
                    case 't': case 'f': return parseBool();
                    case 'n': return parseNull();
                    default:
                        if (c == '-' || (c >= '0' && c <= '9')) return parseNumber();
                        throw new Bad("unexpected char '" + c + "'");
                }
            }

            Map<String, Object> parseObject() {
                Map<String, Object> m = new LinkedHashMap<>();
                pos++; // consume '{'
                skipWs();
                if (pos < s.length() && s.charAt(pos) == '}') { pos++; return m; }
                while (true) {
                    skipWs();
                    if (pos >= s.length() || s.charAt(pos) != '"') throw new Bad("expected key");
                    String key = parseString();
                    skipWs();
                    if (pos >= s.length() || s.charAt(pos) != ':') throw new Bad("expected ':'");
                    pos++;
                    Object val = parseValue();
                    m.put(key, val);
                    skipWs();
                    if (pos >= s.length()) throw new Bad("unterminated object");
                    char c = s.charAt(pos);
                    if (c == ',') { pos++; continue; }
                    if (c == '}') { pos++; break; }
                    throw new Bad("expected ',' or '}'");
                }
                return m;
            }

            List<Object> parseArray() {
                List<Object> l = new ArrayList<>();
                pos++; // consume '['
                skipWs();
                if (pos < s.length() && s.charAt(pos) == ']') { pos++; return l; }
                while (true) {
                    Object val = parseValue();
                    l.add(val);
                    skipWs();
                    if (pos >= s.length()) throw new Bad("unterminated array");
                    char c = s.charAt(pos);
                    if (c == ',') { pos++; continue; }
                    if (c == ']') { pos++; break; }
                    throw new Bad("expected ',' or ']'");
                }
                return l;
            }

            String parseString() {
                pos++; // consume opening '"'
                StringBuilder sb = new StringBuilder();
                while (true) {
                    if (pos >= s.length()) throw new Bad("unterminated string");
                    char c = s.charAt(pos++);
                    if (c == '"') break;
                    if (c == '\\') {
                        if (pos >= s.length()) throw new Bad("bad escape");
                        char e = s.charAt(pos++);
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
                                if (pos + 4 > s.length()) throw new Bad("bad unicode escape");
                                sb.append((char) Integer.parseInt(s.substring(pos, pos + 4), 16));
                                pos += 4;
                                break;
                            default: throw new Bad("bad escape '\\" + e + "'");
                        }
                    } else if (c < 0x20) {
                        throw new Bad("control char in string");
                    } else {
                        sb.append(c);
                    }
                }
                return sb.toString();
            }

            Object parseBool() {
                if (s.startsWith("true", pos)) { pos += 4; return Boolean.TRUE; }
                if (s.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
                throw new Bad("bad literal");
            }

            Object parseNull() {
                if (s.startsWith("null", pos)) { pos += 4; return null; }
                throw new Bad("bad literal");
            }

            Object parseNumber() {
                int start = pos;
                if (pos < s.length() && s.charAt(pos) == '-') pos++;
                while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
                boolean isDouble = false;
                if (pos < s.length() && s.charAt(pos) == '.') {
                    isDouble = true; pos++;
                    while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
                }
                if (pos < s.length() && (s.charAt(pos) == 'e' || s.charAt(pos) == 'E')) {
                    isDouble = true; pos++;
                    if (pos < s.length() && (s.charAt(pos) == '+' || s.charAt(pos) == '-')) pos++;
                    while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
                }
                String num = s.substring(start, pos);
                if (isDouble) return Double.parseDouble(num);
                return Long.parseLong(num);
            }
        }
    }
}
