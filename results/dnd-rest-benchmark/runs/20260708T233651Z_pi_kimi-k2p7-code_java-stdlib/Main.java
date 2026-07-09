import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@SuppressWarnings("unchecked")
public class Main {
    public static void main(String[] args) throws IOException {
        String portEnv = System.getenv("PORT");
        if (portEnv == null) {
            throw new RuntimeException("PORT environment variable not set");
        }
        int port = Integer.parseInt(portEnv);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/dice/stats", new DiceStatsHandler());
        server.createContext("/v1/checks/ability", new AbilityCheckHandler());
        server.createContext("/v1/encounters/adjusted-xp", new AdjustedXpHandler());
        server.createContext("/v1/initiative/order", new InitiativeOrderHandler());
        server.start();
        try {
            Thread.currentThread().join();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    static void sendJson(HttpExchange exchange, int status, Object body) throws IOException {
        String json = Json.toJson(body);
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static void sendError(HttpExchange exchange, int status, String message) throws IOException {
        Map<String, Object> body = new HashMap<>();
        body.put("error", message);
        sendJson(exchange, status, body);
    }

    static String readBody(HttpExchange exchange) throws IOException {
        InputStream is = exchange.getRequestBody();
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = is.read(buf)) != -1) {
            baos.write(buf, 0, n);
        }
        return baos.toString(StandardCharsets.UTF_8.name());
    }

    static class HealthHandler implements HttpHandler {
        public void handle(HttpExchange exchange) throws IOException {
            Map<String, Object> body = new HashMap<>();
            body.put("ok", true);
            sendJson(exchange, 200, body);
        }
    }

    static class DiceStatsHandler implements HttpHandler {
        public void handle(HttpExchange exchange) throws IOException {
            String body = readBody(exchange);
            Map<String, Object> parsed;
            try {
                parsed = (Map<String, Object>) Json.parse(body);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid json");
                return;
            }
            Object exprObj = parsed.get("expression");
            if (!(exprObj instanceof String)) {
                sendError(exchange, 400, "missing expression");
                return;
            }
            String expression = (String) exprObj;
            int[] result = parseDiceExpression(expression);
            if (result == null) {
                sendError(exchange, 400, "invalid expression");
                return;
            }
            int count = result[0];
            int sides = result[1];
            int modifier = result[2];
            int min = count + modifier;
            int max = count * sides + modifier;
            int average = (min + max) / 2;
            Map<String, Object> response = new HashMap<>();
            response.put("dice_count", count);
            response.put("sides", sides);
            response.put("modifier", modifier);
            response.put("min", min);
            response.put("max", max);
            response.put("average", average);
            sendJson(exchange, 200, response);
        }

        private int[] parseDiceExpression(String expression) {
            if (expression == null) return null;
            int dIndex = expression.indexOf('d');
            if (dIndex <= 0) return null;
            String countStr = expression.substring(0, dIndex);
            int count = parsePositiveInt(countStr);
            if (count <= 0) return null;
            int modIndex = -1;
            char modSign = '+';
            for (int i = dIndex + 1; i < expression.length(); i++) {
                char c = expression.charAt(i);
                if (c == '+' || c == '-') {
                    modIndex = i;
                    modSign = c;
                    break;
                }
            }
            String sidesStr;
            String modStr = "0";
            if (modIndex == -1) {
                sidesStr = expression.substring(dIndex + 1);
            } else {
                sidesStr = expression.substring(dIndex + 1, modIndex);
                modStr = expression.substring(modIndex + 1);
            }
            int sides = parsePositiveInt(sidesStr);
            if (sides <= 0) return null;
            int modifier = parseInt(modStr);
            if (modIndex != -1 && !modStr.isEmpty() && modifier == 0 && !modStr.equals("0")) {
                return null;
            }
            if (modSign == '-') modifier = -modifier;
            return new int[]{count, sides, modifier};
        }

        private int parsePositiveInt(String s) {
            if (s.isEmpty()) return -1;
            for (int i = 0; i < s.length(); i++) {
                if (!Character.isDigit(s.charAt(i))) return -1;
            }
            try {
                return Integer.parseInt(s);
            } catch (NumberFormatException e) {
                return -1;
            }
        }

        private int parseInt(String s) {
            if (s.isEmpty()) return Integer.MIN_VALUE;
            boolean negative = false;
            int start = 0;
            if (s.charAt(0) == '-') {
                negative = true;
                start = 1;
            } else if (s.charAt(0) == '+') {
                start = 1;
            }
            if (start >= s.length()) return Integer.MIN_VALUE;
            for (int i = start; i < s.length(); i++) {
                if (!Character.isDigit(s.charAt(i))) return Integer.MIN_VALUE;
            }
            try {
                int val = Integer.parseInt(s.substring(start));
                return negative ? -val : val;
            } catch (NumberFormatException e) {
                return Integer.MIN_VALUE;
            }
        }
    }

    static class AbilityCheckHandler implements HttpHandler {
        public void handle(HttpExchange exchange) throws IOException {
            String body = readBody(exchange);
            Map<String, Object> parsed;
            try {
                parsed = (Map<String, Object>) Json.parse(body);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid json");
                return;
            }
            long roll = getLong(parsed, "roll");
            long modifier = getLong(parsed, "modifier");
            long dc = getLong(parsed, "dc");
            long total = roll + modifier;
            boolean success = total >= dc;
            long margin = total - dc;
            Map<String, Object> response = new HashMap<>();
            response.put("total", total);
            response.put("success", success);
            response.put("margin", margin);
            sendJson(exchange, 200, response);
        }
    }

    static class AdjustedXpHandler implements HttpHandler {
        private static final Map<String, Integer> CR_XP = new HashMap<>();
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

        private static final int[] EASY = {0, 25, 50, 75, 125, 250};
        private static final int[] MEDIUM = {0, 50, 100, 150, 250, 500};
        private static final int[] HARD = {0, 75, 150, 225, 375, 750};
        private static final int[] DEADLY = {0, 100, 200, 400, 500, 1100};

        public void handle(HttpExchange exchange) throws IOException {
            String body = readBody(exchange);
            Map<String, Object> parsed;
            try {
                parsed = (Map<String, Object>) Json.parse(body);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid json");
                return;
            }
            List<Object> partyList = (List<Object>) parsed.get("party");
            List<Object> monstersList = (List<Object>) parsed.get("monsters");
            if (partyList == null || monstersList == null) {
                sendError(exchange, 400, "missing party or monsters");
                return;
            }

            int easy = 0, medium = 0, hard = 0, deadly = 0;
            for (Object p : partyList) {
                Map<String, Object> member = (Map<String, Object>) p;
                int level = (int) getLong(member, "level");
                easy += EASY[level];
                medium += MEDIUM[level];
                hard += HARD[level];
                deadly += DEADLY[level];
            }

            int baseXp = 0;
            int monsterCount = 0;
            for (Object m : monstersList) {
                Map<String, Object> monster = (Map<String, Object>) m;
                String cr = (String) monster.get("cr");
                Integer xp = CR_XP.get(cr);
                if (xp == null) {
                    sendError(exchange, 400, "unsupported cr: " + cr);
                    return;
                }
                int count = (int) getLong(monster, "count");
                baseXp += xp * count;
                monsterCount += count;
            }

            Number multiplier;
            if (monsterCount == 1) multiplier = 1L;
            else if (monsterCount == 2) multiplier = 1.5;
            else if (monsterCount <= 6) multiplier = 2L;
            else if (monsterCount <= 10) multiplier = 2.5;
            else if (monsterCount <= 14) multiplier = 3L;
            else multiplier = 4L;

            int adjustedXp = (int) (baseXp * multiplier.doubleValue());

            String difficulty;
            if (adjustedXp >= deadly) difficulty = "deadly";
            else if (adjustedXp >= hard) difficulty = "hard";
            else if (adjustedXp >= medium) difficulty = "medium";
            else if (adjustedXp >= easy) difficulty = "easy";
            else difficulty = "trivial";

            Map<String, Object> thresholds = new HashMap<>();
            thresholds.put("easy", easy);
            thresholds.put("medium", medium);
            thresholds.put("hard", hard);
            thresholds.put("deadly", deadly);

            Map<String, Object> response = new HashMap<>();
            response.put("base_xp", baseXp);
            response.put("monster_count", monsterCount);
            response.put("multiplier", multiplier);
            response.put("adjusted_xp", adjustedXp);
            response.put("difficulty", difficulty);
            response.put("thresholds", thresholds);
            sendJson(exchange, 200, response);
        }
    }

    static class InitiativeOrderHandler implements HttpHandler {
        public void handle(HttpExchange exchange) throws IOException {
            String body = readBody(exchange);
            Map<String, Object> parsed;
            try {
                parsed = (Map<String, Object>) Json.parse(body);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid json");
                return;
            }
            List<Object> combatantsList = (List<Object>) parsed.get("combatants");
            if (combatantsList == null) {
                sendError(exchange, 400, "missing combatants");
                return;
            }
            List<Combatant> combatants = new ArrayList<>();
            for (Object c : combatantsList) {
                Map<String, Object> map = (Map<String, Object>) c;
                String name = (String) map.get("name");
                long dex = getLong(map, "dex");
                long roll = getLong(map, "roll");
                combatants.add(new Combatant(name, (int) dex, (int) roll));
            }
            Collections.sort(combatants, new Comparator<Combatant>() {
                public int compare(Combatant a, Combatant b) {
                    if (b.score != a.score) return b.score - a.score;
                    if (b.dex != a.dex) return b.dex - a.dex;
                    return a.name.compareTo(b.name);
                }
            });
            List<Map<String, Object>> order = new ArrayList<>();
            for (Combatant c : combatants) {
                Map<String, Object> entry = new HashMap<>();
                entry.put("name", c.name);
                entry.put("score", c.score);
                order.add(entry);
            }
            Map<String, Object> response = new HashMap<>();
            response.put("order", order);
            sendJson(exchange, 200, response);
        }
    }

    static class Combatant {
        String name;
        int dex;
        int roll;
        int score;
        Combatant(String name, int dex, int roll) {
            this.name = name;
            this.dex = dex;
            this.roll = roll;
            this.score = roll + dex;
        }
    }

    static long getLong(Map<String, Object> map, String key) {
        Object value = map.get(key);
        if (value instanceof Number) return ((Number) value).longValue();
        throw new RuntimeException("expected number for " + key);
    }

    static class Json {
        static Object parse(String s) {
            return new JsonParser(s).parse();
        }

        static String toJson(Object obj) {
            StringBuilder sb = new StringBuilder();
            toJson(obj, sb);
            return sb.toString();
        }

        private static void toJson(Object obj, StringBuilder sb) {
            if (obj == null) {
                sb.append("null");
            } else if (obj instanceof Map) {
                sb.append("{");
                Map<?, ?> map = (Map<?, ?>) obj;
                boolean first = true;
                for (Map.Entry<?, ?> e : map.entrySet()) {
                    if (!first) sb.append(",");
                    first = false;
                    sb.append("\"").append(escape(e.getKey().toString())).append("\":");
                    toJson(e.getValue(), sb);
                }
                sb.append("}");
            } else if (obj instanceof List) {
                sb.append("[");
                List<?> list = (List<?>) obj;
                boolean first = true;
                for (Object item : list) {
                    if (!first) sb.append(",");
                    first = false;
                    toJson(item, sb);
                }
                sb.append("]");
            } else if (obj instanceof String) {
                sb.append("\"").append(escape((String) obj)).append("\"");
            } else if (obj instanceof Number) {
                sb.append(obj.toString());
            } else if (obj instanceof Boolean) {
                sb.append(obj.toString());
            } else {
                sb.append("\"").append(escape(obj.toString())).append("\"");
            }
        }

        private static String escape(String s) {
            StringBuilder sb = new StringBuilder();
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
            return sb.toString();
        }
    }

    static class JsonParser {
        private final String s;
        private int pos;

        JsonParser(String s) {
            this.s = s;
            this.pos = 0;
        }

        Object parse() {
            skipWhitespace();
            Object value = parseValue();
            skipWhitespace();
            if (pos != s.length()) throw new RuntimeException("trailing data");
            return value;
        }

        private Object parseValue() {
            skipWhitespace();
            if (pos >= s.length()) throw new RuntimeException("unexpected end");
            char c = s.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBoolean();
            if (c == 'n') return parseNull();
            return parseNumber();
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> obj = new HashMap<>();
            pos++; // {
            skipWhitespace();
            if (peek() == '}') {
                pos++;
                return obj;
            }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                Object value = parseValue();
                obj.put(key, value);
                skipWhitespace();
                char c = peek();
                if (c == ',') {
                    pos++;
                } else if (c == '}') {
                    pos++;
                    break;
                } else {
                    throw new RuntimeException("expected , or }");
                }
            }
            return obj;
        }

        private List<Object> parseArray() {
            List<Object> arr = new ArrayList<>();
            pos++; // [
            skipWhitespace();
            if (peek() == ']') {
                pos++;
                return arr;
            }
            while (true) {
                arr.add(parseValue());
                skipWhitespace();
                char c = peek();
                if (c == ',') {
                    pos++;
                } else if (c == ']') {
                    pos++;
                    break;
                } else {
                    throw new RuntimeException("expected , or ]");
                }
            }
            return arr;
        }

        private String parseString() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < s.length() && s.charAt(pos) != '"') {
                char c = s.charAt(pos++);
                if (c == '\\') {
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
                            String hex = s.substring(pos, pos + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            pos += 4;
                            break;
                        default: throw new RuntimeException("invalid escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            expect('"');
            return sb.toString();
        }

        private Number parseNumber() {
            int start = pos;
            if (s.charAt(pos) == '-') pos++;
            while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
            if (pos < s.length() && s.charAt(pos) == '.') {
                pos++;
                while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
                return Double.parseDouble(s.substring(start, pos));
            }
            if (pos < s.length() && (s.charAt(pos) == 'e' || s.charAt(pos) == 'E')) {
                pos++;
                if (pos < s.length() && (s.charAt(pos) == '+' || s.charAt(pos) == '-')) pos++;
                while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
                return Double.parseDouble(s.substring(start, pos));
            }
            return Long.parseLong(s.substring(start, pos));
        }

        private Boolean parseBoolean() {
            if (s.startsWith("true", pos)) {
                pos += 4;
                return true;
            }
            if (s.startsWith("false", pos)) {
                pos += 5;
                return false;
            }
            throw new RuntimeException("invalid boolean");
        }

        private Object parseNull() {
            if (s.startsWith("null", pos)) {
                pos += 4;
                return null;
            }
            throw new RuntimeException("invalid null");
        }

        private void skipWhitespace() {
            while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) pos++;
        }

        private char peek() {
            if (pos >= s.length()) throw new RuntimeException("unexpected end");
            return s.charAt(pos);
        }

        private void expect(char c) {
            if (pos >= s.length() || s.charAt(pos) != c) throw new RuntimeException("expected " + c);
            pos++;
        }
    }
}
