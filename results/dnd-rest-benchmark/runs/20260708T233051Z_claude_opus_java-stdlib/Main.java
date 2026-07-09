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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {

    // ---- Static data tables ----
    static final Map<String, Integer> CR_XP = new LinkedHashMap<>();
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

    // Level-3 thresholds
    static final Map<Integer, int[]> LEVEL_THRESHOLDS = new LinkedHashMap<>();
    static {
        // easy, medium, hard, deadly
        LEVEL_THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
    }

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);

        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/dice/stats", new DiceStatsHandler());
        server.createContext("/v1/checks/ability", new AbilityHandler());
        server.createContext("/v1/encounters/adjusted-xp", new EncounterHandler());
        server.createContext("/v1/initiative/order", new InitiativeHandler());

        server.setExecutor(null);
        server.start();
    }

    // ---- Handlers ----

    static class HealthHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!ex.getRequestMethod().equalsIgnoreCase("GET")) {
                send(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            send(ex, 200, "{\"ok\":true}");
        }
    }

    static final Pattern DICE = Pattern.compile("^\\s*(\\d+)d(\\d+)([+-]\\d+)?\\s*$");

    static class DiceStatsHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
                send(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Object parsed = Json.parse(readBody(ex));
                if (!(parsed instanceof Map)) { send(ex, 400, err("invalid body")); return; }
                Map<?, ?> body = (Map<?, ?>) parsed;
                Object exprObj = body.get("expression");
                if (!(exprObj instanceof String)) { send(ex, 400, err("missing expression")); return; }
                Matcher m = DICE.matcher((String) exprObj);
                if (!m.matches()) { send(ex, 400, err("invalid expression")); return; }
                long count = Long.parseLong(m.group(1));
                long sides = Long.parseLong(m.group(2));
                long modifier = m.group(3) == null ? 0 : Long.parseLong(m.group(3).replace("+", ""));
                if (count <= 0 || sides <= 0) { send(ex, 400, err("invalid expression")); return; }

                long min = count * 1 + modifier;
                long max = count * sides + modifier;
                double average = (min + max) / 2.0;

                StringBuilder sb = new StringBuilder();
                sb.append("{");
                sb.append("\"dice_count\":").append(count).append(",");
                sb.append("\"sides\":").append(sides).append(",");
                sb.append("\"modifier\":").append(modifier).append(",");
                sb.append("\"min\":").append(min).append(",");
                sb.append("\"max\":").append(max).append(",");
                sb.append("\"average\":").append(Json.num(average));
                sb.append("}");
                send(ex, 200, sb.toString());
            } catch (Exception e) {
                send(ex, 400, err("invalid request"));
            }
        }
    }

    static class AbilityHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
                send(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Object parsed = Json.parse(readBody(ex));
                if (!(parsed instanceof Map)) { send(ex, 400, err("invalid body")); return; }
                Map<?, ?> body = (Map<?, ?>) parsed;
                long roll = asLong(body.get("roll"));
                long modifier = asLong(body.get("modifier"));
                long dc = asLong(body.get("dc"));
                long total = roll + modifier;
                boolean success = total >= dc;
                long margin = total - dc;
                String out = "{\"total\":" + total + ",\"success\":" + success + ",\"margin\":" + margin + "}";
                send(ex, 200, out);
            } catch (Exception e) {
                send(ex, 400, err("invalid request"));
            }
        }
    }

    static class EncounterHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
                send(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Object parsed = Json.parse(readBody(ex));
                if (!(parsed instanceof Map)) { send(ex, 400, err("invalid body")); return; }
                Map<?, ?> body = (Map<?, ?>) parsed;

                Object partyObj = body.get("party");
                Object monstersObj = body.get("monsters");
                if (!(partyObj instanceof List) || !(monstersObj instanceof List)) {
                    send(ex, 400, err("invalid body")); return;
                }
                List<?> party = (List<?>) partyObj;
                List<?> monsters = (List<?>) monstersObj;

                long baseXp = 0;
                long monsterCount = 0;
                for (Object mo : monsters) {
                    if (!(mo instanceof Map)) { send(ex, 400, err("invalid monster")); return; }
                    Map<?, ?> mon = (Map<?, ?>) mo;
                    Object crObj = mon.get("cr");
                    if (!(crObj instanceof String)) { send(ex, 400, err("invalid cr")); return; }
                    String cr = (String) crObj;
                    if (!CR_XP.containsKey(cr)) { send(ex, 400, err("unknown cr")); return; }
                    long cnt = asLong(mon.get("count"));
                    baseXp += (long) CR_XP.get(cr) * cnt;
                    monsterCount += cnt;
                }

                double multiplier = multiplierFor(monsterCount);
                double adjustedXpD = baseXp * multiplier;
                long adjustedXp = (long) adjustedXpD;

                // Sum thresholds across party members
                long easy = 0, medium = 0, hard = 0, deadly = 0;
                for (Object po : party) {
                    if (!(po instanceof Map)) { send(ex, 400, err("invalid party member")); return; }
                    Map<?, ?> pm = (Map<?, ?>) po;
                    int level = (int) asLong(pm.get("level"));
                    int[] t = LEVEL_THRESHOLDS.get(level);
                    if (t == null) { send(ex, 400, err("unsupported level")); return; }
                    easy += t[0]; medium += t[1]; hard += t[2]; deadly += t[3];
                }

                String difficulty;
                if (adjustedXp >= deadly) difficulty = "deadly";
                else if (adjustedXp >= hard) difficulty = "hard";
                else if (adjustedXp >= medium) difficulty = "medium";
                else if (adjustedXp >= easy) difficulty = "easy";
                else difficulty = "trivial";

                StringBuilder sb = new StringBuilder();
                sb.append("{");
                sb.append("\"base_xp\":").append(baseXp).append(",");
                sb.append("\"monster_count\":").append(monsterCount).append(",");
                sb.append("\"multiplier\":").append(Json.num(multiplier)).append(",");
                sb.append("\"adjusted_xp\":").append(adjustedXp).append(",");
                sb.append("\"difficulty\":\"").append(difficulty).append("\",");
                sb.append("\"thresholds\":{");
                sb.append("\"easy\":").append(easy).append(",");
                sb.append("\"medium\":").append(medium).append(",");
                sb.append("\"hard\":").append(hard).append(",");
                sb.append("\"deadly\":").append(deadly);
                sb.append("}");
                sb.append("}");
                send(ex, 200, sb.toString());
            } catch (Exception e) {
                send(ex, 400, err("invalid request"));
            }
        }
    }

    static double multiplierFor(long count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    static class InitiativeHandler implements HttpHandler {
        public void handle(HttpExchange ex) throws IOException {
            if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
                send(ex, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            try {
                Object parsed = Json.parse(readBody(ex));
                if (!(parsed instanceof Map)) { send(ex, 400, err("invalid body")); return; }
                Map<?, ?> body = (Map<?, ?>) parsed;
                Object combatantsObj = body.get("combatants");
                if (!(combatantsObj instanceof List)) { send(ex, 400, err("invalid body")); return; }
                List<?> combatants = (List<?>) combatantsObj;

                List<Combatant> list = new ArrayList<>();
                for (Object co : combatants) {
                    if (!(co instanceof Map)) { send(ex, 400, err("invalid combatant")); return; }
                    Map<?, ?> c = (Map<?, ?>) co;
                    Object nameObj = c.get("name");
                    if (!(nameObj instanceof String)) { send(ex, 400, err("invalid name")); return; }
                    long dex = asLong(c.get("dex"));
                    long roll = asLong(c.get("roll"));
                    list.add(new Combatant((String) nameObj, dex, roll));
                }

                list.sort(Comparator
                        .comparingLong((Combatant c) -> c.score).reversed()
                        .thenComparing(Comparator.comparingLong((Combatant c) -> c.dex).reversed())
                        .thenComparing(c -> c.name));

                StringBuilder sb = new StringBuilder();
                sb.append("{\"order\":[");
                for (int i = 0; i < list.size(); i++) {
                    Combatant c = list.get(i);
                    if (i > 0) sb.append(",");
                    sb.append("{\"name\":").append(Json.str(c.name)).append(",\"score\":").append(c.score).append("}");
                }
                sb.append("]}");
                send(ex, 200, sb.toString());
            } catch (Exception e) {
                send(ex, 400, err("invalid request"));
            }
        }
    }

    static class Combatant {
        final String name;
        final long dex;
        final long roll;
        final long score;
        Combatant(String name, long dex, long roll) {
            this.name = name; this.dex = dex; this.roll = roll; this.score = roll + dex;
        }
    }

    // ---- Helpers ----

    static long asLong(Object o) {
        if (o instanceof Number) return ((Number) o).longValue();
        throw new IllegalArgumentException("expected number");
    }

    static String err(String msg) {
        return "{\"error\":" + Json.str(msg) + "}";
    }

    static String readBody(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            return new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static void send(HttpExchange ex, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    // ---- Minimal JSON parser ----
    static class Json {
        private final String s;
        private int i;
        private Json(String s) { this.s = s; }

        static Object parse(String s) {
            Json j = new Json(s);
            j.ws();
            Object v = j.value();
            j.ws();
            if (j.i != s.length()) throw new IllegalArgumentException("trailing content");
            return v;
        }

        private void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        private Object value() {
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': case 'f': return bool();
                case 'n': return nullVal();
                default: return number();
            }
        }

        private Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; // {
            ws();
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws();
                String key = string();
                ws();
                if (s.charAt(i) != ':') throw new IllegalArgumentException("expected :");
                i++;
                ws();
                Object v = value();
                m.put(key, v);
                ws();
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == '}') { i++; break; }
                throw new IllegalArgumentException("expected , or }");
            }
            return m;
        }

        private List<Object> array() {
            List<Object> list = new ArrayList<>();
            i++; // [
            ws();
            if (s.charAt(i) == ']') { i++; return list; }
            while (true) {
                ws();
                list.add(value());
                ws();
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == ']') { i++; break; }
                throw new IllegalArgumentException("expected , or ]");
            }
            return list;
        }

        private String string() {
            if (s.charAt(i) != '"') throw new IllegalArgumentException("expected string");
            i++;
            StringBuilder sb = new StringBuilder();
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') break;
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
                        default: throw new IllegalArgumentException("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object bool() {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            throw new IllegalArgumentException("bad literal");
        }

        private Object nullVal() {
            if (s.startsWith("null", i)) { i += 4; return null; }
            throw new IllegalArgumentException("bad literal");
        }

        private Object number() {
            int start = i;
            if (s.charAt(i) == '-') i++;
            while (i < s.length()) {
                char c = s.charAt(i);
                if ((c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') i++;
                else break;
            }
            String numStr = s.substring(start, i);
            if (numStr.contains(".") || numStr.contains("e") || numStr.contains("E")) {
                return Double.parseDouble(numStr);
            }
            return Long.parseLong(numStr);
        }

        // ---- serialization helpers ----
        static String str(String v) {
            StringBuilder sb = new StringBuilder();
            sb.append('"');
            for (int k = 0; k < v.length(); k++) {
                char c = v.charAt(k);
                switch (c) {
                    case '"': sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    case '\b': sb.append("\\b"); break;
                    case '\f': sb.append("\\f"); break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            sb.append('"');
            return sb.toString();
        }

        static String num(double d) {
            if (d == Math.rint(d) && !Double.isInfinite(d)) {
                return Long.toString((long) d);
            }
            return Double.toString(d);
        }
    }
}
