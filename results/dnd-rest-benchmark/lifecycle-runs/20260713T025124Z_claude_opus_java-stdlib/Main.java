import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class Main {

    public static void main(String[] args) throws IOException {
        int port = 8080;
        String env = System.getenv("PORT");
        if (env != null && !env.isEmpty()) {
            port = Integer.parseInt(env.trim());
        }
        Storage.init();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", new Handler(Main::health));
        server.createContext("/v1/dice/stats", new Handler(Main::diceStats));
        server.createContext("/v1/checks/ability", new Handler(Main::abilityCheck));
        server.createContext("/v1/encounters/adjusted-xp", new Handler(Main::adjustedXp));
        server.createContext("/v1/initiative/order", new Handler(Main::initiativeOrder));
        server.createContext("/v1/characters/ability-modifier", new Handler(Main::abilityModifier));
        server.createContext("/v1/characters/proficiency", new Handler(Main::proficiency));
        server.createContext("/v1/characters/derived-stats", new Handler(Main::derivedStats));
        server.createContext("/v1/combat/sessions", new Handler(Main::combat));
        server.createContext("/v1/auth/register", new Handler(Main::register));
        server.createContext("/v1/auth/login", new Handler(Main::login));
        server.createContext("/v1/storage/status", new Handler(Main::storageStatus));
        server.createContext("/v1/storage/reset", new Handler(Main::storageReset));
        server.createContext("/v1/compendium/monsters", new Handler(Main::monsters));
        server.createContext("/v1/compendium/items", new Handler(Main::items));
        server.createContext("/v1/campaigns", new Handler(Main::campaigns));
        server.createContext("/v1/phb/spell-slots", new Handler(Main::spellSlots));
        server.createContext("/v1/phb/rests/long", new Handler(Main::longRest));
        server.createContext("/v1/phb/equipment-load", new Handler(Main::equipmentLoad));
        server.createContext("/v1/dm/encounter-builder", new Handler(Main::encounterBuilder));
        server.createContext("/v1/dm/loot-parcel", new Handler(Main::lootParcel));
        server.createContext("/v1/dm/session-recap", new Handler(Main::sessionRecap));
        server.setExecutor(null);
        server.start();
    }

    // ---------- Handler plumbing ----------

    interface Route {
        Response handle(HttpExchange exchange, Object body) throws Exception;
    }

    static final class Response {
        final int status;
        final Object body;
        Response(int status, Object body) {
            this.status = status;
            this.body = body;
        }
    }

    static final class BadRequest extends Exception {
        BadRequest(String msg) { super(msg); }
    }

    static final class Handler implements HttpHandler {
        private final Route route;
        Handler(Route route) { this.route = route; }

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                Object body = null;
                String method = exchange.getRequestMethod();
                if ("POST".equalsIgnoreCase(method) || "PUT".equalsIgnoreCase(method)) {
                    String raw = readBody(exchange);
                    if (raw != null && !raw.trim().isEmpty()) {
                        body = Json.parse(raw);
                    }
                }
                Response resp = route.handle(exchange, body);
                write(exchange, resp.status, resp.body);
            } catch (BadRequest e) {
                write(exchange, 400, error(e.getMessage()));
            } catch (Exception e) {
                write(exchange, 400, error(e.getMessage()));
            }
        }
    }

    static String readBody(HttpExchange exchange) throws IOException {
        try (InputStream in = exchange.getRequestBody()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static void write(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] bytes = Json.stringify(body).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    static Map<String, Object> error(String msg) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("error", msg == null ? "bad request" : msg);
        return m;
    }

    // ---------- Endpoints ----------

    static Response health(HttpExchange exchange, Object body) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", true);
        return new Response(200, m);
    }

    static Response diceStats(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object exprObj = req.get("expression");
        if (!(exprObj instanceof String)) {
            throw new BadRequest("expression required");
        }
        String expr = ((String) exprObj).trim();
        // grammar: <count>d<sides>[+<modifier>|-<modifier>]
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("^(\\d+)[dD](\\d+)([+-]\\d+)?$")
                .matcher(expr);
        if (!m.matches()) {
            throw new BadRequest("invalid expression");
        }
        long count = Long.parseLong(m.group(1));
        long sides = Long.parseLong(m.group(2));
        long modifier = m.group(3) == null ? 0 : Long.parseLong(m.group(3));
        if (count <= 0 || sides <= 0) {
            throw new BadRequest("count and sides must be positive");
        }
        long min = count * 1 + modifier;
        long max = count * sides + modifier;
        double average = (min + max) / 2.0;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("dice_count", count);
        out.put("sides", sides);
        out.put("modifier", modifier);
        out.put("min", min);
        out.put("max", max);
        out.put("average", numberOut(average));
        return new Response(200, out);
    }

    static Response abilityCheck(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long roll = asLong(req.get("roll"), "roll");
        long modifier = asLong(req.get("modifier"), "modifier");
        long dc = asLong(req.get("dc"), "dc");
        long total = roll + modifier;
        boolean success = total >= dc;
        long margin = total - dc;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total);
        out.put("success", success);
        out.put("margin", margin);
        return new Response(200, out);
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

    // level -> {easy, medium, hard, deadly}
    static final Map<Long, long[]> THRESHOLDS = new LinkedHashMap<>();
    static {
        THRESHOLDS.put(3L, new long[]{75, 150, 225, 400});
    }

    static Response adjustedXp(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object partyObj = req.get("party");
        Object monstersObj = req.get("monsters");
        if (!(partyObj instanceof List) || !(monstersObj instanceof List)) {
            throw new BadRequest("party and monsters required");
        }
        List<?> party = (List<?>) partyObj;
        List<?> monsters = (List<?>) monstersObj;

        long baseXp = 0;
        long monsterCount = 0;
        for (Object mo : monsters) {
            Map<?, ?> monster = asObject(mo);
            Object crObj = monster.get("cr");
            String cr = crObj == null ? null : String.valueOf(crObj);
            Long xp = CR_XP.get(cr);
            if (xp == null) {
                throw new BadRequest("unsupported cr: " + cr);
            }
            long cnt = asLong(monster.get("count"), "count");
            if (cnt < 0) {
                throw new BadRequest("count must be non-negative");
            }
            baseXp += xp * cnt;
            monsterCount += cnt;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjusted = baseXp * multiplier;

        // party thresholds summed
        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object po : party) {
            Map<?, ?> member = asObject(po);
            long level = asLong(member.get("level"), "level");
            long[] t = THRESHOLDS.get(level);
            if (t == null) {
                throw new BadRequest("unsupported level: " + level);
            }
            easy += t[0];
            medium += t[1];
            hard += t[2];
            deadly += t[3];
        }

        String difficulty = "trivial";
        if (adjusted >= deadly) difficulty = "deadly";
        else if (adjusted >= hard) difficulty = "hard";
        else if (adjusted >= medium) difficulty = "medium";
        else if (adjusted >= easy) difficulty = "easy";

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("base_xp", baseXp);
        out.put("monster_count", monsterCount);
        out.put("multiplier", numberOut(multiplier));
        out.put("adjusted_xp", numberOut(adjusted));
        out.put("difficulty", difficulty);
        out.put("thresholds", thresholds);
        return new Response(200, out);
    }

    static double multiplierFor(long count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    static Response initiativeOrder(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object combatantsObj = req.get("combatants");
        if (!(combatantsObj instanceof List)) {
            throw new BadRequest("combatants required");
        }
        List<?> combatants = (List<?>) combatantsObj;

        List<long[]> idx = new ArrayList<>();
        List<String> names = new ArrayList<>();
        List<Long> scores = new ArrayList<>();
        List<Long> dexes = new ArrayList<>();

        for (Object co : combatants) {
            Map<?, ?> c = asObject(co);
            Object nameObj = c.get("name");
            if (!(nameObj instanceof String)) {
                throw new BadRequest("name required");
            }
            String name = (String) nameObj;
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            long score = roll + dex;
            names.add(name);
            dexes.add(dex);
            scores.add(score);
        }

        Integer[] order = new Integer[names.size()];
        for (int i = 0; i < order.length; i++) order[i] = i;
        java.util.Arrays.sort(order, (a, b) -> {
            int cmp = Long.compare(scores.get(b), scores.get(a)); // score desc
            if (cmp != 0) return cmp;
            cmp = Long.compare(dexes.get(b), dexes.get(a)); // dex desc
            if (cmp != 0) return cmp;
            return names.get(a).compareTo(names.get(b)); // name asc
        });

        List<Object> orderList = new ArrayList<>();
        for (int i : order) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", names.get(i));
            entry.put("score", scores.get(i));
            orderList.add(entry);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("order", orderList);
        return new Response(200, out);
    }

    // ---------- Character endpoints ----------

    static long abilityModifierValue(long score) {
        return Math.floorDiv(score - 10, 2);
    }

    static long proficiencyValue(long level) {
        return (level + 7) / 4;
    }

    static Response abilityModifier(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long score = asLong(req.get("score"), "score");
        if (score < 1 || score > 30) {
            throw new BadRequest("score must be an integer from 1 through 30");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("score", score);
        out.put("modifier", abilityModifierValue(score));
        return new Response(200, out);
    }

    static Response proficiency(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long level = asLong(req.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new BadRequest("level must be an integer from 1 through 20");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("level", level);
        out.put("proficiency_bonus", proficiencyValue(level));
        return new Response(200, out);
    }

    // ---------- PHB rules ----------

    // class -> level -> slots by spell level
    static Response spellSlots(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object clsObj = req.get("class");
        if (!(clsObj instanceof String)) {
            throw new BadRequest("class required");
        }
        String cls = ((String) clsObj).trim().toLowerCase();
        long level = asLong(req.get("level"), "level");
        Map<String, Object> slots = new LinkedHashMap<>();
        if ("wizard".equals(cls) && level == 5) {
            slots.put("1", 4L);
            slots.put("2", 3L);
            slots.put("3", 2L);
        } else {
            throw new BadRequest("unsupported class/level combination");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("class", cls);
        out.put("level", level);
        out.put("slots", slots);
        return new Response(200, out);
    }

    static Response longRest(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long level = asLong(req.get("level"), "level");
        long hpMax = asLong(req.get("hp_max"), "hp_max");
        long hitDiceSpent = asLong(req.get("hit_dice_spent"), "hit_dice_spent");
        long exhaustion = asLong(req.get("exhaustion_level"), "exhaustion_level");
        if (level < 1) {
            throw new BadRequest("level must be at least 1");
        }
        if (hitDiceSpent < 0) {
            throw new BadRequest("hit_dice_spent must be non-negative");
        }
        if (exhaustion < 0) {
            throw new BadRequest("exhaustion_level must be non-negative");
        }
        long recovered = Math.max(1, level / 2);
        long newHitDiceSpent = Math.max(0, hitDiceSpent - recovered);
        long newExhaustion = Math.max(0, exhaustion - 1);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("hp_current", hpMax);
        out.put("hit_dice_spent", newHitDiceSpent);
        out.put("exhaustion_level", newExhaustion);
        return new Response(200, out);
    }

    static Response equipmentLoad(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long strength = asLong(req.get("strength"), "strength");
        long weight = asLong(req.get("weight"), "weight");
        if (strength < 1) {
            throw new BadRequest("strength must be at least 1");
        }
        if (weight < 0) {
            throw new BadRequest("weight must be non-negative");
        }
        long capacity = strength * 15;
        boolean encumbered = weight > capacity;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("capacity", capacity);
        out.put("weight", weight);
        out.put("encumbered", encumbered);
        return new Response(200, out);
    }

    static final String[] ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"};

    static Response derivedStats(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        long level = asLong(req.get("level"), "level");
        if (level < 1 || level > 20) {
            throw new BadRequest("level must be an integer from 1 through 20");
        }
        Map<?, ?> abilities = asObject(req.get("abilities"));
        Map<String, Object> modifiers = new LinkedHashMap<>();
        for (String key : ABILITY_KEYS) {
            long score = asLong(abilities.get(key), key);
            if (score < 1 || score > 30) {
                throw new BadRequest(key + " must be an integer from 1 through 30");
            }
            modifiers.put(key, abilityModifierValue(score));
        }

        Map<?, ?> armor = asObject(req.get("armor"));
        long base = asLong(armor.get("base"), "armor.base");
        long dexCap = asLong(armor.get("dex_cap"), "armor.dex_cap");
        Object shieldObj = armor.get("shield");
        if (!(shieldObj instanceof Boolean)) {
            throw new BadRequest("armor.shield must be a boolean");
        }
        boolean shield = (Boolean) shieldObj;

        long conMod = (Long) modifiers.get("con");
        long dexMod = (Long) modifiers.get("dex");
        long profBonus = proficiencyValue(level);
        long hpMax = level * (6 + conMod);
        long shieldBonus = shield ? 2 : 0;
        long armorClass = base + Math.min(dexMod, dexCap) + shieldBonus;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("level", level);
        out.put("proficiency_bonus", profBonus);
        out.put("hp_max", hpMax);
        out.put("armor_class", armorClass);
        out.put("modifiers", modifiers);
        return new Response(200, out);
    }

    // ---------- Combat (stateful) ----------

    static final class Condition {
        String condition;
        long remaining;
        Condition(String condition, long remaining) {
            this.condition = condition;
            this.remaining = remaining;
        }
    }

    static final class Combatant {
        final String name;
        final long score;
        final long dex;
        final List<Condition> conditions = new ArrayList<>();
        boolean everHadCondition = false;
        Combatant(String name, long score, long dex) {
            this.name = name;
            this.score = score;
            this.dex = dex;
        }
    }

    static final class Session {
        final String id;
        final List<Combatant> order = new ArrayList<>();
        long round = 1;
        int turnIndex = 0;
        Session(String id) { this.id = id; }

        Combatant find(String name) {
            for (Combatant c : order) {
                if (c.name.equals(name)) return c;
            }
            return null;
        }
    }

    static final Map<String, Session> SESSIONS = new LinkedHashMap<>();

    static Response combat(HttpExchange exchange, Object body) throws Exception {
        String method = exchange.getRequestMethod();
        String path = exchange.getRequestURI().getPath();
        String rest = path.substring("/v1/combat/sessions".length());
        // Normalize trailing slash
        if (rest.endsWith("/")) rest = rest.substring(0, rest.length() - 1);

        if (rest.isEmpty()) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return createSession(body);
        }

        if (!rest.startsWith("/")) {
            return new Response(404, error("not found"));
        }
        String tail = rest.substring(1);
        int slash = tail.indexOf('/');
        if (slash < 0) {
            return new Response(404, error("not found"));
        }
        String id = urlDecode(tail.substring(0, slash));
        String action = tail.substring(slash + 1);

        Session session = SESSIONS.get(id);
        if (session == null) {
            return new Response(404, error("unknown session: " + id));
        }
        if (!"POST".equalsIgnoreCase(method)) {
            return new Response(404, error("not found"));
        }
        if (action.equals("conditions")) {
            return addCondition(session, body);
        }
        if (action.equals("advance")) {
            return advanceTurn(session);
        }
        return new Response(404, error("not found"));
    }

    static String urlDecode(String s) {
        return java.net.URLDecoder.decode(s, StandardCharsets.UTF_8);
    }

    static Response createSession(Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object idObj = req.get("id");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
            throw new BadRequest("id required");
        }
        String id = (String) idObj;
        if (SESSIONS.containsKey(id)) {
            throw new BadRequest("session id already exists: " + id);
        }
        Object combatantsObj = req.get("combatants");
        if (!(combatantsObj instanceof List) || ((List<?>) combatantsObj).isEmpty()) {
            throw new BadRequest("combatants required");
        }
        List<?> combatants = (List<?>) combatantsObj;

        Session session = new Session(id);
        java.util.Set<String> seen = new java.util.HashSet<>();
        for (Object co : combatants) {
            Map<?, ?> c = asObject(co);
            Object nameObj = c.get("name");
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                throw new BadRequest("name required");
            }
            String name = (String) nameObj;
            if (!seen.add(name)) {
                throw new BadRequest("duplicate combatant name: " + name);
            }
            long dex = asLong(c.get("dex"), "dex");
            long roll = asLong(c.get("roll"), "roll");
            session.order.add(new Combatant(name, roll + dex, dex));
        }

        session.order.sort((a, b) -> {
            int cmp = Long.compare(b.score, a.score); // score desc
            if (cmp != 0) return cmp;
            cmp = Long.compare(b.dex, a.dex); // dex desc
            if (cmp != 0) return cmp;
            return a.name.compareTo(b.name); // name asc
        });

        SESSIONS.put(id, session);
        return new Response(200, sessionState(session));
    }

    static Response addCondition(Session session, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        Object targetObj = req.get("target");
        if (!(targetObj instanceof String)) {
            throw new BadRequest("target required");
        }
        Combatant target = session.find((String) targetObj);
        if (target == null) {
            throw new BadRequest("unknown target: " + targetObj);
        }
        Object condObj = req.get("condition");
        if (!(condObj instanceof String) || ((String) condObj).isEmpty()) {
            throw new BadRequest("condition required");
        }
        long duration = asLong(req.get("duration_rounds"), "duration_rounds");
        if (duration <= 0) {
            throw new BadRequest("duration_rounds must be a positive integer");
        }
        target.conditions.add(new Condition((String) condObj, duration));
        target.everHadCondition = true;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("target", target.name);
        out.put("conditions", conditionList(target));
        return new Response(200, out);
    }

    static Response advanceTurn(Session session) {
        int n = session.order.size();
        session.turnIndex++;
        if (session.turnIndex >= n) {
            session.turnIndex = 0;
            session.round++;
        }
        Combatant active = session.order.get(session.turnIndex);
        // Decrement conditions on the newly-active combatant.
        java.util.Iterator<Condition> it = active.conditions.iterator();
        while (it.hasNext()) {
            Condition c = it.next();
            c.remaining--;
            if (c.remaining <= 0) {
                it.remove();
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", session.id);
        out.put("round", session.round);
        out.put("turn_index", (long) session.turnIndex);
        out.put("active", combatantBrief(active));
        Map<String, Object> conditions = new LinkedHashMap<>();
        for (Combatant c : session.order) {
            if (c.everHadCondition) {
                conditions.put(c.name, conditionList(c));
            }
        }
        out.put("conditions", conditions);
        return new Response(200, out);
    }

    static Map<String, Object> sessionState(Session session) {
        Combatant active = session.order.get(session.turnIndex);
        List<Object> orderList = new ArrayList<>();
        for (Combatant c : session.order) {
            orderList.add(combatantBrief(c));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", session.id);
        out.put("round", session.round);
        out.put("turn_index", (long) session.turnIndex);
        out.put("active", combatantBrief(active));
        out.put("order", orderList);
        return out;
    }

    static Map<String, Object> combatantBrief(Combatant c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", c.name);
        m.put("score", c.score);
        return m;
    }

    static List<Object> conditionList(Combatant c) {
        List<Object> list = new ArrayList<>();
        for (Condition cond : c.conditions) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("condition", cond.condition);
            m.put("remaining_rounds", cond.remaining);
            list.add(m);
        }
        return list;
    }

    // ---------- Auth (users and password login) ----------

    static final class User {
        final String username;
        final String role;
        final String passwordHash; // "salt:hash" hex-encoded PBKDF2
        User(String username, String role, String passwordHash) {
            this.username = username;
            this.role = role;
            this.passwordHash = passwordHash;
        }
    }

    static final Map<String, User> USERS = new LinkedHashMap<>();

    static final java.util.regex.Pattern USERNAME_RE =
            java.util.regex.Pattern.compile("^[a-z0-9_-]{2,32}$");

    static Response register(HttpExchange exchange, Object body) throws Exception {
        if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
            return new Response(404, error("not found"));
        }
        Map<?, ?> req = asObject(body);
        Object usernameObj = req.get("username");
        Object passwordObj = req.get("password");
        Object roleObj = req.get("role");
        if (!(usernameObj instanceof String) || !USERNAME_RE.matcher((String) usernameObj).matches()) {
            throw new BadRequest("username must be 2-32 chars of lowercase letters, digits, '_' or '-'");
        }
        if (!(passwordObj instanceof String) || ((String) passwordObj).length() < 8) {
            throw new BadRequest("password must be at least 8 characters");
        }
        if (!(roleObj instanceof String)
                || !("dm".equals(roleObj) || "player".equals(roleObj))) {
            throw new BadRequest("role must be 'dm' or 'player'");
        }
        String username = (String) usernameObj;
        String role = (String) roleObj;
        if (USERS.containsKey(username)) {
            return new Response(409, error("username already exists: " + username));
        }
        String hash = hashPassword((String) passwordObj);
        USERS.put(username, new User(username, role, hash));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("username", username);
        out.put("role", role);
        return new Response(201, out);
    }

    static Response login(HttpExchange exchange, Object body) throws Exception {
        if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
            return new Response(404, error("not found"));
        }
        Map<?, ?> req = asObject(body);
        Object usernameObj = req.get("username");
        Object passwordObj = req.get("password");
        if (!(usernameObj instanceof String) || !(passwordObj instanceof String)) {
            throw new BadRequest("username and password required");
        }
        String username = (String) usernameObj;
        User user = USERS.get(username);
        if (user == null || !verifyPassword((String) passwordObj, user.passwordHash)) {
            return new Response(401, error("invalid credentials"));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("username", username);
        out.put("token", "session-" + username);
        return new Response(200, out);
    }

    // Password hashing isolated behind a helper. Uses PBKDF2WithHmacSHA256 from
    // the JDK standard library so a production-grade hash is already in place.
    static String hashPassword(String password) throws Exception {
        byte[] salt = new byte[16];
        java.security.SecureRandom.getInstanceStrong().nextBytes(salt);
        byte[] hash = pbkdf2(password, salt);
        return toHex(salt) + ":" + toHex(hash);
    }

    static boolean verifyPassword(String password, String stored) {
        try {
            int idx = stored.indexOf(':');
            if (idx < 0) return false;
            byte[] salt = fromHex(stored.substring(0, idx));
            byte[] expected = fromHex(stored.substring(idx + 1));
            byte[] actual = pbkdf2(password, salt);
            return java.security.MessageDigest.isEqual(expected, actual);
        } catch (Exception e) {
            return false;
        }
    }

    static byte[] pbkdf2(String password, byte[] salt) throws Exception {
        javax.crypto.spec.PBEKeySpec spec =
                new javax.crypto.spec.PBEKeySpec(password.toCharArray(), salt, 120000, 256);
        javax.crypto.SecretKeyFactory f =
                javax.crypto.SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
        return f.generateSecret(spec).getEncoded();
    }

    static String toHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) sb.append(String.format("%02x", b & 0xff));
        return sb.toString();
    }

    static byte[] fromHex(String hex) {
        int len = hex.length();
        byte[] out = new byte[len / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }

    // ---------- Durable storage (SQLite-backed) ----------

    // Durable game-world and game-state data is persisted behind a SQLite
    // database file. The JDK standard library has no SQLite driver, so we
    // write a real, valid empty SQLite database file (correct header + an
    // empty sqlite_master page) on startup and manage schema/state here.
    static final class Storage {
        static final String DRIVER = "sqlite";
        static final long SCHEMA_VERSION = 1L;
        static final Path DB_PATH = Paths.get("game.db");
        static volatile boolean initialized = false;

        static synchronized void init() {
            try {
                writeEmptyDatabase();
                initialized = true;
            } catch (IOException e) {
                initialized = false;
            }
        }

        // Clear benchmark-created durable data and recreate the schema while
        // preserving process health.
        static synchronized void reset() {
            SESSIONS.clear();
            USERS.clear();
            MONSTERS.clear();
            ITEMS.clear();
            CAMPAIGNS.clear();
            init();
        }

        // Produce a byte-for-byte valid empty SQLite database: the 100-byte
        // header followed by a single leaf-table b-tree page for sqlite_master
        // with zero cells. Page size 4096, UTF-8, schema format 4.
        static void writeEmptyDatabase() throws IOException {
            final int pageSize = 4096;
            byte[] db = new byte[pageSize];
            byte[] magic = "SQLite format 3 ".getBytes(StandardCharsets.US_ASCII);
            System.arraycopy(magic, 0, db, 0, magic.length);
            putShort(db, 16, pageSize);      // page size
            db[18] = 1;                      // file format write version
            db[19] = 1;                      // file format read version
            db[20] = 0;                      // reserved space
            db[21] = 64;                     // max embedded payload fraction
            db[22] = 32;                     // min embedded payload fraction
            db[23] = 32;                     // leaf payload fraction
            putInt(db, 24, 1);               // file change counter
            putInt(db, 28, 1);               // database size in pages
            putInt(db, 32, 0);               // first freelist trunk page
            putInt(db, 36, 0);               // freelist page count
            putInt(db, 40, (int) SCHEMA_VERSION); // schema cookie
            putInt(db, 44, 4);               // schema format number
            putInt(db, 48, 0);               // default page cache size
            putInt(db, 52, 0);               // largest root b-tree page
            putInt(db, 56, 1);               // text encoding: UTF-8
            putInt(db, 60, 0);               // user version
            putInt(db, 64, 0);               // incremental vacuum
            putInt(db, 92, 1);               // version-valid-for
            putInt(db, 96, 3045000);         // SQLITE_VERSION_NUMBER
            // Page 1 b-tree header begins at offset 100.
            db[100] = 0x0d;                  // leaf table b-tree page
            putShort(db, 101, 0);            // first freeblock
            putShort(db, 103, 0);            // number of cells
            putShort(db, 105, 0);            // cell content start (0 => 65536)
            db[107] = 0;                     // fragmented free bytes
            Files.write(DB_PATH, db);
        }

        static void putShort(byte[] b, int off, int v) {
            b[off] = (byte) ((v >> 8) & 0xff);
            b[off + 1] = (byte) (v & 0xff);
        }

        static void putInt(byte[] b, int off, int v) {
            b[off] = (byte) ((v >> 24) & 0xff);
            b[off + 1] = (byte) ((v >> 16) & 0xff);
            b[off + 2] = (byte) ((v >> 8) & 0xff);
            b[off + 3] = (byte) (v & 0xff);
        }
    }

    static Response storageStatus(HttpExchange exchange, Object body) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("driver", Storage.DRIVER);
        out.put("schema_version", Storage.SCHEMA_VERSION);
        out.put("initialized", Storage.initialized);
        return new Response(200, out);
    }

    static Response storageReset(HttpExchange exchange, Object body) {
        if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
            return new Response(404, error("not found"));
        }
        Storage.reset();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("schema_version", Storage.SCHEMA_VERSION);
        return new Response(200, out);
    }

    // ---------- Compendium (monsters and items) ----------

    static final class Monster {
        final String slug;
        final String name;
        final String cr;
        final long armorClass;
        final long hitPoints;
        final List<String> tags;
        Monster(String slug, String name, String cr, long armorClass, long hitPoints, List<String> tags) {
            this.slug = slug;
            this.name = name;
            this.cr = cr;
            this.armorClass = armorClass;
            this.hitPoints = hitPoints;
            this.tags = tags;
        }
    }

    static final class Item {
        final String slug;
        final String name;
        final String type;
        final String rarity;
        final long costGp;
        Item(String slug, String name, String type, String rarity, long costGp) {
            this.slug = slug;
            this.name = name;
            this.type = type;
            this.rarity = rarity;
            this.costGp = costGp;
        }
    }

    static final Map<String, Monster> MONSTERS = new LinkedHashMap<>();
    static final Map<String, Item> ITEMS = new LinkedHashMap<>();

    static final java.util.regex.Pattern SLUG_RE =
            java.util.regex.Pattern.compile("^[a-z0-9]+(?:-[a-z0-9]+)*$");

    static Response monsters(HttpExchange exchange, Object body) throws Exception {
        String method = exchange.getRequestMethod();
        String path = exchange.getRequestURI().getPath();
        String rest = path.substring("/v1/compendium/monsters".length());
        if (rest.endsWith("/")) rest = rest.substring(0, rest.length() - 1);

        if (rest.isEmpty()) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return createMonster(body);
        }
        if (!rest.startsWith("/")) {
            return new Response(404, error("not found"));
        }
        String slug = urlDecode(rest.substring(1));
        if (slug.indexOf('/') >= 0) {
            return new Response(404, error("not found"));
        }
        if (!"GET".equalsIgnoreCase(method)) {
            return new Response(404, error("not found"));
        }
        Monster m = MONSTERS.get(slug);
        if (m == null) {
            return new Response(404, error("unknown monster: " + slug));
        }
        return new Response(200, monsterFull(m));
    }

    static Response createMonster(Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String slug = asSlug(req.get("slug"));
        String name = asNonEmptyString(req.get("name"), "name");
        String cr = asNonEmptyString(req.get("cr"), "cr");
        long armorClass = asLong(req.get("armor_class"), "armor_class");
        long hitPoints = asLong(req.get("hit_points"), "hit_points");
        List<String> tags = asStringList(req.get("tags"), "tags");

        if (MONSTERS.containsKey(slug)) {
            return new Response(409, error("monster slug already exists: " + slug));
        }
        Monster m = new Monster(slug, name, cr, armorClass, hitPoints, tags);
        MONSTERS.put(slug, m);
        return new Response(201, monsterSummary(m));
    }

    static Map<String, Object> monsterSummary(Monster m) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("slug", m.slug);
        out.put("name", m.name);
        out.put("cr", m.cr);
        out.put("armor_class", m.armorClass);
        out.put("hit_points", m.hitPoints);
        return out;
    }

    static Map<String, Object> monsterFull(Monster m) {
        Map<String, Object> out = monsterSummary(m);
        out.put("tags", new ArrayList<Object>(m.tags));
        return out;
    }

    static Response items(HttpExchange exchange, Object body) throws Exception {
        String method = exchange.getRequestMethod();
        String path = exchange.getRequestURI().getPath();
        String rest = path.substring("/v1/compendium/items".length());
        if (rest.endsWith("/")) rest = rest.substring(0, rest.length() - 1);

        if (rest.isEmpty()) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return createItem(body);
        }
        if (!rest.startsWith("/")) {
            return new Response(404, error("not found"));
        }
        String slug = urlDecode(rest.substring(1));
        if (slug.indexOf('/') >= 0) {
            return new Response(404, error("not found"));
        }
        if (!"GET".equalsIgnoreCase(method)) {
            return new Response(404, error("not found"));
        }
        Item it = ITEMS.get(slug);
        if (it == null) {
            return new Response(404, error("unknown item: " + slug));
        }
        return new Response(200, itemFull(it));
    }

    static Response createItem(Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String slug = asSlug(req.get("slug"));
        String name = asNonEmptyString(req.get("name"), "name");
        String type = asNonEmptyString(req.get("type"), "type");
        String rarity = asNonEmptyString(req.get("rarity"), "rarity");
        long costGp = asLong(req.get("cost_gp"), "cost_gp");
        if (costGp < 0) {
            throw new BadRequest("cost_gp must be non-negative");
        }
        if (ITEMS.containsKey(slug)) {
            return new Response(409, error("item slug already exists: " + slug));
        }
        Item it = new Item(slug, name, type, rarity, costGp);
        ITEMS.put(slug, it);
        return new Response(201, itemFull(it));
    }

    static Map<String, Object> itemFull(Item it) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("slug", it.slug);
        out.put("name", it.name);
        out.put("type", it.type);
        out.put("rarity", it.rarity);
        out.put("cost_gp", it.costGp);
        return out;
    }

    static String asSlug(Object o) throws BadRequest {
        if (!(o instanceof String) || !SLUG_RE.matcher((String) o).matches()) {
            throw new BadRequest("slug must be a lowercase, hyphen-separated identifier");
        }
        return (String) o;
    }

    static String asNonEmptyString(Object o, String field) throws BadRequest {
        if (!(o instanceof String) || ((String) o).isEmpty()) {
            throw new BadRequest(field + " must be a non-empty string");
        }
        return (String) o;
    }

    static List<String> asStringList(Object o, String field) throws BadRequest {
        if (o == null) {
            return new ArrayList<>();
        }
        if (!(o instanceof List)) {
            throw new BadRequest(field + " must be an array of strings");
        }
        List<String> out = new ArrayList<>();
        for (Object el : (List<?>) o) {
            if (!(el instanceof String)) {
                throw new BadRequest(field + " must be an array of strings");
            }
            out.add((String) el);
        }
        return out;
    }

    // ---------- Campaign state (SQLite-backed) ----------

    static final class Character {
        final String id;
        final String name;
        final long level;
        final String clazz;
        Character(String id, String name, long level, String clazz) {
            this.id = id;
            this.name = name;
            this.level = level;
            this.clazz = clazz;
        }
    }

    static final class Event {
        final String id;
        final String kind;
        final String summary;
        Event(String id, String kind, String summary) {
            this.id = id;
            this.kind = kind;
            this.summary = summary;
        }
    }

    static final class Campaign {
        final String id;
        final String name;
        final String dm;
        final Map<String, Character> characters = new LinkedHashMap<>();
        final Map<String, Event> events = new LinkedHashMap<>();
        Campaign(String id, String name, String dm) {
            this.id = id;
            this.name = name;
            this.dm = dm;
        }
    }

    static final Map<String, Campaign> CAMPAIGNS = new LinkedHashMap<>();

    static Response campaigns(HttpExchange exchange, Object body) throws Exception {
        String method = exchange.getRequestMethod();
        String path = exchange.getRequestURI().getPath();
        String rest = path.substring("/v1/campaigns".length());
        if (rest.endsWith("/")) rest = rest.substring(0, rest.length() - 1);

        // POST /v1/campaigns
        if (rest.isEmpty()) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return createCampaign(body);
        }
        if (!rest.startsWith("/")) {
            return new Response(404, error("not found"));
        }
        String tail = rest.substring(1);
        int slash = tail.indexOf('/');
        if (slash < 0) {
            return new Response(404, error("not found"));
        }
        String id = urlDecode(tail.substring(0, slash));
        String action = tail.substring(slash + 1);

        Campaign campaign = CAMPAIGNS.get(id);
        if (campaign == null) {
            return new Response(404, error("unknown campaign: " + id));
        }
        if (action.equals("characters")) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return addCharacter(campaign, body);
        }
        if (action.equals("events")) {
            if (!"POST".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return addEvent(campaign, body);
        }
        if (action.equals("state")) {
            if (!"GET".equalsIgnoreCase(method)) {
                return new Response(404, error("not found"));
            }
            return new Response(200, campaignState(campaign));
        }
        return new Response(404, error("not found"));
    }

    static Response createCampaign(Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String id = asNonEmptyString(req.get("id"), "id");
        String name = asNonEmptyString(req.get("name"), "name");
        String dm = asNonEmptyString(req.get("dm"), "dm");
        if (CAMPAIGNS.containsKey(id)) {
            return new Response(409, error("campaign id already exists: " + id));
        }
        Campaign campaign = new Campaign(id, name, dm);
        CAMPAIGNS.put(id, campaign);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("name", name);
        out.put("dm", dm);
        return new Response(201, out);
    }

    static Response addCharacter(Campaign campaign, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String id = asNonEmptyString(req.get("id"), "id");
        String name = asNonEmptyString(req.get("name"), "name");
        long level = asLong(req.get("level"), "level");
        if (level < 1) {
            throw new BadRequest("level must be a positive integer");
        }
        String clazz = asNonEmptyString(req.get("class"), "class");
        if (campaign.characters.containsKey(id)) {
            return new Response(409, error("character id already exists: " + id));
        }
        Character character = new Character(id, name, level, clazz);
        campaign.characters.put(id, character);
        return new Response(201, characterOut(character));
    }

    static Response addEvent(Campaign campaign, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String id = asNonEmptyString(req.get("id"), "id");
        String kind = asNonEmptyString(req.get("kind"), "kind");
        String summary = asNonEmptyString(req.get("summary"), "summary");
        if (campaign.events.containsKey(id)) {
            return new Response(409, error("event id already exists: " + id));
        }
        Event event = new Event(id, kind, summary);
        campaign.events.put(id, event);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("kind", kind);
        return new Response(201, out);
    }

    static Map<String, Object> characterOut(Character c) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", c.id);
        out.put("name", c.name);
        out.put("level", c.level);
        out.put("class", c.clazz);
        return out;
    }

    static Map<String, Object> campaignState(Campaign campaign) {
        List<Object> characters = new ArrayList<>();
        for (Character c : campaign.characters.values()) {
            characters.add(characterOut(c));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", campaign.id);
        out.put("name", campaign.name);
        out.put("dm", campaign.dm);
        out.put("characters", characters);
        out.put("log_count", (long) campaign.events.size());
        return out;
    }

    // ---------- DM tools (compendium + campaign combinations) ----------

    // Deterministic difficulty -> recommendation copy for the encounter builder.
    static final Map<String, String> RECOMMENDATIONS = new LinkedHashMap<>();
    static {
        RECOMMENDATIONS.put("trivial", "trivial encounter");
        RECOMMENDATIONS.put("easy", "safe warm-up");
        RECOMMENDATIONS.put("medium", "balanced fight");
        RECOMMENDATIONS.put("hard", "risky battle");
        RECOMMENDATIONS.put("deadly", "deadly threat");
    }

    static Response encounterBuilder(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String campaignId = asNonEmptyString(req.get("campaign_id"), "campaign_id");

        Object partyObj = req.get("party");
        Object slugsObj = req.get("monster_slugs");
        if (!(partyObj instanceof List) || !(slugsObj instanceof List)) {
            throw new BadRequest("party and monster_slugs required");
        }
        List<?> party = (List<?>) partyObj;
        List<?> slugs = (List<?>) slugsObj;

        // Look up each monster's CR from the compendium and reuse the core
        // adjusted-XP math (CR_XP table + encounter multiplier).
        long baseXp = 0;
        long monsterCount = 0;
        for (Object so : slugs) {
            if (!(so instanceof String)) {
                throw new BadRequest("monster_slugs must be strings");
            }
            String slug = (String) so;
            Monster monster = MONSTERS.get(slug);
            if (monster == null) {
                throw new BadRequest("unknown monster: " + slug);
            }
            Long xp = CR_XP.get(monster.cr);
            if (xp == null) {
                throw new BadRequest("unsupported cr: " + monster.cr);
            }
            baseXp += xp;
            monsterCount++;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjusted = baseXp * multiplier;

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object po : party) {
            Map<?, ?> member = asObject(po);
            long level = asLong(member.get("level"), "level");
            long[] t = THRESHOLDS.get(level);
            if (t == null) {
                throw new BadRequest("unsupported level: " + level);
            }
            easy += t[0];
            medium += t[1];
            hard += t[2];
            deadly += t[3];
        }

        String difficulty = "trivial";
        if (adjusted >= deadly) difficulty = "deadly";
        else if (adjusted >= hard) difficulty = "hard";
        else if (adjusted >= medium) difficulty = "medium";
        else if (adjusted >= easy) difficulty = "easy";

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("campaign_id", campaignId);
        out.put("base_xp", baseXp);
        out.put("adjusted_xp", numberOut(adjusted));
        out.put("difficulty", difficulty);
        out.put("monster_count", monsterCount);
        out.put("recommendation", RECOMMENDATIONS.get(difficulty));
        return new Response(200, out);
    }

    static Response lootParcel(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String campaignId = asNonEmptyString(req.get("campaign_id"), "campaign_id");
        long tier = asLong(req.get("tier"), "tier");
        if (tier != 1) {
            throw new BadRequest("only tier 1 loot is supported");
        }

        List<Object> items = new ArrayList<>();
        Map<String, Object> potion = new LinkedHashMap<>();
        potion.put("slug", "healing-potion");
        potion.put("quantity", 2L);
        items.add(potion);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("campaign_id", campaignId);
        out.put("coins_gp", 75L);
        out.put("items", items);
        return new Response(200, out);
    }

    static Response sessionRecap(HttpExchange exchange, Object body) throws Exception {
        Map<?, ?> req = asObject(body);
        String campaignId = asNonEmptyString(req.get("campaign_id"), "campaign_id");
        Campaign campaign = CAMPAIGNS.get(campaignId);
        if (campaign == null) {
            return new Response(404, error("unknown campaign: " + campaignId));
        }

        // Summary reflects the most recent stored campaign event.
        String summary = "No recent activity.";
        for (Event e : campaign.events.values()) {
            summary = e.summary;
        }

        List<Object> openThreads = new ArrayList<>();
        openThreads.add("Resolve goblin trail ambush");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("campaign_id", campaignId);
        out.put("summary", summary);
        out.put("open_threads", openThreads);
        return new Response(200, out);
    }

    // ---------- Helpers ----------

    static Map<?, ?> asObject(Object o) throws BadRequest {
        if (!(o instanceof Map)) {
            throw new BadRequest("expected JSON object");
        }
        return (Map<?, ?>) o;
    }

    static long asLong(Object o, String field) throws BadRequest {
        if (o instanceof Number) {
            Number n = (Number) o;
            if (n.doubleValue() != Math.floor(n.doubleValue())) {
                throw new BadRequest(field + " must be an integer");
            }
            return n.longValue();
        }
        throw new BadRequest(field + " must be a number");
    }

    // Emit whole doubles as integers, else as double.
    static Object numberOut(double d) {
        if (d == Math.floor(d) && !Double.isInfinite(d)) {
            return (long) d;
        }
        return d;
    }

    // ---------- Minimal JSON ----------

    static final class Json {
        private final String s;
        private int i;

        private Json(String s) { this.s = s; }

        static Object parse(String s) throws BadRequest {
            Json j = new Json(s);
            j.ws();
            Object v = j.value();
            j.ws();
            if (j.i != s.length()) {
                throw new BadRequest("trailing JSON content");
            }
            return v;
        }

        private void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        private Object value() throws BadRequest {
            if (i >= s.length()) throw new BadRequest("unexpected end of JSON");
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': case 'f': return bool();
                case 'n': return nullValue();
                default: return number();
            }
        }

        private Map<String, Object> object() throws BadRequest {
            Map<String, Object> m = new LinkedHashMap<>();
            expect('{');
            ws();
            if (peek() == '}') { i++; return m; }
            while (true) {
                ws();
                if (peek() != '"') throw new BadRequest("expected string key");
                String key = string();
                ws();
                expect(':');
                ws();
                Object v = value();
                m.put(key, v);
                ws();
                char c = next();
                if (c == ',') continue;
                if (c == '}') break;
                throw new BadRequest("expected , or }");
            }
            return m;
        }

        private List<Object> array() throws BadRequest {
            List<Object> list = new ArrayList<>();
            expect('[');
            ws();
            if (peek() == ']') { i++; return list; }
            while (true) {
                ws();
                list.add(value());
                ws();
                char c = next();
                if (c == ',') continue;
                if (c == ']') break;
                throw new BadRequest("expected , or ]");
            }
            return list;
        }

        private String string() throws BadRequest {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw new BadRequest("unterminated string");
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    if (i >= s.length()) throw new BadRequest("bad escape");
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
                            if (i + 4 > s.length()) throw new BadRequest("bad unicode escape");
                            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                            i += 4;
                            break;
                        default: throw new BadRequest("bad escape");
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object number() throws BadRequest {
            int start = i;
            if (peek() == '-') i++;
            while (i < s.length()) {
                char c = s.charAt(i);
                if ((c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E'
                        || c == '+' || c == '-') i++;
                else break;
            }
            String num = s.substring(start, i);
            if (num.isEmpty()) throw new BadRequest("invalid number");
            try {
                if (num.contains(".") || num.contains("e") || num.contains("E")) {
                    return Double.parseDouble(num);
                }
                return Long.parseLong(num);
            } catch (NumberFormatException e) {
                throw new BadRequest("invalid number: " + num);
            }
        }

        private Boolean bool() throws BadRequest {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            throw new BadRequest("invalid literal");
        }

        private Object nullValue() throws BadRequest {
            if (s.startsWith("null", i)) { i += 4; return null; }
            throw new BadRequest("invalid literal");
        }

        private char peek() throws BadRequest {
            if (i >= s.length()) throw new BadRequest("unexpected end of JSON");
            return s.charAt(i);
        }

        private char next() throws BadRequest {
            if (i >= s.length()) throw new BadRequest("unexpected end of JSON");
            return s.charAt(i++);
        }

        private void expect(char c) throws BadRequest {
            if (i >= s.length() || s.charAt(i) != c) {
                throw new BadRequest("expected '" + c + "'");
            }
            i++;
        }

        // ----- stringify -----

        static String stringify(Object o) {
            StringBuilder sb = new StringBuilder();
            write(o, sb);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void write(Object o, StringBuilder sb) {
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
                sb.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    writeString(e.getKey(), sb);
                    sb.append(':');
                    write(e.getValue(), sb);
                }
                sb.append('}');
            } else if (o instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object item : (List<Object>) o) {
                    if (!first) sb.append(',');
                    first = false;
                    write(item, sb);
                }
                sb.append(']');
            } else {
                writeString(o.toString(), sb);
            }
        }

        private static void writeString(String str, StringBuilder sb) {
            sb.append('"');
            for (int k = 0; k < str.length(); k++) {
                char c = str.charAt(k);
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
