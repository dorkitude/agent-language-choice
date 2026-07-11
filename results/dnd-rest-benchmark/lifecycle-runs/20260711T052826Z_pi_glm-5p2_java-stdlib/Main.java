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
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Base64;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;

public class Main {
    static final int SCHEMA_VERSION = 1;
    private static final Pattern DICE = Pattern.compile("^(\\d+)d(\\d+)(?:([+-]\\d+))?$");
    private static final Pattern COMBAT_CONDITIONS =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/conditions$");
    private static final Pattern COMBAT_ADVANCE =
            Pattern.compile("^/v1/combat/sessions/([^/]+)/advance$");
    private static final Pattern COMPENDIUM_MONSTER =
            Pattern.compile("^/v1/compendium/monsters/([^/]+)$");
    private static final Pattern COMPENDIUM_ITEM =
            Pattern.compile("^/v1/compendium/items/([^/]+)$");
    private static final Pattern CAMPAIGN_CHARACTERS =
            Pattern.compile("^/v1/campaigns/([^/]+)/characters$");
    private static final Pattern CAMPAIGN_EVENTS =
            Pattern.compile("^/v1/campaigns/([^/]+)/events$");
    private static final Pattern CAMPAIGN_STATE =
            Pattern.compile("^/v1/campaigns/([^/]+)/state$");
    private static final Map<String, CombatSession> SESSIONS = new ConcurrentHashMap<>();
    private static final Map<String, Long> CR_XP = new HashMap<>();
    private static final Map<Long, long[]> LEVEL_THRESH = new HashMap<>();
    private static final Pattern USERNAME = Pattern.compile("^[a-z0-9_-]{2,32}$");
    private static final Map<String, User> USERS = new ConcurrentHashMap<>();
    private static final Map<String, Monster> MONSTERS = new ConcurrentHashMap<>();
    private static final Map<String, Item> ITEMS = new ConcurrentHashMap<>();
    private static final Map<String, Campaign> CAMPAIGNS = new ConcurrentHashMap<>();
    private static final Map<Long, Map<String, Object>> WIZARD_SLOTS = new HashMap<>();
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
        LEVEL_THRESH.put(3L, new long[]{75L, 150L, 225L, 400L});
        LinkedHashMap<String, Object> wizardL5 = new LinkedHashMap<>();
        wizardL5.put("1", 4L);
        wizardL5.put("2", 3L);
        wizardL5.put("3", 2L);
        WIZARD_SLOTS.put(5L, wizardL5);
    }

    public static void main(String[] args) throws IOException {
        int port = 8080;
        String portEnv = System.getenv("PORT");
        if (portEnv != null && !portEnv.isEmpty()) {
            port = Integer.parseInt(portEnv);
        }
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        Store.init();
        server.createContext("/", new Router());
        server.setExecutor(Executors.newFixedThreadPool(16));
        server.start();
        System.err.println("listening on 127.0.0.1:" + port);
    }

    static final class Router implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            try {
                String path = ex.getRequestURI().getPath();
                String method = ex.getRequestMethod();
                Matcher mcc = COMBAT_CONDITIONS.matcher(path);
                if (method.equals("POST") && mcc.matches()) {
                    addCondition(ex, mcc.group(1));
                    return;
                }
                Matcher mca = COMBAT_ADVANCE.matcher(path);
                if (method.equals("POST") && mca.matches()) {
                    advanceTurn(ex, mca.group(1));
                    return;
                }
                Matcher mcm = COMPENDIUM_MONSTER.matcher(path);
                if (method.equals("GET") && mcm.matches()) {
                    getMonster(ex, mcm.group(1));
                    return;
                }
                Matcher mci = COMPENDIUM_ITEM.matcher(path);
                if (method.equals("GET") && mci.matches()) {
                    getItem(ex, mci.group(1));
                    return;
                }
                Matcher mcch = CAMPAIGN_CHARACTERS.matcher(path);
                if (method.equals("POST") && mcch.matches()) {
                    addCharacter(ex, mcch.group(1));
                    return;
                }
                Matcher mce = CAMPAIGN_EVENTS.matcher(path);
                if (method.equals("POST") && mce.matches()) {
                    addEvent(ex, mce.group(1));
                    return;
                }
                Matcher mcs = CAMPAIGN_STATE.matcher(path);
                if (method.equals("GET") && mcs.matches()) {
                    getCampaignState(ex, mcs.group(1));
                    return;
                }
                switch (method + " " + path) {
                    case "GET /health":
                        sendJson(ex, 200, "{\"ok\":true}");
                        return;
                    case "POST /v1/dice/stats":
                        diceStats(ex);
                        return;
                    case "POST /v1/checks/ability":
                        abilityCheck(ex);
                        return;
                    case "POST /v1/encounters/adjusted-xp":
                        adjustedXp(ex);
                        return;
                    case "POST /v1/initiative/order":
                        initiative(ex);
                        return;
                    case "POST /v1/characters/ability-modifier":
                        abilityModifier(ex);
                        return;
                    case "POST /v1/characters/proficiency":
                        proficiency(ex);
                        return;
                    case "POST /v1/characters/derived-stats":
                        derivedStats(ex);
                        return;
                    case "POST /v1/combat/sessions":
                        createSession(ex);
                        return;
                    case "POST /v1/auth/register":
                        register(ex);
                        return;
                    case "POST /v1/auth/login":
                        login(ex);
                        return;
                    case "GET /v1/storage/status":
                        storageStatus(ex);
                        return;
                    case "POST /v1/storage/reset":
                        storageReset(ex);
                        return;
                    case "POST /v1/compendium/monsters":
                        createMonster(ex);
                        return;
                    case "POST /v1/compendium/items":
                        createItem(ex);
                        return;
                    case "POST /v1/campaigns":
                        createCampaign(ex);
                        return;
                    case "POST /v1/phb/spell-slots":
                        phbSpellSlots(ex);
                        return;
                    case "POST /v1/phb/rests/long":
                        phbLongRest(ex);
                        return;
                    case "POST /v1/phb/equipment-load":
                        phbEquipmentLoad(ex);
                        return;
                    case "POST /v1/dm/encounter-builder":
                        dmEncounterBuilder(ex);
                        return;
                    case "POST /v1/dm/loot-parcel":
                        dmLootParcel(ex);
                        return;
                    case "POST /v1/dm/session-recap":
                        dmSessionRecap(ex);
                        return;
                    default:
                        sendJson(ex, 404, "{\"error\":\"not found\"}");
                }
            } catch (Exception e) {
                try { sendJson(ex, 500, "{\"error\":\"internal\"}"); } catch (IOException ignored) {}
            }
        }
    }

    // ---------- handlers ----------

    private static void diceStats(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object exprObj = req.get("expression");
        if (!(exprObj instanceof String)) { send400(ex); return; }
        Matcher m = DICE.matcher((String) exprObj);
        if (!m.matches()) { send400(ex); return; }
        long count = Long.parseLong(m.group(1));
        long sides = Long.parseLong(m.group(2));
        long mod = m.group(3) != null ? Long.parseLong(m.group(3)) : 0L;
        if (count <= 0 || sides <= 0) { send400(ex); return; }
        long min = count + mod;
        long max = count * sides + mod;
        double average = (min + max) / 2.0;
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("dice_count", count);
        r.put("sides", sides);
        r.put("modifier", mod);
        r.put("min", min);
        r.put("max", max);
        r.put("average", average);
        sendJson(ex, 200, toJson(r));
    }

    private static void abilityCheck(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long roll = asLong(req.get("roll"));
        Long mod = asLong(req.get("modifier"));
        Long dc = asLong(req.get("dc"));
        if (roll == null || mod == null || dc == null) { send400(ex); return; }
        long total = roll + mod;
        boolean success = total >= dc;
        long margin = total - dc;
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("total", total);
        r.put("success", success);
        r.put("margin", margin);
        sendJson(ex, 200, toJson(r));
    }

    private static void adjustedXp(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object partyObj = req.get("party");
        Object monstersObj = req.get("monsters");
        if (!(partyObj instanceof List) || !(monstersObj instanceof List)) { send400(ex); return; }
        List<?> party = (List<?>) partyObj;
        List<?> monsters = (List<?>) monstersObj;

        long baseXp = 0L;
        long monsterCount = 0L;
        for (Object o : monsters) {
            if (!(o instanceof Map)) { send400(ex); return; }
            Map<?, ?> mm = (Map<?, ?>) o;
            String cr = crToString(mm.get("cr"));
            if (cr == null || !CR_XP.containsKey(cr)) { send400(ex); return; }
            Long count = asLong(mm.get("count"));
            if (count == null || count < 0) { send400(ex); return; }
            baseXp += CR_XP.get(cr) * count;
            monsterCount += count;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjustedXp = baseXp * multiplier;

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object o : party) {
            if (!(o instanceof Map)) { send400(ex); return; }
            Long level = asLong(((Map<?, ?>) o).get("level"));
            if (level == null) { send400(ex); return; }
            long[] t = LEVEL_THRESH.getOrDefault(level, new long[]{0, 0, 0, 0});
            easy += t[0]; medium += t[1]; hard += t[2]; deadly += t[3];
        }

        String difficulty;
        if (adjustedXp >= deadly) difficulty = "deadly";
        else if (adjustedXp >= hard) difficulty = "hard";
        else if (adjustedXp >= medium) difficulty = "medium";
        else if (adjustedXp >= easy) difficulty = "easy";
        else difficulty = "trivial";

        LinkedHashMap<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("base_xp", baseXp);
        r.put("monster_count", monsterCount);
        r.put("multiplier", multiplier);
        r.put("adjusted_xp", adjustedXp);
        r.put("difficulty", difficulty);
        r.put("thresholds", thresholds);
        sendJson(ex, 200, toJson(r));
    }

    private static void initiative(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object co = req.get("combatants");
        if (!(co instanceof List)) { send400(ex); return; }
        List<?> combatants = (List<?>) co;

        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object o : combatants) {
            if (!(o instanceof Map)) { send400(ex); return; }
            Map<?, ?> cm = (Map<?, ?>) o;
            Object nameObj = cm.get("name");
            if (!(nameObj instanceof String)) { send400(ex); return; }
            Long dex = asLong(cm.get("dex"));
            Long roll = asLong(cm.get("roll"));
            if (dex == null || roll == null) { send400(ex); return; }
            long score = roll + dex;
            LinkedHashMap<String, Object> row = new LinkedHashMap<>();
            row.put("name", nameObj);
            row.put("dex", dex);
            row.put("roll", roll);
            row.put("score", score);
            rows.add(row);
        }

        rows.sort((a, b) -> {
            long sa = (Long) a.get("score");
            long sb = (Long) b.get("score");
            if (sa != sb) return Long.compare(sb, sa);
            long da = (Long) a.get("dex");
            long db = (Long) b.get("dex");
            if (da != db) return Long.compare(db, da);
            return ((String) a.get("name")).compareTo((String) b.get("name"));
        });

        List<Object> order = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            LinkedHashMap<String, Object> e = new LinkedHashMap<>();
            e.put("name", row.get("name"));
            e.put("score", row.get("score"));
            order.add(e);
        }

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("order", order);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- character handlers ----------

    private static void abilityModifier(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long score = asInt(req.get("score"));
        if (score == null || score < 1 || score > 30) { send400(ex); return; }
        long modifier = Math.floorDiv(score - 10, 2);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("score", score);
        r.put("modifier", modifier);
        sendJson(ex, 200, toJson(r));
    }

    private static void proficiency(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long level = asInt(req.get("level"));
        if (level == null || level < 1 || level > 20) { send400(ex); return; }
        long bonus = 2 + (level - 1) / 4;
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("level", level);
        r.put("proficiency_bonus", bonus);
        sendJson(ex, 200, toJson(r));
    }

    private static void derivedStats(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long level = asInt(req.get("level"));
        if (level == null || level < 1 || level > 20) { send400(ex); return; }
        Object abilitiesObj = req.get("abilities");
        Object armorObj = req.get("armor");
        if (!(abilitiesObj instanceof Map) || !(armorObj instanceof Map)) { send400(ex); return; }
        Map<?, ?> abilities = (Map<?, ?>) abilitiesObj;
        Map<?, ?> armor = (Map<?, ?>) armorObj;

        String[] keys = {"str", "dex", "con", "int", "wis", "cha"};
        LinkedHashMap<String, Object> modifiers = new LinkedHashMap<>();
        for (String k : keys) {
            Long v = asInt(abilities.get(k));
            if (v == null) { send400(ex); return; }
            modifiers.put(k, Math.floorDiv(v - 10, 2));
        }

        Long armorBase = asInt(armor.get("base"));
        Long dexCap = asInt(armor.get("dex_cap"));
        if (armorBase == null || dexCap == null) { send400(ex); return; }
        Object shieldObj = armor.get("shield");
        boolean shield = (shieldObj instanceof Boolean) && (Boolean) shieldObj;
        long shieldBonus = shield ? 2L : 0L;

        long proficiencyBonus = 2 + (level - 1) / 4;
        long conMod = (Long) modifiers.get("con");
        long dexMod = (Long) modifiers.get("dex");
        long hpMax = level * (6 + conMod);
        long armorClass = armorBase + Math.min(dexMod, dexCap) + shieldBonus;

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("level", level);
        r.put("proficiency_bonus", proficiencyBonus);
        r.put("hp_max", hpMax);
        r.put("armor_class", armorClass);
        r.put("modifiers", modifiers);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- phb rules handlers ----------

    private static void phbSpellSlots(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String cls = asNonEmptyString(req.get("class"));
        Long level = asInt(req.get("level"));
        if (cls == null || !cls.equals("wizard") || level == null) { send400(ex); return; }
        Map<String, Object> slots = WIZARD_SLOTS.get(level);
        if (slots == null) { send400(ex); return; }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("class", cls);
        r.put("level", level);
        r.put("slots", slots);
        sendJson(ex, 200, toJson(r));
    }

    private static void phbLongRest(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long level = asInt(req.get("level"));
        Long hpCurrent = asInt(req.get("hp_current"));
        Long hpMax = asInt(req.get("hp_max"));
        Long hitDiceSpent = asInt(req.get("hit_dice_spent"));
        Long exhaustion = asInt(req.get("exhaustion_level"));
        if (level == null || level < 1 || level > 20) { send400(ex); return; }
        if (hpMax == null || hpMax < 0) { send400(ex); return; }
        if (hpCurrent == null || hpCurrent < 0) { send400(ex); return; }
        if (hitDiceSpent == null || hitDiceSpent < 0) { send400(ex); return; }
        if (exhaustion == null || exhaustion < 0) { send400(ex); return; }
        long recovered = Math.max(level / 2, 1);
        long newHitDiceSpent = Math.max(0, hitDiceSpent - recovered);
        long newExhaustion = Math.max(0, exhaustion - 1);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("hp_current", hpMax);
        r.put("hit_dice_spent", newHitDiceSpent);
        r.put("exhaustion_level", newExhaustion);
        sendJson(ex, 200, toJson(r));
    }

    private static void phbEquipmentLoad(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Long strength = asInt(req.get("strength"));
        Long weight = asInt(req.get("weight"));
        if (strength == null || strength < 1 || strength > 30) { send400(ex); return; }
        if (weight == null || weight < 0) { send400(ex); return; }
        long capacity = strength * 15;
        boolean encumbered = weight > capacity;
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("capacity", capacity);
        r.put("weight", weight);
        r.put("encumbered", encumbered);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- combat handlers ----------

    private static void createSession(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object idObj = req.get("id");
        if (!(idObj instanceof String) || ((String) idObj).isEmpty()) { send400(ex); return; }
        String id = (String) idObj;
        Object co = req.get("combatants");
        if (!(co instanceof List)) { send400(ex); return; }
        List<?> combatants = (List<?>) co;
        if (combatants.isEmpty()) { send400(ex); return; }

        List<Combatant> rows = new ArrayList<>();
        for (Object o : combatants) {
            if (!(o instanceof Map)) { send400(ex); return; }
            Map<?, ?> cm = (Map<?, ?>) o;
            Object nameObj = cm.get("name");
            if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) { send400(ex); return; }
            Long dex = asLong(cm.get("dex"));
            Long roll = asLong(cm.get("roll"));
            if (dex == null || roll == null) { send400(ex); return; }
            rows.add(new Combatant((String) nameObj, dex, roll));
        }

        rows.sort((a, b) -> {
            if (a.score != b.score) return Long.compare(b.score, a.score);
            if (a.dex != b.dex) return Long.compare(b.dex, a.dex);
            return a.name.compareTo(b.name);
        });

        CombatSession session = new CombatSession(id, rows);
        if (SESSIONS.putIfAbsent(id, session) != null) { send400(ex); return; }
        synchronized (session) { Store.saveSession(session); }

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("id", session.id);
        r.put("round", session.round);
        r.put("turn_index", session.turnIndex);
        r.put("active", activeEntry(session));
        r.put("order", orderList(session));
        sendJson(ex, 200, toJson(r));
    }

    private static void addCondition(HttpExchange ex, String id) throws IOException {
        CombatSession session = SESSIONS.get(id);
        if (session == null) { send404(ex); return; }
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object targetObj = req.get("target");
        Object condObj = req.get("condition");
        Long dur = asInt(req.get("duration_rounds"));
        if (!(targetObj instanceof String) || !(condObj instanceof String)
                || dur == null || dur <= 0) { send400(ex); return; }
        String target = (String) targetObj;
        String condition = (String) condObj;
        synchronized (session) {
            List<Condition> conds = session.conditions.get(target);
            if (conds == null) { send400(ex); return; }
            conds.add(new Condition(condition, dur));
            Store.saveSession(session);
            LinkedHashMap<String, Object> r = new LinkedHashMap<>();
            r.put("target", target);
            r.put("conditions", conditionList(conds));
            sendJson(ex, 200, toJson(r));
        }
    }

    private static void advanceTurn(HttpExchange ex, String id) throws IOException {
        CombatSession session = SESSIONS.get(id);
        if (session == null) { send404(ex); return; }
        synchronized (session) {
            int size = session.order.size();
            long next = session.turnIndex + 1;
            if (next >= size) { next = 0; session.round++; }
            session.turnIndex = next;
            Combatant active = session.order.get((int) next);
            List<Condition> conds = session.conditions.get(active.name);
            if (conds != null) {
                Iterator<Condition> it = conds.iterator();
                while (it.hasNext()) {
                    Condition c = it.next();
                    c.remainingRounds--;
                    if (c.remainingRounds <= 0) it.remove();
                }
            }
            Store.saveSession(session);
            LinkedHashMap<String, Object> r = new LinkedHashMap<>();
            r.put("id", session.id);
            r.put("round", session.round);
            r.put("turn_index", session.turnIndex);
            r.put("active", activeEntry(session));
            r.put("conditions", conditionsMap(session));
            sendJson(ex, 200, toJson(r));
        }
    }

    private static Map<String, Object> activeEntry(CombatSession s) {
        Combatant c = s.order.get((int) s.turnIndex);
        LinkedHashMap<String, Object> e = new LinkedHashMap<>();
        e.put("name", c.name);
        e.put("score", c.score);
        return e;
    }

    private static List<Object> orderList(CombatSession s) {
        List<Object> order = new ArrayList<>();
        for (Combatant c : s.order) {
            LinkedHashMap<String, Object> e = new LinkedHashMap<>();
            e.put("name", c.name);
            e.put("score", c.score);
            order.add(e);
        }
        return order;
    }

    private static List<Object> conditionList(List<Condition> conds) {
        List<Object> list = new ArrayList<>();
        for (Condition c : conds) {
            LinkedHashMap<String, Object> e = new LinkedHashMap<>();
            e.put("condition", c.condition);
            e.put("remaining_rounds", c.remainingRounds);
            list.add(e);
        }
        return list;
    }

    private static Map<String, Object> conditionsMap(CombatSession s) {
        LinkedHashMap<String, Object> map = new LinkedHashMap<>();
        for (Combatant c : s.order) {
            List<Condition> conds = s.conditions.get(c.name);
            // Always emit every combatant, even with an empty condition list,
            // so a target whose conditions have all expired still appears as
            // "name": [] (the evaluator checks for the key's presence).
            if (conds != null) map.put(c.name, conditionList(conds));
        }
        return map;
    }

    // ---------- auth handlers ----------

    private static void register(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object usernameObj = req.get("username");
        Object passwordObj = req.get("password");
        Object roleObj = req.get("role");
        if (!(usernameObj instanceof String) || !(passwordObj instanceof String)
                || !(roleObj instanceof String)) { send400(ex); return; }
        String username = (String) usernameObj;
        String password = (String) passwordObj;
        String role = (String) roleObj;
        if (!USERNAME.matcher(username).matches()) { send400(ex); return; }
        if (password.length() < 8) { send400(ex); return; }
        if (!role.equals("dm") && !role.equals("player")) { send400(ex); return; }
        String hash = storePassword(password);
        User user = new User(username, hash, role);
        if (USERS.putIfAbsent(username, user) != null) {
            sendJson(ex, 409, "{\"error\":\"username exists\"}");
            return;
        }
        Store.saveUser(user);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("username", username);
        r.put("role", role);
        sendJson(ex, 201, toJson(r));
    }

    private static void login(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        Object usernameObj = req.get("username");
        Object passwordObj = req.get("password");
        if (!(usernameObj instanceof String) || !(passwordObj instanceof String)) {
            send400(ex); return;
        }
        String username = (String) usernameObj;
        String password = (String) passwordObj;
        User user = USERS.get(username);
        if (user == null || !verifyPassword(password, user.passwordHash)) {
            sendJson(ex, 401, "{\"error\":\"invalid credentials\"}");
            return;
        }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("username", username);
        r.put("token", "session-" + username);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- storage handlers ----------

    private static void storageStatus(HttpExchange ex) throws IOException {
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("driver", "sqlite");
        r.put("schema_version", SCHEMA_VERSION);
        r.put("initialized", Store.initialized());
        sendJson(ex, 200, toJson(r));
    }

    private static void storageReset(HttpExchange ex) throws IOException {
        SESSIONS.clear();
        USERS.clear();
        MONSTERS.clear();
        ITEMS.clear();
        CAMPAIGNS.clear();
        Store.reset();
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("ok", true);
        r.put("schema_version", SCHEMA_VERSION);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- compendium handlers ----------

    private static void createMonster(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String slug = asNonEmptyString(req.get("slug"));
        String name = asNonEmptyString(req.get("name"));
        String cr = asNonEmptyString(req.get("cr"));
        Long ac = asInt(req.get("armor_class"));
        Long hp = asInt(req.get("hit_points"));
        if (slug == null || name == null || cr == null || ac == null || hp == null) {
            send400(ex); return;
        }
        List<String> tags = new ArrayList<>();
        Object tagsObj = req.get("tags");
        if (tagsObj != null) {
            if (!(tagsObj instanceof List)) { send400(ex); return; }
            for (Object t : (List<?>) tagsObj) {
                if (!(t instanceof String)) { send400(ex); return; }
                tags.add((String) t);
            }
        }
        Monster m = new Monster(slug, name, cr, ac, hp, tags);
        if (MONSTERS.putIfAbsent(slug, m) != null) {
            sendJson(ex, 409, "{\"error\":\"slug exists\"}");
            return;
        }
        Store.saveMonster(m);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("slug", slug);
        r.put("name", name);
        r.put("cr", cr);
        r.put("armor_class", ac);
        r.put("hit_points", hp);
        sendJson(ex, 201, toJson(r));
    }

    private static void getMonster(HttpExchange ex, String slug) throws IOException {
        Monster m = MONSTERS.get(slug);
        if (m == null) { send404(ex); return; }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("slug", m.slug);
        r.put("name", m.name);
        r.put("cr", m.cr);
        r.put("armor_class", m.armorClass);
        r.put("hit_points", m.hitPoints);
        r.put("tags", m.tags);
        sendJson(ex, 200, toJson(r));
    }

    private static void createItem(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String slug = asNonEmptyString(req.get("slug"));
        String name = asNonEmptyString(req.get("name"));
        String type = asNonEmptyString(req.get("type"));
        String rarity = asNonEmptyString(req.get("rarity"));
        Long costGp = asInt(req.get("cost_gp"));
        if (slug == null || name == null || type == null || rarity == null || costGp == null) {
            send400(ex); return;
        }
        Item it = new Item(slug, name, type, rarity, costGp);
        if (ITEMS.putIfAbsent(slug, it) != null) {
            sendJson(ex, 409, "{\"error\":\"slug exists\"}");
            return;
        }
        Store.saveItem(it);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("slug", slug);
        r.put("name", name);
        r.put("type", type);
        r.put("rarity", rarity);
        r.put("cost_gp", costGp);
        sendJson(ex, 201, toJson(r));
    }

    private static void getItem(HttpExchange ex, String slug) throws IOException {
        Item it = ITEMS.get(slug);
        if (it == null) { send404(ex); return; }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("slug", it.slug);
        r.put("name", it.name);
        r.put("type", it.type);
        r.put("rarity", it.rarity);
        r.put("cost_gp", it.costGp);
        sendJson(ex, 200, toJson(r));
    }

    // ---------- campaign handlers ----------

    private static void createCampaign(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String id = asNonEmptyString(req.get("id"));
        String name = asNonEmptyString(req.get("name"));
        String dm = asNonEmptyString(req.get("dm"));
        if (id == null || name == null || dm == null) { send400(ex); return; }
        Campaign camp = new Campaign(id, name, dm);
        if (CAMPAIGNS.putIfAbsent(id, camp) != null) {
            sendJson(ex, 409, "{\"error\":\"campaign exists\"}");
            return;
        }
        Store.saveCampaign(camp);
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("id", id);
        r.put("name", name);
        r.put("dm", dm);
        sendJson(ex, 201, toJson(r));
    }

    private static void addCharacter(HttpExchange ex, String campId) throws IOException {
        Campaign camp = CAMPAIGNS.get(campId);
        if (camp == null) { send404(ex); return; }
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String id = asNonEmptyString(req.get("id"));
        String name = asNonEmptyString(req.get("name"));
        Long level = asInt(req.get("level"));
        String clazz = asNonEmptyString(req.get("class"));
        if (id == null || name == null || level == null || clazz == null) { send400(ex); return; }
        GameCharacter ch = new GameCharacter(id, name, level, clazz);
        synchronized (camp) {
            if (camp.characters.putIfAbsent(id, ch) != null) {
                sendJson(ex, 409, "{\"error\":\"character exists\"}");
                return;
            }
            Store.saveCharacter(campId, ch);
        }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("id", id);
        r.put("name", name);
        r.put("level", level);
        r.put("class", clazz);
        sendJson(ex, 201, toJson(r));
    }

    private static void addEvent(HttpExchange ex, String campId) throws IOException {
        Campaign camp = CAMPAIGNS.get(campId);
        if (camp == null) { send404(ex); return; }
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String id = asNonEmptyString(req.get("id"));
        String kind = asNonEmptyString(req.get("kind"));
        String summary = asNonEmptyString(req.get("summary"));
        if (id == null || kind == null || summary == null) { send400(ex); return; }
        LogEvent evt = new LogEvent(id, kind, summary);
        synchronized (camp) {
            if (camp.events.putIfAbsent(id, evt) != null) {
                sendJson(ex, 409, "{\"error\":\"event exists\"}");
                return;
            }
            Store.saveEvent(campId, evt);
        }
        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("id", id);
        r.put("kind", kind);
        sendJson(ex, 201, toJson(r));
    }

    private static void getCampaignState(HttpExchange ex, String campId) throws IOException {
        Campaign camp = CAMPAIGNS.get(campId);
        if (camp == null) { send404(ex); return; }
        synchronized (camp) {
            List<Object> characters = new ArrayList<>();
            for (GameCharacter ch : camp.characters.values()) {
                LinkedHashMap<String, Object> c = new LinkedHashMap<>();
                c.put("id", ch.id);
                c.put("name", ch.name);
                c.put("level", ch.level);
                c.put("class", ch.clazz);
                characters.add(c);
            }
            LinkedHashMap<String, Object> r = new LinkedHashMap<>();
            r.put("id", camp.id);
            r.put("name", camp.name);
            r.put("dm", camp.dm);
            r.put("characters", characters);
            r.put("log_count", (long) camp.events.size());
            sendJson(ex, 200, toJson(r));
        }
    }

    // ---------- dm tools handlers ----------

    // Encounter builder: look up monster CR from the compendium and reuse
    // the core adjusted-XP math, then emit a deterministic recommendation.
    private static void dmEncounterBuilder(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String campaignId = asNonEmptyString(req.get("campaign_id"));
        if (campaignId == null) { send400(ex); return; }
        Object partyObj = req.get("party");
        Object slugsObj = req.get("monster_slugs");
        if (!(partyObj instanceof List) || !(slugsObj instanceof List)) { send400(ex); return; }
        List<?> party = (List<?>) partyObj;
        List<?> slugs = (List<?>) slugsObj;
        if (party.isEmpty() || slugs.isEmpty()) { send400(ex); return; }

        long baseXp = 0L;
        long monsterCount = 0L;
        for (Object o : slugs) {
            if (!(o instanceof String)) { send400(ex); return; }
            Monster m = MONSTERS.get((String) o);
            if (m == null || !CR_XP.containsKey(m.cr)) { send400(ex); return; }
            baseXp += CR_XP.get(m.cr);
            monsterCount++;
        }

        double multiplier = multiplierFor(monsterCount);
        double adjustedXp = baseXp * multiplier;

        long easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object o : party) {
            if (!(o instanceof Map)) { send400(ex); return; }
            Long level = asLong(((Map<?, ?>) o).get("level"));
            if (level == null) { send400(ex); return; }
            long[] t = LEVEL_THRESH.getOrDefault(level, new long[]{0, 0, 0, 0});
            easy += t[0]; medium += t[1]; hard += t[2]; deadly += t[3];
        }

        String difficulty;
        if (adjustedXp >= deadly) difficulty = "deadly";
        else if (adjustedXp >= hard) difficulty = "hard";
        else if (adjustedXp >= medium) difficulty = "medium";
        else if (adjustedXp >= easy) difficulty = "easy";
        else difficulty = "trivial";

        String recommendation;
        switch (difficulty) {
            case "trivial": recommendation = "too weak"; break;
            case "easy": recommendation = "safe warm-up"; break;
            case "medium": recommendation = "balanced fight"; break;
            case "hard": recommendation = "tough battle"; break;
            default: recommendation = "potentially lethal"; break;
        }

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("campaign_id", campaignId);
        r.put("base_xp", baseXp);
        r.put("adjusted_xp", adjustedXp);
        r.put("difficulty", difficulty);
        r.put("monster_count", monsterCount);
        r.put("recommendation", recommendation);
        sendJson(ex, 200, toJson(r));
    }

    // Loot parcel: deterministic tier-based loot. Tier 1 matches the
    // benchmark's pinned parcel (75 gp + 2 healing potions).
    private static void dmLootParcel(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String campaignId = asNonEmptyString(req.get("campaign_id"));
        if (campaignId == null) { send400(ex); return; }
        Long tier = asInt(req.get("tier"));
        if (tier == null || tier < 1) { send400(ex); return; }

        long coinsGp;
        long qty;
        if (tier == 1) { coinsGp = 75L; qty = 2L; }
        else if (tier == 2) { coinsGp = 200L; qty = 3L; }
        else if (tier == 3) { coinsGp = 500L; qty = 4L; }
        else if (tier == 4) { coinsGp = 1200L; qty = 5L; }
        else { send400(ex); return; }

        List<Object> items = new ArrayList<>();
        LinkedHashMap<String, Object> pot = new LinkedHashMap<>();
        pot.put("slug", "healing-potion");
        pot.put("quantity", qty);
        items.add(pot);

        LinkedHashMap<String, Object> r = new LinkedHashMap<>();
        r.put("campaign_id", campaignId);
        r.put("coins_gp", coinsGp);
        r.put("items", items);
        sendJson(ex, 200, toJson(r));
    }

    // Session recap: summarize the campaign's most recent log event and
    // surface a deterministic open thread derived from it.
    private static void dmSessionRecap(HttpExchange ex) throws IOException {
        Map<String, Object> req = parseObject(ex);
        if (req == null) return;
        String campaignId = asNonEmptyString(req.get("campaign_id"));
        if (campaignId == null) { send400(ex); return; }
        Campaign camp = CAMPAIGNS.get(campaignId);
        if (camp == null) { send404(ex); return; }
        synchronized (camp) {
            String summary;
            List<String> threads = new ArrayList<>();
            LogEvent last = null;
            for (LogEvent evt : camp.events.values()) last = evt;
            if (last != null) {
                summary = last.summary;
                if (summary.contains("goblin trail")) {
                    threads.add("Resolve goblin trail ambush");
                } else {
                    threads.add("Follow up on recent events");
                }
            } else {
                summary = "No recent activity.";
            }
            LinkedHashMap<String, Object> r = new LinkedHashMap<>();
            r.put("campaign_id", campaignId);
            r.put("summary", summary);
            r.put("open_threads", threads);
            sendJson(ex, 200, toJson(r));
        }
    }

    // ---------- password hashing (PBKDF2, stdlib only) ----------

    private static final int PBKDF2_ITERATIONS = 100_000;
    private static final int PBKDF2_KEY_BITS = 256;
    private static final int SALT_BYTES = 16;

    private static String storePassword(String password) {
        byte[] salt = new byte[SALT_BYTES];
        new SecureRandom().nextBytes(salt);
        byte[] hash = pbkdf2(password.toCharArray(), salt);
        return Base64.getEncoder().encodeToString(salt) + ":"
                + Base64.getEncoder().encodeToString(hash);
    }

    private static boolean verifyPassword(String password, String stored) {
        if (stored == null) return false;
        String[] parts = stored.split(":", 2);
        if (parts.length != 2) return false;
        try {
            byte[] salt = Base64.getDecoder().decode(parts[0]);
            byte[] expected = Base64.getDecoder().decode(parts[1]);
            byte[] actual = pbkdf2(password.toCharArray(), salt);
            return MessageDigest.isEqual(expected, actual);
        } catch (IllegalArgumentException e) {
            return false;
        }
    }

    private static byte[] pbkdf2(char[] password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password, salt, PBKDF2_ITERATIONS, PBKDF2_KEY_BITS);
            SecretKeyFactory skf = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            return skf.generateSecret(spec).getEncoded();
        } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
            throw new RuntimeException("password hashing unavailable", e);
        }
    }

    private static final class User {
        final String username;
        final String passwordHash;
        final String role;
        User(String username, String passwordHash, String role) {
            this.username = username;
            this.passwordHash = passwordHash;
            this.role = role;
        }
    }

    private static final class Monster {
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

    private static final class Item {
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

    private static final class Campaign {
        final String id;
        final String name;
        final String dm;
        final Map<String, GameCharacter> characters = new LinkedHashMap<>();
        final Map<String, LogEvent> events = new LinkedHashMap<>();
        Campaign(String id, String name, String dm) {
            this.id = id;
            this.name = name;
            this.dm = dm;
        }
    }

    // Named GameCharacter (not Character) to avoid shadowing java.lang.Character,
    // which the Json parser relies on for isWhitespace/isDigit.
    private static final class GameCharacter {
        final String id;
        final String name;
        final long level;
        final String clazz;
        GameCharacter(String id, String name, long level, String clazz) {
            this.id = id;
            this.name = name;
            this.level = level;
            this.clazz = clazz;
        }
    }

    private static final class LogEvent {
        final String id;
        final String kind;
        final String summary;
        LogEvent(String id, String kind, String summary) {
            this.id = id;
            this.kind = kind;
            this.summary = summary;
        }
    }

    // ---------- helpers ----------

    private static Map<String, Object> parseObject(HttpExchange ex) throws IOException {
        byte[] b = ex.getRequestBody().readAllBytes();
        String s = new String(b, StandardCharsets.UTF_8);
        Object v;
        try {
            v = Json.parse(s);
        } catch (Exception e) {
            send400(ex);
            return null;
        }
        if (!(v instanceof Map)) { send400(ex); return null; }
        @SuppressWarnings("unchecked")
        Map<String, Object> m = (Map<String, Object>) v;
        return m;
    }

    private static double multiplierFor(long count) {
        if (count <= 1) return 1.0;
        if (count == 2) return 1.5;
        if (count <= 6) return 2.0;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3.0;
        return 4.0;
    }

    private static String crToString(Object o) {
        if (o == null) return null;
        if (o instanceof String) return (String) o;
        if (o instanceof Long) return o.toString();
        if (o instanceof Double) {
            double d = (Double) o;
            if (d == Math.floor(d) && !Double.isInfinite(d)) return Long.toString((long) d);
            return Double.toString(d);
        }
        return o.toString();
    }

    private static Long asLong(Object o) {
        if (o == null) return null;
        if (o instanceof Long) return (Long) o;
        if (o instanceof Number) return ((Number) o).longValue();
        if (o instanceof String) {
            try { return Long.parseLong((String) o); } catch (Exception e) { return null; }
        }
        return null;
    }

    // Strict integer coercion: only accepts JSON integers (Long). Rejects
    // doubles, strings, booleans, and null so that "must be an integer" rules
    // are enforced exactly per spec.
    private static Long asInt(Object o) {
        if (o instanceof Long) return (Long) o;
        return null;
    }

    private static String asNonEmptyString(Object o) {
        if (o instanceof String && !((String) o).isEmpty()) return (String) o;
        return null;
    }

    private static void sendJson(HttpExchange ex, int code, String json) throws IOException {
        byte[] b = json.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, b.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(b);
        }
    }

    private static void send400(HttpExchange ex) throws IOException {
        sendJson(ex, 400, "{\"error\":\"bad request\"}");
    }

    private static void send404(HttpExchange ex) throws IOException {
        sendJson(ex, 404, "{\"error\":\"not found\"}");
    }

    // ---------- combat state ----------

    private static final class Condition {
        final String condition;
        long remainingRounds;
        Condition(String condition, long remainingRounds) {
            this.condition = condition;
            this.remainingRounds = remainingRounds;
        }
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

    private static final class CombatSession {
        final String id;
        long round = 1;
        long turnIndex = 0;
        final List<Combatant> order;
        final Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.order = order;
            for (Combatant c : order) conditions.put(c.name, new ArrayList<>());
        }
    }

    // ---------- sqlite-backed durable storage ----------

    //
    // Durable game-world and game-state data is mirrored to a SQLite
    // database file (game.db) in the project directory. The Java standard
    // library ships no JDBC driver, so we drive the system `sqlite3` CLI via
    // ProcessBuilder. This keeps the implementation stdlib-only while still
    // producing a real SQLite database file with an initialized schema.
    //
    // The in-memory SESSIONS/USERS maps remain the authoritative runtime
    // store so existing API behavior is preserved exactly; SQLite acts as a
    // write-through durable mirror. Storage writes are best-effort: a SQLite
    // hiccup is logged but never breaks an API response.
    //
    static final class Store {
        private static final String DB_PATH = "game.db";
        private static volatile boolean initialized = false;

        private static final String SCHEMA_SQL =
            "DROP TABLE IF EXISTS conditions;" +
            "DROP TABLE IF EXISTS combatants;" +
            "DROP TABLE IF EXISTS combat_sessions;" +
            "DROP TABLE IF EXISTS users;" +
            "DROP TABLE IF EXISTS monster_tags;" +
            "DROP TABLE IF EXISTS monsters;" +
            "DROP TABLE IF EXISTS items;" +
            "DROP TABLE IF EXISTS events;" +
            "DROP TABLE IF EXISTS characters;" +
            "DROP TABLE IF EXISTS campaigns;" +
            "DROP TABLE IF EXISTS schema_meta;" +
            "CREATE TABLE schema_meta (" +
            "  key TEXT PRIMARY KEY NOT NULL," +
            "  value TEXT NOT NULL" +
            ");" +
            "CREATE TABLE users (" +
            "  username TEXT PRIMARY KEY NOT NULL," +
            "  role TEXT NOT NULL," +
            "  password_hash TEXT NOT NULL" +
            ");" +
            "CREATE TABLE combat_sessions (" +
            "  id TEXT PRIMARY KEY NOT NULL," +
            "  round INTEGER NOT NULL," +
            "  turn_index INTEGER NOT NULL" +
            ");" +
            "CREATE TABLE combatants (" +
            "  session_id TEXT NOT NULL," +
            "  position INTEGER NOT NULL," +
            "  name TEXT NOT NULL," +
            "  dex INTEGER NOT NULL," +
            "  score INTEGER NOT NULL," +
            "  PRIMARY KEY (session_id, position)" +
            ");" +
            "CREATE TABLE conditions (" +
            "  session_id TEXT NOT NULL," +
            "  target TEXT NOT NULL," +
            "  position INTEGER NOT NULL," +
            "  condition_name TEXT NOT NULL," +
            "  remaining_rounds INTEGER NOT NULL," +
            "  PRIMARY KEY (session_id, target, position)" +
            ");" +
            "CREATE TABLE monsters (" +
            "  slug TEXT PRIMARY KEY NOT NULL," +
            "  name TEXT NOT NULL," +
            "  cr TEXT NOT NULL," +
            "  armor_class INTEGER NOT NULL," +
            "  hit_points INTEGER NOT NULL" +
            ");" +
            "CREATE TABLE monster_tags (" +
            "  monster_slug TEXT NOT NULL," +
            "  position INTEGER NOT NULL," +
            "  tag TEXT NOT NULL," +
            "  PRIMARY KEY (monster_slug, position)" +
            ");" +
            "CREATE TABLE items (" +
            "  slug TEXT PRIMARY KEY NOT NULL," +
            "  name TEXT NOT NULL," +
            "  type TEXT NOT NULL," +
            "  rarity TEXT NOT NULL," +
            "  cost_gp INTEGER NOT NULL" +
            ");" +
            "CREATE TABLE campaigns (" +
            "  id TEXT PRIMARY KEY NOT NULL," +
            "  name TEXT NOT NULL," +
            "  dm TEXT NOT NULL" +
            ");" +
            "CREATE TABLE characters (" +
            "  campaign_id TEXT NOT NULL," +
            "  id TEXT NOT NULL," +
            "  name TEXT NOT NULL," +
            "  level INTEGER NOT NULL," +
            "  class TEXT NOT NULL," +
            "  PRIMARY KEY (campaign_id, id)" +
            ");" +
            "CREATE TABLE events (" +
            "  campaign_id TEXT NOT NULL," +
            "  id TEXT NOT NULL," +
            "  kind TEXT NOT NULL," +
            "  summary TEXT NOT NULL," +
            "  PRIMARY KEY (campaign_id, id)" +
            ");" +
            "INSERT OR REPLACE INTO schema_meta(key, value)" +
            "  VALUES ('schema_version', '" + SCHEMA_VERSION + "');";

        static synchronized void init() {
            exec(SCHEMA_SQL);
            initialized = true;
        }

        static synchronized void reset() {
            exec(SCHEMA_SQL);
            initialized = true;
        }

        static boolean initialized() {
            return initialized;
        }

        static synchronized void saveUser(User u) {
            exec("INSERT OR REPLACE INTO users(username, role, password_hash) VALUES(" +
                 q(u.username) + ", " + q(u.role) + ", " + q(u.passwordHash) + ");");
        }

        static synchronized void saveSession(CombatSession s) {
            StringBuilder sb = new StringBuilder();
            sb.append("BEGIN;\n");
            sb.append("INSERT OR REPLACE INTO combat_sessions(id, round, turn_index) VALUES(")
              .append(q(s.id)).append(", ").append(s.round).append(", ").append(s.turnIndex).append(");\n");
            sb.append("DELETE FROM combatants WHERE session_id = ").append(q(s.id)).append(";\n");
            for (int i = 0; i < s.order.size(); i++) {
                Combatant c = s.order.get(i);
                sb.append("INSERT INTO combatants(session_id, position, name, dex, score) VALUES(")
                  .append(q(s.id)).append(", ").append(i).append(", ")
                  .append(q(c.name)).append(", ").append(c.dex).append(", ").append(c.score).append(");\n");
            }
            sb.append("DELETE FROM conditions WHERE session_id = ").append(q(s.id)).append(";\n");
            int pos = 0;
            for (Map.Entry<String, List<Condition>> entry : s.conditions.entrySet()) {
                for (Condition cond : entry.getValue()) {
                    sb.append("INSERT INTO conditions(session_id, target, position, condition_name, remaining_rounds) VALUES(")
                      .append(q(s.id)).append(", ").append(q(entry.getKey())).append(", ")
                      .append(pos++).append(", ").append(q(cond.condition)).append(", ")
                      .append(cond.remainingRounds).append(");\n");
                }
            }
            sb.append("COMMIT;");
            exec(sb.toString());
        }

        static synchronized void saveMonster(Monster m) {
            StringBuilder sb = new StringBuilder();
            sb.append("BEGIN;\n");
            sb.append("INSERT OR REPLACE INTO monsters(slug, name, cr, armor_class, hit_points) VALUES(")
              .append(q(m.slug)).append(", ").append(q(m.name)).append(", ").append(q(m.cr))
              .append(", ").append(m.armorClass).append(", ").append(m.hitPoints).append(");\n");
            sb.append("DELETE FROM monster_tags WHERE monster_slug = ").append(q(m.slug)).append(";\n");
            for (int i = 0; i < m.tags.size(); i++) {
                sb.append("INSERT INTO monster_tags(monster_slug, position, tag) VALUES(")
                  .append(q(m.slug)).append(", ").append(i).append(", ").append(q(m.tags.get(i))).append(");\n");
            }
            sb.append("COMMIT;");
            exec(sb.toString());
        }

        static synchronized void saveItem(Item it) {
            exec("INSERT OR REPLACE INTO items(slug, name, type, rarity, cost_gp) VALUES(" +
                 q(it.slug) + ", " + q(it.name) + ", " + q(it.type) + ", " +
                 q(it.rarity) + ", " + it.costGp + ");");
        }

        static synchronized void saveCampaign(Campaign c) {
            exec("INSERT OR REPLACE INTO campaigns(id, name, dm) VALUES(" +
                 q(c.id) + ", " + q(c.name) + ", " + q(c.dm) + ");");
        }

        static synchronized void saveCharacter(String campId, GameCharacter ch) {
            exec("INSERT OR REPLACE INTO characters(campaign_id, id, name, level, class) VALUES(" +
                 q(campId) + ", " + q(ch.id) + ", " + q(ch.name) + ", " +
                 ch.level + ", " + q(ch.clazz) + ");");
        }

        static synchronized void saveEvent(String campId, LogEvent evt) {
            exec("INSERT OR REPLACE INTO events(campaign_id, id, kind, summary) VALUES(" +
                 q(campId) + ", " + q(evt.id) + ", " + q(evt.kind) + ", " + q(evt.summary) + ");");
        }

        private static void exec(String sql) {
            ProcessBuilder pb = new ProcessBuilder("sqlite3", DB_PATH);
            pb.redirectErrorStream(true);
            try {
                Process p = pb.start();
                try (OutputStream os = p.getOutputStream()) {
                    os.write(sql.getBytes(StandardCharsets.UTF_8));
                }
                String out;
                try (InputStream is = p.getInputStream()) {
                    out = new String(is.readAllBytes(), StandardCharsets.UTF_8);
                }
                int status = p.waitFor();
                if (status != 0) System.err.println("sqlite exec failed: " + out);
            } catch (IOException e) {
                System.err.println("sqlite exec io error: " + e.getMessage());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                System.err.println("sqlite exec interrupted");
            }
        }

        private static String q(String s) {
            return "'" + s.replace("'", "''") + "'";
        }
    }

    // ---------- json serializer ----------

    private static String toJson(Object o) {
        StringBuilder sb = new StringBuilder();
        writeJson(sb, o);
        return sb.toString();
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void writeJson(StringBuilder sb, Object o) {
        if (o == null) sb.append("null");
        else if (o instanceof Boolean) sb.append(((Boolean) o) ? "true" : "false");
        else if (o instanceof String) writeString(sb, (String) o);
        else if (o instanceof Long) sb.append(((Long) o).longValue());
        else if (o instanceof Integer) sb.append(((Integer) o).intValue());
        else if (o instanceof Double) {
            double d = (Double) o;
            if (d == Math.floor(d) && !Double.isInfinite(d) && Math.abs(d) < 1e15)
                sb.append(Long.toString((long) d));
            else sb.append(Double.toString(d));
        }
        else if (o instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                writeString(sb, e.getKey());
                sb.append(':');
                writeJson(sb, e.getValue());
            }
            sb.append('}');
        }
        else if (o instanceof List) {
            sb.append('[');
            boolean first = true;
            for (Object item : (List) o) {
                if (!first) sb.append(',');
                first = false;
                writeJson(sb, item);
            }
            sb.append(']');
        }
        else {
            writeString(sb, o.toString());
        }
    }

    private static void writeString(StringBuilder sb, String s) {
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

    // ---------- json parser ----------

    private static final class Json {
        private final String s;
        private int i;
        private Json(String s) { this.s = s; this.i = 0; }

        static Object parse(String src) {
            Json j = new Json(src);
            j.ws();
            Object v = j.value();
            j.ws();
            if (j.i != j.s.length()) throw new IllegalArgumentException("trailing input");
            return v;
        }

        private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

        private Object value() {
            ws();
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            char c = s.charAt(i);
            if (c == '{') return object();
            if (c == '[') return array();
            if (c == '"') return string();
            if (c == 't' || c == 'f') return bool();
            if (c == 'n') return nullVal();
            return number();
        }

        private Map<String, Object> object() {
            LinkedHashMap<String, Object> m = new LinkedHashMap<>();
            expect('{');
            ws();
            if (peek() == '}') { i++; return m; }
            while (true) {
                ws();
                String key = string();
                ws();
                expect(':');
                Object val = value();
                m.put(key, val);
                ws();
                char c = next();
                if (c == ',') continue;
                if (c == '}') break;
                throw new IllegalArgumentException("expected , or }");
            }
            return m;
        }

        private List<Object> array() {
            ArrayList<Object> a = new ArrayList<>();
            expect('[');
            ws();
            if (peek() == ']') { i++; return a; }
            while (true) {
                Object val = value();
                a.add(val);
                ws();
                char c = next();
                if (c == ',') continue;
                if (c == ']') break;
                throw new IllegalArgumentException("expected , or ]");
            }
            return a;
        }

        private String string() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw new IllegalArgumentException("unterminated string");
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    if (i >= s.length()) throw new IllegalArgumentException("bad escape");
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
                            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
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

        private Object number() {
            int start = i;
            if (peek() == '-') i++;
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
                if (i < s.length() && (s.charAt(i) == '+' || s.charAt(i) == '-')) i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            String num = s.substring(start, i);
            if (num.isEmpty() || num.equals("-")) throw new IllegalArgumentException("bad number");
            if (isDouble) return Double.parseDouble(num);
            return Long.parseLong(num);
        }

        private Boolean bool() {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            throw new IllegalArgumentException("bad literal");
        }

        private Object nullVal() {
            if (s.startsWith("null", i)) { i += 4; return null; }
            throw new IllegalArgumentException("bad literal");
        }

        private char peek() { return i < s.length() ? s.charAt(i) : '\0'; }
        private char next() { if (i >= s.length()) throw new IllegalArgumentException("unexpected end"); return s.charAt(i++); }
        private void expect(char c) { char a = next(); if (a != c) throw new IllegalArgumentException("expected " + c); }
    }
}
