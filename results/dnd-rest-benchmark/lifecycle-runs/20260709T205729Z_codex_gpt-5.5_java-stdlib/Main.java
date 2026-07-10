import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    private static final Pattern DICE = Pattern.compile("^(\\d+)d(\\d+)([+-]\\d+)?$");
    private static final String COMBAT_SESSIONS_PREFIX = "/v1/combat/sessions/";
    private static final Map<String, CombatSession> COMBAT_SESSIONS = new LinkedHashMap<>();
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
        String rawPort = System.getenv("PORT");
        if (rawPort == null || rawPort.isBlank()) {
            throw new IllegalStateException("PORT is required");
        }
        int port = Integer.parseInt(rawPort);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/", new ApiHandler());
        server.setExecutor(null);
        server.start();
    }

    private static final class ApiHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                String method = exchange.getRequestMethod();
                String path = exchange.getRequestURI().getPath();
                if ("GET".equals(method) && "/health".equals(path)) {
                    sendJson(exchange, 200, Map.of("ok", true));
                    return;
                }
                if (!"POST".equals(method)) {
                    sendText(exchange, 404, "not found");
                    return;
                }

                String rawBody = readBody(exchange);
                Object body = rawBody.isBlank() ? new LinkedHashMap<>() : Json.parse(rawBody);
                if (!(body instanceof Map<?, ?> request)) {
                    sendText(exchange, 400, "invalid json");
                    return;
                }

                if ("/v1/combat/sessions".equals(path)) {
                    sendJson(exchange, 200, createCombatSession(request));
                    return;
                }
                if (path.startsWith(COMBAT_SESSIONS_PREFIX)) {
                    Object response = combatSessionAction(path.substring(COMBAT_SESSIONS_PREFIX.length()), request);
                    if (response == null) {
                        sendText(exchange, 404, "not found");
                    } else {
                        sendJson(exchange, 200, response);
                    }
                    return;
                }

                switch (path) {
                    case "/v1/dice/stats" -> sendJson(exchange, 200, diceStats(request));
                    case "/v1/checks/ability" -> sendJson(exchange, 200, abilityCheck(request));
                    case "/v1/encounters/adjusted-xp" -> sendJson(exchange, 200, adjustedXp(request));
                    case "/v1/initiative/order" -> sendJson(exchange, 200, initiativeOrder(request));
                    case "/v1/characters/ability-modifier" -> sendJson(exchange, 200, abilityModifier(request));
                    case "/v1/characters/proficiency" -> sendJson(exchange, 200, proficiency(request));
                    case "/v1/characters/derived-stats" -> sendJson(exchange, 200, derivedStats(request));
                    default -> sendText(exchange, 404, "not found");
                }
            } catch (BadRequest e) {
                sendText(exchange, 400, "bad request");
            } catch (Exception e) {
                sendText(exchange, 500, "internal error");
            } finally {
                exchange.close();
            }
        }
    }

    private static Map<String, Object> diceStats(Map<?, ?> request) {
        String expression = stringField(request, "expression");
        Matcher matcher = DICE.matcher(expression);
        if (!matcher.matches()) {
            throw new BadRequest();
        }
        int count = parsePositiveInt(matcher.group(1));
        int sides = parsePositiveInt(matcher.group(2));
        int modifier = matcher.group(3) == null ? 0 : parseInt(matcher.group(3));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("dice_count", count);
        response.put("sides", sides);
        response.put("modifier", modifier);
        response.put("min", count + modifier);
        response.put("max", count * sides + modifier);
        response.put("average", count * (sides + 1) / 2.0 + modifier);
        return response;
    }

    private static Map<String, Object> abilityCheck(Map<?, ?> request) {
        int roll = intField(request, "roll");
        int modifier = intField(request, "modifier");
        int dc = intField(request, "dc");
        int total = roll + modifier;

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("total", total);
        response.put("success", total >= dc);
        response.put("margin", total - dc);
        return response;
    }

    private static Map<String, Object> adjustedXp(Map<?, ?> request) {
        List<?> party = listField(request, "party");
        List<?> monsters = listField(request, "monsters");

        int easy = 0;
        int medium = 0;
        int hard = 0;
        int deadly = 0;
        for (Object member : party) {
            Map<?, ?> map = objectValue(member);
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
            Map<?, ?> map = objectValue(monster);
            String cr = stringField(map, "cr");
            int count = intField(map, "count");
            Integer xp = CR_XP.get(cr);
            if (xp == null || count < 0) {
                throw new BadRequest();
            }
            baseXp += xp * count;
            monsterCount += count;
        }

        double multiplier = monsterMultiplier(monsterCount);
        double adjusted = baseXp * multiplier;
        String difficulty = "trivial";
        if (adjusted >= easy) difficulty = "easy";
        if (adjusted >= medium) difficulty = "medium";
        if (adjusted >= hard) difficulty = "hard";
        if (adjusted >= deadly) difficulty = "deadly";

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("base_xp", baseXp);
        response.put("monster_count", monsterCount);
        response.put("multiplier", multiplier);
        response.put("adjusted_xp", adjusted);
        response.put("difficulty", difficulty);
        response.put("thresholds", thresholds);
        return response;
    }

    private static Map<String, Object> initiativeOrder(Map<?, ?> request) {
        List<Combatant> combatants = combatantsField(request);
        combatants.sort(initiativeComparator());

        return Map.of("order", orderList(combatants));
    }

    private static synchronized Map<String, Object> createCombatSession(Map<?, ?> request) {
        String id = stringField(request, "id");
        if (id.isEmpty() || COMBAT_SESSIONS.containsKey(id)) {
            throw new BadRequest();
        }

        List<Combatant> combatants = combatantsField(request);
        if (combatants.isEmpty()) {
            throw new BadRequest();
        }
        combatants.sort(initiativeComparator());

        CombatSession session = new CombatSession(id, combatants);
        COMBAT_SESSIONS.put(id, session);
        return sessionResponse(session);
    }

    private static synchronized Object combatSessionAction(String suffix, Map<?, ?> request) {
        int slash = suffix.indexOf('/');
        if (slash <= 0) {
            return null;
        }
        String id = suffix.substring(0, slash);
        String action = suffix.substring(slash + 1);
        CombatSession session = COMBAT_SESSIONS.get(id);
        if (session == null) {
            return null;
        }

        return switch (action) {
            case "conditions" -> addCondition(session, request);
            case "advance" -> advanceTurn(session);
            default -> null;
        };
    }

    private static Map<String, Object> addCondition(CombatSession session, Map<?, ?> request) {
        String target = stringField(request, "target");
        if (!session.conditions.containsKey(target)) {
            throw new BadRequest();
        }
        String condition = stringField(request, "condition");
        int duration = intField(request, "duration_rounds");
        if (duration <= 0) {
            throw new BadRequest();
        }

        session.conditionTargets.add(target);
        session.conditions.get(target).add(new Condition(condition, duration));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("target", target);
        response.put("conditions", conditionList(session.conditions.get(target)));
        return response;
    }

    private static Map<String, Object> advanceTurn(CombatSession session) {
        session.turnIndex++;
        if (session.turnIndex >= session.order.size()) {
            session.turnIndex = 0;
            session.round++;
        }

        String active = session.order.get(session.turnIndex).name();
        List<Condition> conditions = session.conditions.get(active);
        for (int i = conditions.size() - 1; i >= 0; i--) {
            Condition condition = conditions.get(i);
            condition.remainingRounds--;
            if (condition.remainingRounds <= 0) {
                conditions.remove(i);
            }
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("id", session.id);
        response.put("round", session.round);
        response.put("turn_index", session.turnIndex);
        response.put("active", activeCombatant(session));
        response.put("conditions", conditionsResponse(session));
        return response;
    }

    private static List<Combatant> combatantsField(Map<?, ?> request) {
        List<Combatant> combatants = new ArrayList<>();
        for (Object item : listField(request, "combatants")) {
            Map<?, ?> map = objectValue(item);
            String name = stringField(map, "name");
            int dex = intField(map, "dex");
            int roll = intField(map, "roll");
            combatants.add(new Combatant(name, dex, roll, roll + dex));
        }
        return combatants;
    }

    private static Comparator<Combatant> initiativeComparator() {
        return Comparator
                .comparingInt(Combatant::score).reversed()
                .thenComparing(Comparator.comparingInt(Combatant::dex).reversed())
                .thenComparing(Combatant::name);
    }

    private static Map<String, Object> sessionResponse(CombatSession session) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("id", session.id);
        response.put("round", session.round);
        response.put("turn_index", session.turnIndex);
        response.put("active", activeCombatant(session));
        response.put("order", orderList(session.order));
        return response;
    }

    private static Map<String, Object> activeCombatant(CombatSession session) {
        Combatant combatant = session.order.get(session.turnIndex);
        Map<String, Object> active = new LinkedHashMap<>();
        active.put("name", combatant.name());
        active.put("score", combatant.score());
        return active;
    }

    private static List<Object> orderList(List<Combatant> combatants) {
        List<Object> order = new ArrayList<>();
        for (Combatant combatant : combatants) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", combatant.name());
            entry.put("score", combatant.score());
            order.add(entry);
        }
        return order;
    }

    private static Map<String, Object> conditionsResponse(CombatSession session) {
        Map<String, Object> response = new LinkedHashMap<>();
        for (Combatant combatant : session.order) {
            List<Condition> conditions = session.conditions.get(combatant.name());
            if (!conditions.isEmpty() || session.conditionTargets.contains(combatant.name())) {
                response.put(combatant.name(), conditionList(conditions));
            }
        }
        return response;
    }

    private static List<Object> conditionList(List<Condition> conditions) {
        List<Object> list = new ArrayList<>();
        for (Condition condition : conditions) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("condition", condition.name);
            entry.put("remaining_rounds", condition.remainingRounds);
            list.add(entry);
        }
        return list;
    }

    private static Map<String, Object> abilityModifier(Map<?, ?> request) {
        int score = abilityScoreField(request, "score");

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("score", score);
        response.put("modifier", abilityModifier(score));
        return response;
    }

    private static Map<String, Object> proficiency(Map<?, ?> request) {
        int level = levelField(request, "level");

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("level", level);
        response.put("proficiency_bonus", proficiencyBonus(level));
        return response;
    }

    private static Map<String, Object> derivedStats(Map<?, ?> request) {
        int level = levelField(request, "level");
        Map<?, ?> abilities = objectField(request, "abilities");
        Map<?, ?> armor = objectField(request, "armor");

        Map<String, Object> modifiers = new LinkedHashMap<>();
        int str = abilityModifier(abilityScoreField(abilities, "str"));
        int dex = abilityModifier(abilityScoreField(abilities, "dex"));
        int con = abilityModifier(abilityScoreField(abilities, "con"));
        int intel = abilityModifier(abilityScoreField(abilities, "int"));
        int wis = abilityModifier(abilityScoreField(abilities, "wis"));
        int cha = abilityModifier(abilityScoreField(abilities, "cha"));
        modifiers.put("str", str);
        modifiers.put("dex", dex);
        modifiers.put("con", con);
        modifiers.put("int", intel);
        modifiers.put("wis", wis);
        modifiers.put("cha", cha);

        int armorBase = intField(armor, "base");
        boolean shield = booleanField(armor, "shield");
        int dexCap = intField(armor, "dex_cap");
        int shieldBonus = shield ? 2 : 0;

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("level", level);
        response.put("proficiency_bonus", proficiencyBonus(level));
        response.put("hp_max", level * (6 + con));
        response.put("armor_class", armorBase + Math.min(dex, dexCap) + shieldBonus);
        response.put("modifiers", modifiers);
        return response;
    }

    private static int abilityModifier(int score) {
        return Math.floorDiv(score - 10, 2);
    }

    private static int proficiencyBonus(int level) {
        return 2 + (level - 1) / 4;
    }

    private static double monsterMultiplier(int count) {
        if (count <= 0) return 1.0;
        if (count == 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    private static int parsePositiveInt(String value) {
        int parsed = parseInt(value);
        if (parsed <= 0) {
            throw new BadRequest();
        }
        return parsed;
    }

    private static int parseInt(String value) {
        try {
            return Integer.parseInt(value);
        } catch (NumberFormatException e) {
            throw new BadRequest();
        }
    }

    private static String stringField(Map<?, ?> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof String string)) {
            throw new BadRequest();
        }
        return string;
    }

    private static int intField(Map<?, ?> map, String key) {
        Object value = map.get(key);
        if (value instanceof Integer integer) {
            return integer;
        }
        if (value instanceof Long number && number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE) {
            return number.intValue();
        }
        throw new BadRequest();
    }

    private static int abilityScoreField(Map<?, ?> map, String key) {
        int score = intField(map, key);
        if (score < 1 || score > 30) {
            throw new BadRequest();
        }
        return score;
    }

    private static int levelField(Map<?, ?> map, String key) {
        int level = intField(map, key);
        if (level < 1 || level > 20) {
            throw new BadRequest();
        }
        return level;
    }

    private static boolean booleanField(Map<?, ?> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof Boolean bool)) {
            throw new BadRequest();
        }
        return bool;
    }

    private static List<?> listField(Map<?, ?> map, String key) {
        Object value = map.get(key);
        if (!(value instanceof List<?> list)) {
            throw new BadRequest();
        }
        return list;
    }

    private static Map<?, ?> objectField(Map<?, ?> map, String key) {
        return objectValue(map.get(key));
    }

    private static Map<?, ?> objectValue(Object value) {
        if (!(value instanceof Map<?, ?> map)) {
            throw new BadRequest();
        }
        return map;
    }

    private static String readBody(HttpExchange exchange) throws IOException {
        try (InputStream input = exchange.getRequestBody()) {
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static void sendJson(HttpExchange exchange, int status, Object value) throws IOException {
        byte[] bytes = Json.stringify(value).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private static void sendText(HttpExchange exchange, int status, String value) throws IOException {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "text/plain; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private record Combatant(String name, int dex, int roll, int score) {
    }

    private static final class CombatSession {
        private final String id;
        private final List<Combatant> order;
        private final Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        private final Set<String> conditionTargets = new LinkedHashSet<>();
        private int round = 1;
        private int turnIndex = 0;

        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.order = order;
            for (Combatant combatant : order) {
                conditions.putIfAbsent(combatant.name(), new ArrayList<>());
            }
        }
    }

    private static final class Condition {
        private final String name;
        private int remainingRounds;

        Condition(String name, int remainingRounds) {
            this.name = name;
            this.remainingRounds = remainingRounds;
        }
    }

    private static final class BadRequest extends RuntimeException {
    }

    private static final class Json {
        static Object parse(String source) {
            Parser parser = new Parser(source);
            Object value = parser.parseValue();
            parser.skipWhitespace();
            if (!parser.atEnd()) {
                throw new BadRequest();
            }
            return value;
        }

        static String stringify(Object value) {
            StringBuilder out = new StringBuilder();
            writeValue(out, value);
            return out.toString();
        }

        private static void writeValue(StringBuilder out, Object value) {
            if (value == null) {
                out.append("null");
            } else if (value instanceof String string) {
                writeString(out, string);
            } else if (value instanceof Boolean bool) {
                out.append(bool);
            } else if (value instanceof Integer || value instanceof Long) {
                out.append(value);
            } else if (value instanceof Double number) {
                if (number.isNaN() || number.isInfinite()) {
                    throw new IllegalArgumentException();
                }
                if (number == Math.rint(number)) {
                    out.append(number.longValue());
                } else {
                    out.append(BigDecimal.valueOf(number).stripTrailingZeros().toPlainString());
                }
            } else if (value instanceof Map<?, ?> map) {
                out.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (!first) out.append(',');
                    first = false;
                    writeString(out, String.valueOf(entry.getKey()));
                    out.append(':');
                    writeValue(out, entry.getValue());
                }
                out.append('}');
            } else if (value instanceof List<?> list) {
                out.append('[');
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) out.append(',');
                    writeValue(out, list.get(i));
                }
                out.append(']');
            } else {
                throw new IllegalArgumentException();
            }
        }

        private static void writeString(StringBuilder out, String value) {
            out.append('"');
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
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
        }

        private static final class Parser {
            private final String source;
            private int index;

            Parser(String source) {
                this.source = source == null ? "" : source;
            }

            Object parseValue() {
                skipWhitespace();
                if (atEnd()) {
                    throw new BadRequest();
                }
                char c = source.charAt(index);
                return switch (c) {
                    case '{' -> parseObject();
                    case '[' -> parseArray();
                    case '"' -> parseString();
                    case 't' -> parseLiteral("true", Boolean.TRUE);
                    case 'f' -> parseLiteral("false", Boolean.FALSE);
                    case 'n' -> parseLiteral("null", null);
                    default -> parseNumber();
                };
            }

            private Map<String, Object> parseObject() {
                expect('{');
                Map<String, Object> map = new LinkedHashMap<>();
                skipWhitespace();
                if (take('}')) {
                    return map;
                }
                while (true) {
                    skipWhitespace();
                    if (atEnd() || source.charAt(index) != '"') {
                        throw new BadRequest();
                    }
                    String key = parseString();
                    skipWhitespace();
                    expect(':');
                    map.put(key, parseValue());
                    skipWhitespace();
                    if (take('}')) {
                        return map;
                    }
                    expect(',');
                }
            }

            private List<Object> parseArray() {
                expect('[');
                List<Object> list = new ArrayList<>();
                skipWhitespace();
                if (take(']')) {
                    return list;
                }
                while (true) {
                    list.add(parseValue());
                    skipWhitespace();
                    if (take(']')) {
                        return list;
                    }
                    expect(',');
                }
            }

            private String parseString() {
                expect('"');
                StringBuilder out = new StringBuilder();
                while (!atEnd()) {
                    char c = source.charAt(index++);
                    if (c == '"') {
                        return out.toString();
                    }
                    if (c == '\\') {
                        if (atEnd()) {
                            throw new BadRequest();
                        }
                        char escaped = source.charAt(index++);
                        switch (escaped) {
                            case '"', '\\', '/' -> out.append(escaped);
                            case 'b' -> out.append('\b');
                            case 'f' -> out.append('\f');
                            case 'n' -> out.append('\n');
                            case 'r' -> out.append('\r');
                            case 't' -> out.append('\t');
                            case 'u' -> out.append(parseUnicode());
                            default -> throw new BadRequest();
                        }
                    } else {
                        if (c < 0x20) {
                            throw new BadRequest();
                        }
                        out.append(c);
                    }
                }
                throw new BadRequest();
            }

            private char parseUnicode() {
                if (index + 4 > source.length()) {
                    throw new BadRequest();
                }
                String hex = source.substring(index, index + 4);
                index += 4;
                try {
                    return (char) Integer.parseInt(hex, 16);
                } catch (NumberFormatException e) {
                    throw new BadRequest();
                }
            }

            private Object parseNumber() {
                int start = index;
                if (take('-') && atEnd()) {
                    throw new BadRequest();
                }
                if (take('0')) {
                    if (!atEnd() && Character.isDigit(source.charAt(index))) {
                        throw new BadRequest();
                    }
                } else {
                    if (atEnd() || !Character.isDigit(source.charAt(index))) {
                        throw new BadRequest();
                    }
                    while (!atEnd() && Character.isDigit(source.charAt(index))) {
                        index++;
                    }
                }
                if (!atEnd() && (source.charAt(index) == '.' || source.charAt(index) == 'e' || source.charAt(index) == 'E')) {
                    throw new BadRequest();
                }
                try {
                    long number = Long.parseLong(source.substring(start, index));
                    if (number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE) {
                        return (int) number;
                    }
                    return number;
                } catch (NumberFormatException e) {
                    throw new BadRequest();
                }
            }

            private Object parseLiteral(String literal, Object value) {
                if (!source.startsWith(literal, index)) {
                    throw new BadRequest();
                }
                index += literal.length();
                return value;
            }

            private void expect(char c) {
                if (!take(c)) {
                    throw new BadRequest();
                }
            }

            private boolean take(char c) {
                if (!atEnd() && source.charAt(index) == c) {
                    index++;
                    return true;
                }
                return false;
            }

            private void skipWhitespace() {
                while (!atEnd()) {
                    char c = source.charAt(index);
                    if (c == ' ' || c == '\n' || c == '\r' || c == '\t') {
                        index++;
                    } else {
                        return;
                    }
                }
            }

            private boolean atEnd() {
                return index >= source.length();
            }
        }
    }
}
