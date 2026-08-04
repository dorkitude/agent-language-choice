import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
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
import java.util.concurrent.Executors;
import java.util.Base64;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class Main {
    private static Storage STORAGE;

    public static void main(String[] args) throws IOException {
        STORAGE = new Storage("game.db");
        STORAGE.init();

        String portEnv = System.getenv("PORT");
        int port = portEnv == null ? 8080 : Integer.parseInt(portEnv);

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/dice/stats", new DiceHandler());
        server.createContext("/v1/checks/ability", new AbilityHandler());
        server.createContext("/v1/encounters/adjusted-xp", new EncounterHandler());
        server.createContext("/v1/initiative/order", new InitiativeHandler());
        server.createContext("/v1/characters/ability-modifier", new AbilityModifierHandler());
        server.createContext("/v1/characters/proficiency", new ProficiencyHandler());
        server.createContext("/v1/characters/derived-stats", new DerivedStatsHandler());
        server.createContext("/v1/combat/sessions", new CombatHandler());
        server.createContext("/v1/auth/register", new RegisterHandler());
        server.createContext("/v1/auth/login", new LoginHandler());
        server.createContext("/v1/storage", new StorageHandler());
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.start();
        System.out.println("Listening on 127.0.0.1:" + port);
    }

    // ------------------------------------------------------------------
    // JSON value model
    // ------------------------------------------------------------------

    static abstract class JsonValue {
        abstract void write(StringBuilder sb);

        @Override
        public String toString() {
            StringBuilder sb = new StringBuilder();
            write(sb);
            return sb.toString();
        }
    }

    static final class JsonObject extends JsonValue {
        final Map<String, JsonValue> map = new LinkedHashMap<>();

        boolean has(String key) {
            return map.containsKey(key);
        }

        JsonValue get(String key) {
            return map.get(key);
        }

        String getString(String key) {
            JsonValue v = map.get(key);
            return v instanceof JsonString ? ((JsonString) v).value : null;
        }

        Integer getInt(String key) {
            JsonValue v = map.get(key);
            if (v instanceof JsonNumber) {
                return ((JsonNumber) v).value.intValue();
            }
            return null;
        }

        JsonArray getArray(String key) {
            JsonValue v = map.get(key);
            return v instanceof JsonArray ? (JsonArray) v : null;
        }

        JsonObject getObject(String key) {
            JsonValue v = map.get(key);
            return v instanceof JsonObject ? (JsonObject) v : null;
        }

        Boolean getBool(String key) {
            JsonValue v = map.get(key);
            return v instanceof JsonBool ? ((JsonBool) v).value : null;
        }

        void put(String key, JsonValue value) {
            map.put(key, value);
        }

        @Override
        void write(StringBuilder sb) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, JsonValue> e : map.entrySet()) {
                if (!first) sb.append(',');
                first = false;
                sb.append('"');
                escape(e.getKey(), sb);
                sb.append('"').append(':');
                e.getValue().write(sb);
            }
            sb.append('}');
        }
    }

    static final class JsonArray extends JsonValue {
        final List<JsonValue> list = new ArrayList<>();

        void add(JsonValue v) {
            list.add(v);
        }

        int size() {
            return list.size();
        }

        JsonValue get(int i) {
            return list.get(i);
        }

        @Override
        void write(StringBuilder sb) {
            sb.append('[');
            boolean first = true;
            for (JsonValue v : list) {
                if (!first) sb.append(',');
                first = false;
                v.write(sb);
            }
            sb.append(']');
        }
    }

    static final class JsonString extends JsonValue {
        final String value;

        JsonString(String value) {
            this.value = value;
        }

        @Override
        void write(StringBuilder sb) {
            sb.append('"');
            escape(value, sb);
            sb.append('"');
        }
    }

    static final class JsonNumber extends JsonValue {
        final Number value;

        JsonNumber(Number value) {
            this.value = value;
        }

        @Override
        void write(StringBuilder sb) {
            if (value instanceof Double d) {
                if (Double.isNaN(d) || Double.isInfinite(d)) {
                    sb.append("null");
                    return;
                }
                long l = (long) (double) d;
                if (d == l && Math.abs(d) <= 9e15) {
                    sb.append(l);
                    return;
                }
            }
            sb.append(value.toString());
        }
    }

    static final class JsonBool extends JsonValue {
        final boolean value;

        JsonBool(boolean value) {
            this.value = value;
        }

        @Override
        void write(StringBuilder sb) {
            sb.append(value);
        }
    }

    static final class JsonNull extends JsonValue {
        @Override
        void write(StringBuilder sb) {
            sb.append("null");
        }
    }

    static void escape(String s, StringBuilder sb) {
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
    }

    // ------------------------------------------------------------------
    // JSON parser
    // ------------------------------------------------------------------

    static JsonValue parseJson(String s) {
        return new JsonParser(s).parse();
    }

    static final class JsonParser {
        private final String s;
        private int pos;

        JsonParser(String s) {
            this.s = s;
            this.pos = 0;
        }

        JsonValue parse() {
            JsonValue v = parseValue();
            skipWhitespace();
            if (pos != s.length()) {
                throw new RuntimeException("Unexpected trailing data");
            }
            return v;
        }

        private void skipWhitespace() {
            while (pos < s.length()) {
                char c = s.charAt(pos);
                if (c == ' ' || c == '\n' || c == '\r' || c == '\t') {
                    pos++;
                } else {
                    break;
                }
            }
        }

        private JsonValue parseValue() {
            skipWhitespace();
            if (pos >= s.length()) {
                throw new RuntimeException("Unexpected end of input");
            }
            char c = s.charAt(pos);
            return switch (c) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> parseString();
                case 't', 'f' -> parseBool();
                case 'n' -> parseNull();
                default -> parseNumber();
            };
        }

        private JsonObject parseObject() {
            pos++; // '{'
            JsonObject obj = new JsonObject();
            skipWhitespace();
            if (peek() == '}') {
                pos++;
                return obj;
            }
            while (true) {
                skipWhitespace();
                if (s.charAt(pos) != '"') {
                    throw new RuntimeException("Expected string key");
                }
                String key = parseStringValue();
                skipWhitespace();
                expect(':');
                JsonValue val = parseValue();
                obj.put(key, val);
                skipWhitespace();
                char c = s.charAt(pos++);
                if (c == '}') return obj;
                if (c != ',') throw new RuntimeException("Expected ',' or '}'");
            }
        }

        private JsonArray parseArray() {
            pos++; // '['
            JsonArray arr = new JsonArray();
            skipWhitespace();
            if (peek() == ']') {
                pos++;
                return arr;
            }
            while (true) {
                JsonValue val = parseValue();
                arr.add(val);
                skipWhitespace();
                char c = s.charAt(pos++);
                if (c == ']') return arr;
                if (c != ',') throw new RuntimeException("Expected ',' or ']'");
            }
        }

        private char peek() {
            if (pos >= s.length()) throw new RuntimeException("Unexpected end of input");
            return s.charAt(pos);
        }

        private void expect(char c) {
            skipWhitespace();
            if (pos >= s.length() || s.charAt(pos) != c) {
                throw new RuntimeException("Expected '" + c + "'");
            }
            pos++;
        }

        private JsonString parseString() {
            return new JsonString(parseStringValue());
        }

        private String parseStringValue() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < s.length()) {
                char c = s.charAt(pos++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    if (pos >= s.length()) throw new RuntimeException("Bad escape");
                    char esc = s.charAt(pos++);
                    switch (esc) {
                        case '"', '\\', '/' -> sb.append(esc);
                        case 'b' -> sb.append('\b');
                        case 'f' -> sb.append('\f');
                        case 'n' -> sb.append('\n');
                        case 'r' -> sb.append('\r');
                        case 't' -> sb.append('\t');
                        case 'u' -> {
                            if (pos + 4 > s.length()) throw new RuntimeException("Bad unicode escape");
                            String hex = s.substring(pos, pos + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            pos += 4;
                        }
                        default -> throw new RuntimeException("Bad escape \\ " + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new RuntimeException("Unterminated string");
        }

        private JsonBool parseBool() {
            if (s.startsWith("true", pos)) {
                pos += 4;
                return new JsonBool(true);
            }
            if (s.startsWith("false", pos)) {
                pos += 5;
                return new JsonBool(false);
            }
            throw new RuntimeException("Expected boolean");
        }

        private JsonNull parseNull() {
            if (s.startsWith("null", pos)) {
                pos += 4;
                return new JsonNull();
            }
            throw new RuntimeException("Expected null");
        }

        private JsonNumber parseNumber() {
            int start = pos;
            if (peek() == '-') pos++;
            while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
            boolean isDouble = false;
            if (pos < s.length() && s.charAt(pos) == '.') {
                isDouble = true;
                pos++;
                while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
            }
            if (pos < s.length() && (s.charAt(pos) == 'e' || s.charAt(pos) == 'E')) {
                isDouble = true;
                pos++;
                if (pos < s.length() && (s.charAt(pos) == '+' || s.charAt(pos) == '-')) pos++;
                while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
            }
            String num = s.substring(start, pos);
            if (isDouble) {
                return new JsonNumber(Double.parseDouble(num));
            }
            try {
                return new JsonNumber(Long.parseLong(num));
            } catch (NumberFormatException e) {
                return new JsonNumber(Double.parseDouble(num));
            }
        }
    }

    // ------------------------------------------------------------------
    // HTTP helpers
    // ------------------------------------------------------------------

    static JsonObject parseRequest(HttpExchange exchange) throws IOException {
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        JsonValue v = parseJson(body);
        if (!(v instanceof JsonObject)) {
            throw new RuntimeException("Expected JSON object");
        }
        return (JsonObject) v;
    }

    static void sendResponse(HttpExchange exchange, int status, JsonValue body) throws IOException {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static void sendResponse(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static int abilityModifier(int score) {
        return Math.floorDiv(score - 10, 2);
    }

    static int proficiencyBonus(int level) {
        return 2 + (level - 1) / 4;
    }

    static abstract class BaseHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                handleRequest(exchange);
            } catch (Exception e) {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
            }
        }

        abstract void handleRequest(HttpExchange exchange) throws IOException;
    }

    // ------------------------------------------------------------------
    // Storage
    // ------------------------------------------------------------------

    static final class Storage {
        private final String dbPath;
        private final Object lock = new Object();
        private boolean initialized = false;

        Storage(String dbPath) {
            this.dbPath = dbPath;
        }

        void init() {
            synchronized (lock) {
                execSql(
                    "DROP TABLE IF EXISTS conditions;",
                    "DROP TABLE IF EXISTS combatants;",
                    "DROP TABLE IF EXISTS combat_sessions;",
                    "DROP TABLE IF EXISTS users;",
                    "CREATE TABLE users (username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash TEXT NOT NULL);",
                    "CREATE TABLE combat_sessions (id TEXT PRIMARY KEY, round INTEGER NOT NULL DEFAULT 1, turn_index INTEGER NOT NULL DEFAULT 0);",
                    "CREATE TABLE combatants (session_id TEXT NOT NULL, name TEXT NOT NULL, dex INTEGER NOT NULL, roll INTEGER NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (session_id, name));",
                    "CREATE TABLE conditions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL);"
                );
                initialized = true;
            }
        }

        void reset() {
            synchronized (lock) {
                execSql(
                    "DROP TABLE IF EXISTS conditions;",
                    "DROP TABLE IF EXISTS combatants;",
                    "DROP TABLE IF EXISTS combat_sessions;",
                    "DROP TABLE IF EXISTS users;"
                );
                init();
            }
        }

        JsonObject status() {
            JsonObject o = new JsonObject();
            o.put("driver", new JsonString("sqlite"));
            o.put("schema_version", new JsonNumber(1));
            o.put("initialized", new JsonBool(initialized));
            return o;
        }

        boolean insertUser(String username, String role, String passwordHash) {
            synchronized (lock) {
                try {
                    execSql(
                        "BEGIN;",
                        "INSERT INTO users (username, role, password_hash) VALUES (" + quote(username) + ", " + quote(role) + ", " + quote(passwordHash) + ");",
                        "COMMIT;"
                    );
                    return true;
                } catch (RuntimeException e) {
                    if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                        return false;
                    }
                    throw e;
                }
            }
        }

        User getUser(String username) {
            synchronized (lock) {
                String result = queryJson("SELECT username, role, password_hash FROM users WHERE username = " + quote(username) + ";");
                JsonArray arr = parseJsonArray(result);
                if (arr.size() == 0) return null;
                JsonObject o = (JsonObject) arr.get(0);
                return new User(o.getString("username"), o.getString("role"), o.getString("password_hash"));
            }
        }

        boolean insertCombatSession(String id, List<Combatant> combatants) {
            synchronized (lock) {
                try {
                    List<String> sqls = new ArrayList<>();
                    sqls.add("BEGIN;");
                    sqls.add("INSERT INTO combat_sessions (id, round, turn_index) VALUES (" + quote(id) + ", 1, 0);");
                    for (int i = 0; i < combatants.size(); i++) {
                        Combatant c = combatants.get(i);
                        sqls.add("INSERT INTO combatants (session_id, name, dex, roll, sort_order) VALUES (" + quote(id) + ", " + quote(c.name) + ", " + c.dex + ", " + c.roll + ", " + i + ");");
                    }
                    sqls.add("COMMIT;");
                    execSql(sqls.toArray(new String[0]));
                    return true;
                } catch (RuntimeException e) {
                    if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                        return false;
                    }
                    throw e;
                }
            }
        }

        CombatSession getCombatSession(String id) {
            synchronized (lock) {
                String sessionResult = queryJson("SELECT id, round, turn_index FROM combat_sessions WHERE id = " + quote(id) + ";");
                JsonArray sessionArr = parseJsonArray(sessionResult);
                if (sessionArr.size() == 0) return null;
                JsonObject sessionObj = (JsonObject) sessionArr.get(0);

                String combatantsResult = queryJson("SELECT name, dex, roll FROM combatants WHERE session_id = " + quote(id) + " ORDER BY sort_order;");
                JsonArray combatantsArr = parseJsonArray(combatantsResult);
                List<Combatant> combatants = new ArrayList<>();
                for (JsonValue v : combatantsArr.list) {
                    JsonObject o = (JsonObject) v;
                    combatants.add(new Combatant(o.getString("name"), o.getInt("dex"), o.getInt("roll")));
                }

                CombatSession session = new CombatSession(sessionObj.getString("id"), combatants);
                session.round = sessionObj.getInt("round");
                session.turnIndex = sessionObj.getInt("turn_index");

                String conditionsResult = queryJson("SELECT target, condition, remaining_rounds FROM conditions WHERE session_id = " + quote(id) + " ORDER BY id;");
                JsonArray conditionsArr = parseJsonArray(conditionsResult);
                for (JsonValue v : conditionsArr.list) {
                    JsonObject o = (JsonObject) v;
                    String target = o.getString("target");
                    session.conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(new Condition(o.getString("condition"), o.getInt("remaining_rounds")));
                }

                return session;
            }
        }

        void addCondition(String sessionId, String target, String condition, int duration) {
            synchronized (lock) {
                execSql("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (" + quote(sessionId) + ", " + quote(target) + ", " + quote(condition) + ", " + duration + ");");
            }
        }

        void updateCombatSession(CombatSession session) {
            synchronized (lock) {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                sqls.add("UPDATE combat_sessions SET round = " + session.round + ", turn_index = " + session.turnIndex + " WHERE id = " + quote(session.id) + ";");
                for (Map.Entry<String, List<Condition>> e : session.conditions.entrySet()) {
                    String target = e.getKey();
                    sqls.add("DELETE FROM conditions WHERE session_id = " + quote(session.id) + " AND target = " + quote(target) + ";");
                    for (Condition c : e.getValue()) {
                        sqls.add("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (" + quote(session.id) + ", " + quote(target) + ", " + quote(c.condition) + ", " + c.remaining + ");");
                    }
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));
            }
        }

        private String quote(String s) {
            return "'" + s.replace("'", "''") + "'";
        }

        private String execSql(String... sqls) {
            try {
                List<String> cmd = new ArrayList<>();
                cmd.add("sqlite3");
                cmd.add(dbPath);
                Collections.addAll(cmd, sqls);
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectErrorStream(true);
                Process p = pb.start();
                String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                int rc = p.waitFor();
                if (rc != 0) {
                    throw new RuntimeException("sqlite3 failed: " + output.trim());
                }
                return output;
            } catch (IOException | InterruptedException e) {
                throw new RuntimeException(e);
            }
        }

        private String queryJson(String sql) {
            try {
                List<String> cmd = new ArrayList<>();
                cmd.add("sqlite3");
                cmd.add("-json");
                cmd.add(dbPath);
                cmd.add(sql);
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectErrorStream(true);
                Process p = pb.start();
                String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                int rc = p.waitFor();
                if (rc != 0) {
                    throw new RuntimeException("sqlite3 failed: " + output.trim());
                }
                return output;
            } catch (IOException | InterruptedException e) {
                throw new RuntimeException(e);
            }
        }

        private JsonArray parseJsonArray(String s) {
            String trimmed = s.trim();
            if (trimmed.isEmpty()) {
                return new JsonArray();
            }
            JsonValue v = parseJson(trimmed);
            if (v instanceof JsonArray) return (JsonArray) v;
            return new JsonArray();
        }
    }

    // ------------------------------------------------------------------
    // Endpoint handlers
    // ------------------------------------------------------------------

    static final class HealthHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            JsonObject o = new JsonObject();
            o.put("ok", new JsonBool(true));
            sendResponse(exchange, 200, o);
        }
    }

    static final class StorageHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();
            if (path.equals("/v1/storage/status") && method.equalsIgnoreCase("GET")) {
                sendResponse(exchange, 200, STORAGE.status());
            } else if (path.equals("/v1/storage/reset") && method.equalsIgnoreCase("POST")) {
                STORAGE.reset();
                JsonObject res = new JsonObject();
                res.put("ok", new JsonBool(true));
                res.put("schema_version", new JsonNumber(1));
                sendResponse(exchange, 200, res);
            } else {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
            }
        }
    }

    static final class DiceHandler extends BaseHandler {
        private static final Pattern EXPR = Pattern.compile("^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            String expr = req.getString("expression");
            if (expr == null) {
                sendResponse(exchange, 400, "{\"error\":\"missing expression\"}");
                return;
            }
            Matcher m = EXPR.matcher(expr);
            if (!m.matches()) {
                sendResponse(exchange, 400, "{\"error\":\"invalid expression\"}");
                return;
            }
            int count = Integer.parseInt(m.group(1));
            int sides = Integer.parseInt(m.group(2));
            if (count <= 0 || sides <= 0) {
                sendResponse(exchange, 400, "{\"error\":\"invalid expression\"}");
                return;
            }
            int modifier = 0;
            if (m.group(3) != null) {
                int mod = Integer.parseInt(m.group(4));
                modifier = m.group(3).equals("-") ? -mod : mod;
            }

            int min = count + modifier;
            int max = count * sides + modifier;
            double average = ((double) count) * (sides + 1) / 2.0 + modifier;

            JsonObject res = new JsonObject();
            res.put("dice_count", new JsonNumber(count));
            res.put("sides", new JsonNumber(sides));
            res.put("modifier", new JsonNumber(modifier));
            res.put("min", new JsonNumber(min));
            res.put("max", new JsonNumber(max));
            res.put("average", new JsonNumber(average));
            sendResponse(exchange, 200, res);
        }
    }

    static final class AbilityHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            Integer roll = req.getInt("roll");
            Integer modifier = req.getInt("modifier");
            Integer dc = req.getInt("dc");
            if (roll == null || modifier == null || dc == null) {
                sendResponse(exchange, 400, "{\"error\":\"missing fields\"}");
                return;
            }
            int total = roll + modifier;
            int margin = total - dc;
            JsonObject res = new JsonObject();
            res.put("total", new JsonNumber(total));
            res.put("success", new JsonBool(total >= dc));
            res.put("margin", new JsonNumber(margin));
            sendResponse(exchange, 200, res);
        }
    }

    static final class EncounterHandler extends BaseHandler {
        private static final Map<String, Integer> XP = new HashMap<>();
        private static final Map<Integer, Number> MULTIPLIER = new HashMap<>();

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

            MULTIPLIER.put(1, 1L);
            MULTIPLIER.put(2, 1.5);
            MULTIPLIER.put(3, 2L);
            MULTIPLIER.put(4, 2L);
            MULTIPLIER.put(5, 2L);
            MULTIPLIER.put(6, 2L);
            MULTIPLIER.put(7, 2.5);
            MULTIPLIER.put(8, 2.5);
            MULTIPLIER.put(9, 2.5);
            MULTIPLIER.put(10, 2.5);
            MULTIPLIER.put(11, 3L);
            MULTIPLIER.put(12, 3L);
            MULTIPLIER.put(13, 3L);
            MULTIPLIER.put(14, 3L);
            MULTIPLIER.put(15, 4L);
        }

        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            JsonArray party = req.getArray("party");
            JsonArray monsters = req.getArray("monsters");
            if (party == null || monsters == null) {
                sendResponse(exchange, 400, "{\"error\":\"missing fields\"}");
                return;
            }

            int easy = 0, medium = 0, hard = 0, deadly = 0;
            for (JsonValue v : party.list) {
                if (!(v instanceof JsonObject)) {
                    sendResponse(exchange, 400, "{\"error\":\"bad party\"}");
                    return;
                }
                Integer level = ((JsonObject) v).getInt("level");
                if (level == null || level != 3) {
                    sendResponse(exchange, 400, "{\"error\":\"unsupported level\"}");
                    return;
                }
                easy += 75;
                medium += 150;
                hard += 225;
                deadly += 400;
            }

            long baseXp = 0;
            long monsterCount = 0;
            for (JsonValue v : monsters.list) {
                if (!(v instanceof JsonObject)) {
                    sendResponse(exchange, 400, "{\"error\":\"bad monsters\"}");
                    return;
                }
                JsonObject mo = (JsonObject) v;
                String cr = mo.getString("cr");
                Integer count = mo.getInt("count");
                if (cr == null || count == null || count < 0) {
                    sendResponse(exchange, 400, "{\"error\":\"bad monster\"}");
                    return;
                }
                Integer xp = XP.get(cr);
                if (xp == null) {
                    sendResponse(exchange, 400, "{\"error\":\"unsupported cr\"}");
                    return;
                }
                baseXp += (long) xp * count;
                monsterCount += count;
            }
            if (monsterCount <= 0) {
                sendResponse(exchange, 400, "{\"error\":\"no monsters\"}");
                return;
            }

            Number multiplier = MULTIPLIER.getOrDefault((int) monsterCount, 4L);
            double adjustedD = baseXp * multiplier.doubleValue();
            Number adjusted;
            if (adjustedD == Math.floor(adjustedD)) {
                adjusted = (long) adjustedD;
            } else {
                adjusted = adjustedD;
            }

            long adjCompare = (long) Math.floor(adjustedD);
            String difficulty;
            if (adjCompare >= deadly) difficulty = "deadly";
            else if (adjCompare >= hard) difficulty = "hard";
            else if (adjCompare >= medium) difficulty = "medium";
            else if (adjCompare >= easy) difficulty = "easy";
            else difficulty = "trivial";

            JsonObject thresholds = new JsonObject();
            thresholds.put("easy", new JsonNumber(easy));
            thresholds.put("medium", new JsonNumber(medium));
            thresholds.put("hard", new JsonNumber(hard));
            thresholds.put("deadly", new JsonNumber(deadly));

            JsonObject res = new JsonObject();
            res.put("base_xp", new JsonNumber(baseXp));
            res.put("monster_count", new JsonNumber(monsterCount));
            res.put("multiplier", new JsonNumber(multiplier));
            res.put("adjusted_xp", new JsonNumber(adjusted));
            res.put("difficulty", new JsonString(difficulty));
            res.put("thresholds", thresholds);
            sendResponse(exchange, 200, res);
        }
    }

    static final class InitiativeHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            JsonArray combatants = req.getArray("combatants");
            if (combatants == null) {
                sendResponse(exchange, 400, "{\"error\":\"missing combatants\"}");
                return;
            }
            List<Combatant> list = new ArrayList<>();
            for (JsonValue v : combatants.list) {
                if (!(v instanceof JsonObject)) {
                    sendResponse(exchange, 400, "{\"error\":\"bad combatant\"}");
                    return;
                }
                JsonObject c = (JsonObject) v;
                String name = c.getString("name");
                Integer dex = c.getInt("dex");
                Integer roll = c.getInt("roll");
                if (name == null || dex == null || roll == null) {
                    sendResponse(exchange, 400, "{\"error\":\"bad combatant\"}");
                    return;
                }
                list.add(new Combatant(name, dex, roll));
            }
            list.sort((a, b) -> {
                int sa = a.score();
                int sb = b.score();
                if (sa != sb) return Integer.compare(sb, sa);
                if (a.dex != b.dex) return Integer.compare(b.dex, a.dex);
                return a.name.compareTo(b.name);
            });

            JsonArray order = new JsonArray();
            for (Combatant c : list) {
                JsonObject o = new JsonObject();
                o.put("name", new JsonString(c.name));
                o.put("score", new JsonNumber(c.score()));
                order.add(o);
            }
            JsonObject res = new JsonObject();
            res.put("order", order);
            sendResponse(exchange, 200, res);
        }
    }

    static final class AbilityModifierHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            Integer score = req.getInt("score");
            if (score == null || score < 1 || score > 30) {
                sendResponse(exchange, 400, "{\"error\":\"invalid score\"}");
                return;
            }
            JsonObject res = new JsonObject();
            res.put("score", new JsonNumber(score));
            res.put("modifier", new JsonNumber(abilityModifier(score)));
            sendResponse(exchange, 200, res);
        }
    }

    static final class ProficiencyHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            Integer level = req.getInt("level");
            if (level == null || level < 1 || level > 20) {
                sendResponse(exchange, 400, "{\"error\":\"invalid level\"}");
                return;
            }
            JsonObject res = new JsonObject();
            res.put("level", new JsonNumber(level));
            res.put("proficiency_bonus", new JsonNumber(proficiencyBonus(level)));
            sendResponse(exchange, 200, res);
        }
    }

    static final class DerivedStatsHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req = parseRequest(exchange);
            Integer level = req.getInt("level");
            JsonObject abilities = req.getObject("abilities");
            JsonObject armor = req.getObject("armor");
            if (level == null || level < 1 || level > 20 || abilities == null || armor == null) {
                sendResponse(exchange, 400, "{\"error\":\"invalid request\"}");
                return;
            }

            String[] abilityNames = {"str", "dex", "con", "int", "wis", "cha"};
            Map<String, Integer> scores = new LinkedHashMap<>();
            for (String name : abilityNames) {
                Integer score = abilities.getInt(name);
                if (score == null || score < 1 || score > 30) {
                    sendResponse(exchange, 400, "{\"error\":\"invalid ability\"}");
                    return;
                }
                scores.put(name, score);
            }

            Integer base = armor.getInt("base");
            Boolean shield = armor.getBool("shield");
            Integer dexCap = armor.getInt("dex_cap");
            if (base == null || shield == null || dexCap == null) {
                sendResponse(exchange, 400, "{\"error\":\"invalid armor\"}");
                return;
            }

            int shieldBonus = shield ? 2 : 0;
            int dexModifier = abilityModifier(scores.get("dex"));
            int armorClass = base + Math.min(dexModifier, dexCap) + shieldBonus;

            int conModifier = abilityModifier(scores.get("con"));
            int hpMax = level * (6 + conModifier);

            JsonObject modifiers = new JsonObject();
            for (String name : abilityNames) {
                modifiers.put(name, new JsonNumber(abilityModifier(scores.get(name))));
            }

            JsonObject res = new JsonObject();
            res.put("level", new JsonNumber(level));
            res.put("proficiency_bonus", new JsonNumber(proficiencyBonus(level)));
            res.put("hp_max", new JsonNumber(hpMax));
            res.put("armor_class", new JsonNumber(armorClass));
            res.put("modifiers", modifiers);
            sendResponse(exchange, 200, res);
        }
    }

    static final class Combatant {
        final String name;
        final int dex;
        final int roll;

        Combatant(String name, int dex, int roll) {
            this.name = name;
            this.dex = dex;
            this.roll = roll;
        }

        int score() {
            return roll + dex;
        }
    }

    // ------------------------------------------------------------------
    // Users / authentication
    // ------------------------------------------------------------------

    static record User(String username, String role, String passwordHash) {}

    static final class PasswordHelper {
        private static final int SALT_BYTES = 16;
        private static final int ITERATIONS = 10000;
        private static final int KEY_BITS = 256;

        private final SecureRandom random = new SecureRandom();

        String hash(String password) {
            byte[] salt = new byte[SALT_BYTES];
            random.nextBytes(salt);
            byte[] hash = pbkdf2(password, salt);
            return Base64.getEncoder().encodeToString(salt) + ":" + Base64.getEncoder().encodeToString(hash);
        }

        boolean verify(String password, String stored) {
            int sep = stored.indexOf(':');
            if (sep < 0) {
                return false;
            }
            byte[] salt = Base64.getDecoder().decode(stored.substring(0, sep));
            byte[] expected = Base64.getDecoder().decode(stored.substring(sep + 1));
            byte[] actual = pbkdf2(password, salt);
            return MessageDigest.isEqual(expected, actual);
        }

        private byte[] pbkdf2(String password, byte[] salt) {
            try {
                SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
                PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, KEY_BITS);
                return factory.generateSecret(spec).getEncoded();
            } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
                throw new RuntimeException(e);
            }
        }
    }

    static final class RegisterHandler extends BaseHandler {
        private static final Pattern USERNAME = Pattern.compile("^[a-z0-9_-]{2,32}$");
        private final PasswordHelper passwords = new PasswordHelper();

        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req;
            try {
                req = parseRequest(exchange);
            } catch (Exception e) {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
                return;
            }
            String username = req.getString("username");
            String password = req.getString("password");
            String role = req.getString("role");
            if (username == null || password == null || role == null
                    || !USERNAME.matcher(username).matches()
                    || password.length() < 8
                    || (!"dm".equals(role) && !"player".equals(role))) {
                sendResponse(exchange, 400, "{\"error\":\"invalid request\"}");
                return;
            }
            if (STORAGE.getUser(username) != null) {
                sendResponse(exchange, 409, "{\"error\":\"duplicate username\"}");
                return;
            }
            String hash = passwords.hash(password);
            if (STORAGE.insertUser(username, role, hash)) {
                JsonObject res = new JsonObject();
                res.put("username", new JsonString(username));
                res.put("role", new JsonString(role));
                sendResponse(exchange, 201, res);
            } else {
                sendResponse(exchange, 409, "{\"error\":\"duplicate username\"}");
            }
        }
    }

    static final class LoginHandler extends BaseHandler {
        private final PasswordHelper passwords = new PasswordHelper();

        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            JsonObject req;
            try {
                req = parseRequest(exchange);
            } catch (Exception e) {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
                return;
            }
            String username = req.getString("username");
            String password = req.getString("password");
            if (username == null || password == null) {
                sendResponse(exchange, 400, "{\"error\":\"invalid request\"}");
                return;
            }
            User user = STORAGE.getUser(username);
            if (user == null || !passwords.verify(password, user.passwordHash())) {
                sendResponse(exchange, 401, "{\"error\":\"bad credentials\"}");
                return;
            }
            JsonObject res = new JsonObject();
            res.put("username", new JsonString(user.username()));
            res.put("token", new JsonString("session-" + user.username()));
            sendResponse(exchange, 200, res);
        }
    }

    static final class Condition {
        final String condition;
        int remaining;

        Condition(String condition, int remaining) {
            this.condition = condition;
            this.remaining = remaining;
        }
    }

    static final class CombatSession {
        final String id;
        final List<Combatant> order;
        int round;
        int turnIndex;
        final Map<String, List<Condition>> conditions = new LinkedHashMap<>();

        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.order = order;
            this.round = 1;
            this.turnIndex = 0;
        }
    }

    static final class CombatHandler extends BaseHandler {
        @Override
        void handleRequest(HttpExchange exchange) throws IOException {
            if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
                sendResponse(exchange, 405, "{\"error\":\"method not allowed\"}");
                return;
            }
            String path = exchange.getRequestURI().getPath();
            if (path.equals("/v1/combat/sessions")) {
                createSession(exchange);
                return;
            }
            String prefix = "/v1/combat/sessions/";
            if (!path.startsWith(prefix)) {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
                return;
            }
            String rest = path.substring(prefix.length());
            int slash = rest.indexOf('/');
            if (slash < 0) {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
                return;
            }
            String id = rest.substring(0, slash);
            String action = rest.substring(slash + 1);
            CombatSession session = STORAGE.getCombatSession(id);
            if (session == null) {
                sendResponse(exchange, 404, "{\"error\":\"session not found\"}");
                return;
            }
            if (action.equals("conditions")) {
                addCondition(exchange, session);
            } else if (action.equals("advance")) {
                advanceTurn(exchange, session);
            } else {
                sendResponse(exchange, 400, "{\"error\":\"bad request\"}");
            }
        }

        private void createSession(HttpExchange exchange) throws IOException {
            JsonObject req = parseRequest(exchange);
            String id = req.getString("id");
            JsonArray combatants = req.getArray("combatants");
            if (id == null || combatants == null) {
                sendResponse(exchange, 400, "{\"error\":\"missing fields\"}");
                return;
            }
            if (STORAGE.getCombatSession(id) != null) {
                sendResponse(exchange, 400, "{\"error\":\"duplicate session id\"}");
                return;
            }
            List<Combatant> list = new ArrayList<>();
            for (JsonValue v : combatants.list) {
                if (!(v instanceof JsonObject)) {
                    sendResponse(exchange, 400, "{\"error\":\"bad combatant\"}");
                    return;
                }
                JsonObject c = (JsonObject) v;
                String name = c.getString("name");
                Integer dex = c.getInt("dex");
                Integer roll = c.getInt("roll");
                if (name == null || dex == null || roll == null) {
                    sendResponse(exchange, 400, "{\"error\":\"bad combatant\"}");
                    return;
                }
                list.add(new Combatant(name, dex, roll));
            }
            if (list.isEmpty()) {
                sendResponse(exchange, 400, "{\"error\":\"no combatants\"}");
                return;
            }
            list.sort((a, b) -> {
                int sa = a.score();
                int sb = b.score();
                if (sa != sb) return Integer.compare(sb, sa);
                if (a.dex != b.dex) return Integer.compare(b.dex, a.dex);
                return a.name.compareTo(b.name);
            });
            if (STORAGE.insertCombatSession(id, list)) {
                CombatSession session = STORAGE.getCombatSession(id);
                sendResponse(exchange, 200, sessionResponse(session, false));
            } else {
                sendResponse(exchange, 400, "{\"error\":\"duplicate session id\"}");
            }
        }

        private void addCondition(HttpExchange exchange, CombatSession session) throws IOException {
            JsonObject req = parseRequest(exchange);
            String target = req.getString("target");
            String condition = req.getString("condition");
            Integer duration = req.getInt("duration_rounds");
            if (target == null || condition == null || duration == null || duration <= 0) {
                sendResponse(exchange, 400, "{\"error\":\"invalid condition\"}");
                return;
            }
            boolean found = false;
            for (Combatant c : session.order) {
                if (c.name.equals(target)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                sendResponse(exchange, 400, "{\"error\":\"unknown target\"}");
                return;
            }
            STORAGE.addCondition(session.id, target, condition, duration);
            session = STORAGE.getCombatSession(session.id);
            JsonObject res = new JsonObject();
            res.put("target", new JsonString(target));
            res.put("conditions", conditionsArray(session.conditions.get(target)));
            sendResponse(exchange, 200, res);
        }

        private void advanceTurn(HttpExchange exchange, CombatSession session) throws IOException {
            if (session.order.isEmpty()) {
                sendResponse(exchange, 400, "{\"error\":\"no combatants\"}");
                return;
            }
            int next = session.turnIndex + 1;
            if (next >= session.order.size()) {
                next = 0;
                session.round++;
            }
            session.turnIndex = next;
            Combatant active = session.order.get(next);
            List<Condition> activeConditions = session.conditions.get(active.name);
            if (activeConditions != null) {
                activeConditions.removeIf(c -> {
                    c.remaining--;
                    return c.remaining <= 0;
                });
            }
            STORAGE.updateCombatSession(session);
            sendResponse(exchange, 200, sessionResponse(session, true));
        }

        private JsonObject sessionResponse(CombatSession session, boolean includeConditions) {
            JsonObject res = new JsonObject();
            res.put("id", new JsonString(session.id));
            res.put("round", new JsonNumber(session.round));
            res.put("turn_index", new JsonNumber(session.turnIndex));
            res.put("active", combatantObject(session.order.get(session.turnIndex)));
            JsonArray order = new JsonArray();
            for (Combatant c : session.order) {
                order.add(combatantObject(c));
            }
            res.put("order", order);
            if (includeConditions) {
                res.put("conditions", conditionsMap(session.conditions));
            }
            return res;
        }

        private JsonObject combatantObject(Combatant c) {
            JsonObject o = new JsonObject();
            o.put("name", new JsonString(c.name));
            o.put("score", new JsonNumber(c.score()));
            return o;
        }

        private JsonArray conditionsArray(List<Condition> list) {
            JsonArray arr = new JsonArray();
            if (list != null) {
                for (Condition c : list) {
                    JsonObject o = new JsonObject();
                    o.put("condition", new JsonString(c.condition));
                    o.put("remaining_rounds", new JsonNumber(c.remaining));
                    arr.add(o);
                }
            }
            return arr;
        }

        private JsonObject conditionsMap(Map<String, List<Condition>> map) {
            JsonObject obj = new JsonObject();
            for (Map.Entry<String, List<Condition>> e : map.entrySet()) {
                obj.put(e.getKey(), conditionsArray(e.getValue()));
            }
            return obj;
        }
    }
}
