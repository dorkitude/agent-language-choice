import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigDecimal;
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
    private static final Pattern DICE = Pattern.compile("^(\\d+)d(\\d+)([+-]\\d+)?$");
    private static final Map<String, Integer> CR_XP = Map.of(
            "0", 10,
            "1/8", 25,
            "1/4", 50,
            "1/2", 100,
            "1", 200,
            "2", 450,
            "3", 700,
            "4", 1100,
            "5", 1800
    );

    public static void main(String[] args) throws Exception {
        String portText = System.getenv().getOrDefault("PORT", "8000");
        int port = Integer.parseInt(portText);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/", Main::handle);
        server.setExecutor(null);
        server.start();
    }

    private static void handle(HttpExchange exchange) throws IOException {
        try {
            String method = exchange.getRequestMethod();
            String path = exchange.getRequestURI().getPath();
            if ("GET".equals(method) && "/health".equals(path)) {
                send(exchange, 200, "{\"ok\":true}");
                return;
            }
            if (!"POST".equals(method)) {
                send(exchange, 404, "{\"error\":\"not found\"}");
                return;
            }

            Object parsed = Json.parse(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            if (!(parsed instanceof Map<?, ?> raw)) {
                throw new BadRequest();
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> body = (Map<String, Object>) raw;

            switch (path) {
                case "/v1/dice/stats" -> send(exchange, 200, diceStats(body));
                case "/v1/checks/ability" -> send(exchange, 200, abilityCheck(body));
                case "/v1/encounters/adjusted-xp" -> send(exchange, 200, adjustedXp(body));
                case "/v1/initiative/order" -> send(exchange, 200, initiativeOrder(body));
                default -> send(exchange, 404, "{\"error\":\"not found\"}");
            }
        } catch (BadRequest | IllegalArgumentException | ClassCastException ex) {
            send(exchange, 400, "{\"error\":\"bad request\"}");
        } catch (Exception ex) {
            send(exchange, 500, "{\"error\":\"internal server error\"}");
        } finally {
            exchange.close();
        }
    }

    private static String diceStats(Map<String, Object> body) {
        String expression = stringField(body, "expression");
        Matcher matcher = DICE.matcher(expression);
        if (!matcher.matches()) {
            throw new BadRequest();
        }
        int count = parsePositive(matcher.group(1));
        int sides = parsePositive(matcher.group(2));
        int modifier = matcher.group(3) == null ? 0 : Integer.parseInt(matcher.group(3));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("dice_count", count);
        response.put("sides", sides);
        response.put("modifier", modifier);
        response.put("min", count + modifier);
        response.put("max", count * sides + modifier);
        response.put("average", count * (sides + 1) / 2.0 + modifier);
        return Json.write(response);
    }

    private static String abilityCheck(Map<String, Object> body) {
        int roll = intField(body, "roll");
        int modifier = intField(body, "modifier");
        int dc = intField(body, "dc");
        int total = roll + modifier;

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("total", total);
        response.put("success", total >= dc);
        response.put("margin", total - dc);
        return Json.write(response);
    }

    private static String adjustedXp(Map<String, Object> body) {
        List<Object> party = listField(body, "party");
        List<Object> monsters = listField(body, "monsters");

        int easy = 0;
        int medium = 0;
        int hard = 0;
        int deadly = 0;
        for (Object member : party) {
            Map<String, Object> map = objectValue(member);
            int level = intField(map, "level");
            if (level != 3) {
                throw new BadRequest();
            }
            easy += 75;
            medium += 150;
            hard += 225;
            deadly += 400;
        }

        int baseXp = 0;
        int monsterCount = 0;
        for (Object monster : monsters) {
            Map<String, Object> map = objectValue(monster);
            String cr = stringField(map, "cr");
            int count = intField(map, "count");
            if (count < 0 || !CR_XP.containsKey(cr)) {
                throw new BadRequest();
            }
            baseXp += CR_XP.get(cr) * count;
            monsterCount += count;
        }

        double multiplier = multiplier(monsterCount);
        double adjustedXp = baseXp * multiplier;
        String difficulty = "trivial";
        if (adjustedXp >= easy) difficulty = "easy";
        if (adjustedXp >= medium) difficulty = "medium";
        if (adjustedXp >= hard) difficulty = "hard";
        if (adjustedXp >= deadly) difficulty = "deadly";

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("base_xp", baseXp);
        response.put("monster_count", monsterCount);
        response.put("multiplier", multiplier);
        response.put("adjusted_xp", adjustedXp);
        response.put("difficulty", difficulty);
        response.put("thresholds", thresholds);
        return Json.write(response);
    }

    private static String initiativeOrder(Map<String, Object> body) {
        List<Object> combatants = listField(body, "combatants");
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object combatant : combatants) {
            Map<String, Object> map = objectValue(combatant);
            String name = stringField(map, "name");
            int dex = intField(map, "dex");
            int roll = intField(map, "roll");
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", name);
            row.put("dex", dex);
            row.put("score", roll + dex);
            rows.add(row);
        }
        rows.sort(Comparator
                .comparingInt((Map<String, Object> row) -> (Integer) row.get("score")).reversed()
                .thenComparing(Comparator.comparingInt((Map<String, Object> row) -> (Integer) row.get("dex")).reversed())
                .thenComparing(row -> (String) row.get("name")));

        List<Object> order = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", row.get("name"));
            item.put("score", row.get("score"));
            order.add(item);
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("order", order);
        return Json.write(response);
    }

    private static int parsePositive(String value) {
        int parsed = Integer.parseInt(value);
        if (parsed <= 0) {
            throw new BadRequest();
        }
        return parsed;
    }

    private static double multiplier(int count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    private static String stringField(Map<String, Object> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof String text)) {
            throw new BadRequest();
        }
        return text;
    }

    private static int intField(Map<String, Object> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof Long) && !(value instanceof Integer)) {
            throw new BadRequest();
        }
        return Math.toIntExact(((Number) value).longValue());
    }

    private static List<Object> listField(Map<String, Object> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof List<?> list)) {
            throw new BadRequest();
        }
        return new ArrayList<>(list);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> objectValue(Object value) {
        if (!(value instanceof Map<?, ?>)) {
            throw new BadRequest();
        }
        return (Map<String, Object>) value;
    }

    private static void send(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    private static class BadRequest extends RuntimeException {
    }

    private static class Json {
        static Object parse(String input) {
            Parser parser = new Parser(input);
            Object value = parser.parseValue();
            parser.skipWhitespace();
            if (!parser.done()) {
                throw new BadRequest();
            }
            return value;
        }

        static String write(Object value) {
            StringBuilder out = new StringBuilder();
            writeValue(out, value);
            return out.toString();
        }

        private static void writeValue(StringBuilder out, Object value) {
            if (value == null) {
                out.append("null");
            } else if (value instanceof String text) {
                out.append('"');
                for (int i = 0; i < text.length(); i++) {
                    char c = text.charAt(i);
                    switch (c) {
                        case '"' -> out.append("\\\"");
                        case '\\' -> out.append("\\\\");
                        case '\b' -> out.append("\\b");
                        case '\f' -> out.append("\\f");
                        case '\n' -> out.append("\\n");
                        case '\r' -> out.append("\\r");
                        case '\t' -> out.append("\\t");
                        default -> {
                            if (c < 0x20) {
                                out.append(String.format("\\u%04x", (int) c));
                            } else {
                                out.append(c);
                            }
                        }
                    }
                }
                out.append('"');
            } else if (value instanceof Boolean) {
                out.append(value);
            } else if (value instanceof Integer || value instanceof Long) {
                out.append(value);
            } else if (value instanceof Number number) {
                out.append(formatNumber(number.doubleValue()));
            } else if (value instanceof Map<?, ?> map) {
                out.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (!first) out.append(',');
                    first = false;
                    writeValue(out, entry.getKey().toString());
                    out.append(':');
                    writeValue(out, entry.getValue());
                }
                out.append('}');
            } else if (value instanceof List<?> list) {
                out.append('[');
                boolean first = true;
                for (Object item : list) {
                    if (!first) out.append(',');
                    first = false;
                    writeValue(out, item);
                }
                out.append(']');
            } else {
                throw new IllegalArgumentException();
            }
        }

        private static String formatNumber(double value) {
            if (Double.isNaN(value) || Double.isInfinite(value)) {
                throw new IllegalArgumentException();
            }
            BigDecimal decimal = BigDecimal.valueOf(value).stripTrailingZeros();
            return decimal.scale() <= 0 ? decimal.toPlainString() : decimal.toString();
        }
    }

    private static class Parser {
        private final String input;
        private int pos;

        Parser(String input) {
            this.input = input;
        }

        boolean done() {
            return pos == input.length();
        }

        void skipWhitespace() {
            while (!done() && Character.isWhitespace(input.charAt(pos))) {
                pos++;
            }
        }

        Object parseValue() {
            skipWhitespace();
            if (done()) throw new BadRequest();
            char c = input.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == '-' || Character.isDigit(c)) return parseNumber();
            if (input.startsWith("true", pos)) {
                pos += 4;
                return true;
            }
            if (input.startsWith("false", pos)) {
                pos += 5;
                return false;
            }
            if (input.startsWith("null", pos)) {
                pos += 4;
                return null;
            }
            throw new BadRequest();
        }

        private Map<String, Object> parseObject() {
            expect('{');
            Map<String, Object> object = new LinkedHashMap<>();
            skipWhitespace();
            if (peek('}')) {
                pos++;
                return object;
            }
            while (true) {
                skipWhitespace();
                if (!peek('"')) throw new BadRequest();
                String key = parseString();
                skipWhitespace();
                expect(':');
                object.put(key, parseValue());
                skipWhitespace();
                if (peek('}')) {
                    pos++;
                    return object;
                }
                expect(',');
            }
        }

        private List<Object> parseArray() {
            expect('[');
            List<Object> array = new ArrayList<>();
            skipWhitespace();
            if (peek(']')) {
                pos++;
                return array;
            }
            while (true) {
                array.add(parseValue());
                skipWhitespace();
                if (peek(']')) {
                    pos++;
                    return array;
                }
                expect(',');
            }
        }

        private String parseString() {
            expect('"');
            StringBuilder out = new StringBuilder();
            while (!done()) {
                char c = input.charAt(pos++);
                if (c == '"') return out.toString();
                if (c == '\\') {
                    if (done()) throw new BadRequest();
                    char escaped = input.charAt(pos++);
                    switch (escaped) {
                        case '"' -> out.append('"');
                        case '\\' -> out.append('\\');
                        case '/' -> out.append('/');
                        case 'b' -> out.append('\b');
                        case 'f' -> out.append('\f');
                        case 'n' -> out.append('\n');
                        case 'r' -> out.append('\r');
                        case 't' -> out.append('\t');
                        case 'u' -> {
                            if (pos + 4 > input.length()) throw new BadRequest();
                            out.append((char) Integer.parseInt(input.substring(pos, pos + 4), 16));
                            pos += 4;
                        }
                        default -> throw new BadRequest();
                    }
                } else {
                    if (c < 0x20) throw new BadRequest();
                    out.append(c);
                }
            }
            throw new BadRequest();
        }

        private Number parseNumber() {
            int start = pos;
            if (peek('-')) pos++;
            if (done()) throw new BadRequest();
            if (peek('0')) {
                pos++;
            } else if (Character.isDigit(input.charAt(pos))) {
                while (!done() && Character.isDigit(input.charAt(pos))) pos++;
            } else {
                throw new BadRequest();
            }
            boolean decimal = false;
            if (!done() && input.charAt(pos) == '.') {
                decimal = true;
                pos++;
                if (done() || !Character.isDigit(input.charAt(pos))) throw new BadRequest();
                while (!done() && Character.isDigit(input.charAt(pos))) pos++;
            }
            if (!done() && (input.charAt(pos) == 'e' || input.charAt(pos) == 'E')) {
                decimal = true;
                pos++;
                if (!done() && (input.charAt(pos) == '+' || input.charAt(pos) == '-')) pos++;
                if (done() || !Character.isDigit(input.charAt(pos))) throw new BadRequest();
                while (!done() && Character.isDigit(input.charAt(pos))) pos++;
            }
            String text = input.substring(start, pos);
            return decimal ? Double.parseDouble(text) : Long.parseLong(text);
        }

        private boolean peek(char expected) {
            return !done() && input.charAt(pos) == expected;
        }

        private void expect(char expected) {
            if (done() || input.charAt(pos) != expected) {
                throw new BadRequest();
            }
            pos++;
        }
    }
}
