import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", Main::handleHealth);
        server.createContext("/v1/dice/stats", Main::handleDiceStats);
        server.createContext("/v1/checks/ability", Main::handleAbilityCheck);
        server.createContext("/v1/encounters/adjusted-xp", Main::handleAdjustedXp);
        server.createContext("/v1/initiative/order", Main::handleInitiativeOrder);
        server.setExecutor(null);
        server.start();
        System.out.println("Listening on 127.0.0.1:" + port);
    }

    // ---------- Handlers ----------

    private static void handleHealth(HttpExchange ex) throws IOException {
        if (!ex.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        sendJson(ex, 200, "{\"ok\":true}");
    }

    private static final Pattern DICE_PATTERN =
            Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

    private static void handleDiceStats(HttpExchange ex) throws IOException {
        if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        try {
            Object body = JsonParser.parse(readBody(ex));
            Map<String, Object> reqMap = asMap(body);
            Object exprObj = reqMap.get("expression");
            if (!(exprObj instanceof String)) {
                sendJson(ex, 400, "{\"error\":\"invalid expression\"}");
                return;
            }
            String expr = ((String) exprObj).trim();
            Matcher m = DICE_PATTERN.matcher(expr);
            if (!m.matches()) {
                sendJson(ex, 400, "{\"error\":\"invalid expression\"}");
                return;
            }
            long count = Long.parseLong(m.group(1));
            long sides = Long.parseLong(m.group(2));
            long modifier = 0;
            if (m.group(3) != null) {
                long modVal = Long.parseLong(m.group(4));
                modifier = m.group(3).equals("-") ? -modVal : modVal;
            }
            if (count <= 0 || sides <= 0) {
                sendJson(ex, 400, "{\"error\":\"invalid expression\"}");
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
            resp.put("average", numberValue(average));
            sendJson(ex, 200, JsonWriter.write(resp));
        } catch (Exception e) {
            sendJson(ex, 400, "{\"error\":\"invalid request\"}");
        }
    }

    private static void handleAbilityCheck(HttpExchange ex) throws IOException {
        if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        try {
            Object body = JsonParser.parse(readBody(ex));
            Map<String, Object> reqMap = asMap(body);
            double roll = toDouble(reqMap.get("roll"));
            double modifier = toDouble(reqMap.get("modifier"));
            double dc = toDouble(reqMap.get("dc"));

            double total = roll + modifier;
            boolean success = total >= dc;
            double margin = total - dc;

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("total", numberValue(total));
            resp.put("success", success);
            resp.put("margin", numberValue(margin));
            sendJson(ex, 200, JsonWriter.write(resp));
        } catch (Exception e) {
            sendJson(ex, 400, "{\"error\":\"invalid request\"}");
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

    private static void handleAdjustedXp(HttpExchange ex) throws IOException {
        if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        try {
            Object body = JsonParser.parse(readBody(ex));
            Map<String, Object> reqMap = asMap(body);

            List<Object> party = asList(reqMap.get("party"));
            List<Object> monsters = asList(reqMap.get("monsters"));

            long easyTotal = 0, mediumTotal = 0, hardTotal = 0, deadlyTotal = 0;
            for (Object p : party) {
                Map<String, Object> pm = asMap(p);
                int level = (int) toDouble(pm.get("level"));
                int[] th = LEVEL_THRESHOLDS.get(level);
                if (th == null) {
                    sendJson(ex, 400, "{\"error\":\"unsupported level\"}");
                    return;
                }
                easyTotal += th[0];
                mediumTotal += th[1];
                hardTotal += th[2];
                deadlyTotal += th[3];
            }

            long baseXp = 0;
            long monsterCount = 0;
            for (Object mo : monsters) {
                Map<String, Object> mm = asMap(mo);
                Object crObj = mm.get("cr");
                String cr = crObj == null ? null : String.valueOf(crObj);
                Integer xp = CR_XP.get(cr);
                if (xp == null) {
                    sendJson(ex, 400, "{\"error\":\"unsupported cr\"}");
                    return;
                }
                long count = (long) toDouble(mm.get("count"));
                baseXp += (long) xp * count;
                monsterCount += count;
            }

            double multiplier;
            if (monsterCount <= 1) multiplier = 1;
            else if (monsterCount == 2) multiplier = 1.5;
            else if (monsterCount <= 6) multiplier = 2;
            else if (monsterCount <= 10) multiplier = 2.5;
            else if (monsterCount <= 14) multiplier = 3;
            else multiplier = 4;

            double adjustedXp = baseXp * multiplier;

            String difficulty = "trivial";
            if (adjustedXp >= deadlyTotal) difficulty = "deadly";
            else if (adjustedXp >= hardTotal) difficulty = "hard";
            else if (adjustedXp >= mediumTotal) difficulty = "medium";
            else if (adjustedXp >= easyTotal) difficulty = "easy";

            Map<String, Object> thresholds = new LinkedHashMap<>();
            thresholds.put("easy", easyTotal);
            thresholds.put("medium", mediumTotal);
            thresholds.put("hard", hardTotal);
            thresholds.put("deadly", deadlyTotal);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("base_xp", baseXp);
            resp.put("monster_count", monsterCount);
            resp.put("multiplier", numberValue(multiplier));
            resp.put("adjusted_xp", numberValue(adjustedXp));
            resp.put("difficulty", difficulty);
            resp.put("thresholds", thresholds);
            sendJson(ex, 200, JsonWriter.write(resp));
        } catch (Exception e) {
            sendJson(ex, 400, "{\"error\":\"invalid request\"}");
        }
    }

    private static void handleInitiativeOrder(HttpExchange ex) throws IOException {
        if (!ex.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(ex, 405, "{\"error\":\"method not allowed\"}");
            return;
        }
        try {
            Object body = JsonParser.parse(readBody(ex));
            Map<String, Object> reqMap = asMap(body);
            List<Object> combatants = asList(reqMap.get("combatants"));

            List<Map<String, Object>> entries = new ArrayList<>();
            for (Object c : combatants) {
                Map<String, Object> cm = asMap(c);
                String name = String.valueOf(cm.get("name"));
                double dex = toDouble(cm.get("dex"));
                double roll = toDouble(cm.get("roll"));
                double score = roll + dex;

                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("name", name);
                entry.put("dex", dex);
                entry.put("score", score);
                entries.add(entry);
            }

            entries.sort((a, b) -> {
                double scoreA = (double) a.get("score");
                double scoreB = (double) b.get("score");
                if (scoreA != scoreB) return Double.compare(scoreB, scoreA);
                double dexA = (double) a.get("dex");
                double dexB = (double) b.get("dex");
                if (dexA != dexB) return Double.compare(dexB, dexA);
                return ((String) a.get("name")).compareTo((String) b.get("name"));
            });

            List<Object> order = new ArrayList<>();
            for (Map<String, Object> entry : entries) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("name", entry.get("name"));
                item.put("score", numberValue((double) entry.get("score")));
                order.add(item);
            }

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("order", order);
            sendJson(ex, 200, JsonWriter.write(resp));
        } catch (Exception e) {
            sendJson(ex, 400, "{\"error\":\"invalid request\"}");
        }
    }

    // ---------- Helpers ----------

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        if (o instanceof Map) return (Map<String, Object>) o;
        throw new IllegalArgumentException("expected object");
    }

    @SuppressWarnings("unchecked")
    private static List<Object> asList(Object o) {
        if (o instanceof List) return (List<Object>) o;
        if (o == null) return new ArrayList<>();
        throw new IllegalArgumentException("expected array");
    }

    private static double toDouble(Object o) {
        if (o instanceof Number) return ((Number) o).doubleValue();
        throw new IllegalArgumentException("expected number");
    }

    // Returns Long if the value is a whole number, otherwise Double.
    private static Object numberValue(double d) {
        if (d == Math.floor(d) && !Double.isInfinite(d)) {
            return (long) d;
        }
        return d;
    }

    private static String readBody(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            return new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static void sendJson(HttpExchange ex, int status, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    // ---------- Minimal JSON parser ----------

    static class JsonParser {
        private final String s;
        private int i;

        private JsonParser(String s) {
            this.s = s;
            this.i = 0;
        }

        static Object parse(String s) {
            JsonParser p = new JsonParser(s);
            p.skipWs();
            Object v = p.parseValue();
            p.skipWs();
            if (p.i != p.s.length()) {
                throw new IllegalArgumentException("trailing content");
            }
            return v;
        }

        private void skipWs() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
        }

        private Object parseValue() {
            skipWs();
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            char c = s.charAt(i);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't') { expect("true"); return Boolean.TRUE; }
            if (c == 'f') { expect("false"); return Boolean.FALSE; }
            if (c == 'n') { expect("null"); return null; }
            return parseNumber();
        }

        private void expect(String lit) {
            if (!s.regionMatches(i, lit, 0, lit.length())) {
                throw new IllegalArgumentException("expected " + lit);
            }
            i += lit.length();
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new LinkedHashMap<>();
            i++; // {
            skipWs();
            if (i < s.length() && s.charAt(i) == '}') { i++; return map; }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                if (s.charAt(i) != ':') throw new IllegalArgumentException("expected :");
                i++;
                Object val = parseValue();
                map.put(key, val);
                skipWs();
                if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == '}') { i++; break; }
                throw new IllegalArgumentException("expected , or }");
            }
            return map;
        }

        private List<Object> parseArray() {
            List<Object> list = new ArrayList<>();
            i++; // [
            skipWs();
            if (i < s.length() && s.charAt(i) == ']') { i++; return list; }
            while (true) {
                Object val = parseValue();
                list.add(val);
                skipWs();
                if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == ']') { i++; break; }
                throw new IllegalArgumentException("expected , or ]");
            }
            return list;
        }

        private String parseString() {
            if (s.charAt(i) != '"') throw new IllegalArgumentException("expected string");
            i++;
            StringBuilder sb = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw new IllegalArgumentException("unterminated string");
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
                        default:
                            throw new IllegalArgumentException("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object parseNumber() {
            int start = i;
            if (i < s.length() && (s.charAt(i) == '-' || s.charAt(i) == '+')) i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            boolean isDouble = false;
            if (i < s.length() && s.charAt(i) == '.') {
                isDouble = true;
                i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            if (i < s.length() && (s.charAt(i) == 'e' || s.charAt(i) == 'E')) {
                isDouble = true;
                i++;
                if (i < s.length() && (s.charAt(i) == '-' || s.charAt(i) == '+')) i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            String numStr = s.substring(start, i);
            if (numStr.isEmpty()) throw new IllegalArgumentException("invalid number");
            if (isDouble) {
                return Double.parseDouble(numStr);
            } else {
                try {
                    return Long.parseLong(numStr);
                } catch (NumberFormatException e) {
                    return Double.parseDouble(numStr);
                }
            }
        }
    }

    // ---------- Minimal JSON writer ----------

    static class JsonWriter {
        static String write(Object o) {
            StringBuilder sb = new StringBuilder();
            writeValue(o, sb);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(Object o, StringBuilder sb) {
            if (o == null) {
                sb.append("null");
            } else if (o instanceof String) {
                writeString((String) o, sb);
            } else if (o instanceof Boolean) {
                sb.append(o.toString());
            } else if (o instanceof Double || o instanceof Float) {
                double d = ((Number) o).doubleValue();
                if (d == Math.floor(d) && !Double.isInfinite(d)) {
                    sb.append((long) d);
                } else {
                    sb.append(d);
                }
            } else if (o instanceof Number) {
                sb.append(o.toString());
            } else if (o instanceof Map) {
                writeMap((Map<String, Object>) o, sb);
            } else if (o instanceof List) {
                writeList((List<Object>) o, sb);
            } else {
                writeString(o.toString(), sb);
            }
        }

        private static void writeMap(Map<String, Object> map, StringBuilder sb) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : map.entrySet()) {
                if (!first) sb.append(',');
                first = false;
                writeString(e.getKey(), sb);
                sb.append(':');
                writeValue(e.getValue(), sb);
            }
            sb.append('}');
        }

        private static void writeList(List<Object> list, StringBuilder sb) {
            sb.append('[');
            boolean first = true;
            for (Object o : list) {
                if (!first) sb.append(',');
                first = false;
                writeValue(o, sb);
            }
            sb.append(']');
        }

        private static void writeString(String s, StringBuilder sb) {
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
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
        }
    }
}
