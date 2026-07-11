import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.security.spec.KeySpec;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class Main {
    private static final Pattern DICE = Pattern.compile("^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$");
    private static final Pattern USERNAME = Pattern.compile("^[a-z0-9_-]{2,32}$");
    private static final Pattern COMBAT_CONDITIONS = Pattern.compile("^/v1/combat/sessions/([^/]+)/conditions$");
    private static final Pattern COMBAT_ADVANCE = Pattern.compile("^/v1/combat/sessions/([^/]+)/advance$");
    private static final Pattern MONSTER_READ = Pattern.compile("^/v1/compendium/monsters/([^/]+)$");
    private static final Pattern ITEM_READ = Pattern.compile("^/v1/compendium/items/([^/]+)$");
    private static final Pattern CAMPAIGN_CHARACTERS = Pattern.compile("^/v1/campaigns/([^/]+)/characters$");
    private static final Pattern CAMPAIGN_EVENTS = Pattern.compile("^/v1/campaigns/([^/]+)/events$");
    private static final Pattern CAMPAIGN_STATE = Pattern.compile("^/v1/campaigns/([^/]+)/state$");
    private static final Map<String, CombatSession> COMBAT_SESSIONS = new LinkedHashMap<>();
    private static final Map<String, User> USERS = new LinkedHashMap<>();
    private static final Passwords PASSWORDS = new Passwords();
    private static final Storage STORAGE = new Storage();
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
        String portValue = System.getenv("PORT");
        if (portValue == null || portValue.isBlank()) {
            throw new IllegalStateException("PORT is required");
        }

        STORAGE.initialize();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", Integer.parseInt(portValue)), 0);
        server.createContext("/", new Router());
        server.setExecutor(null);
        server.start();
    }

    private static final class Router implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                String method = exchange.getRequestMethod();
                String path = exchange.getRequestURI().getPath();

                if ("GET".equals(method) && "/health".equals(path)) {
                    send(exchange, 200, "{\"ok\":true}");
                    return;
                }
                if ("GET".equals(method) && "/v1/storage/status".equals(path)) {
                    storageStatus(exchange);
                    return;
                }
                if ("GET".equals(method)) {
                    Matcher monsterMatcher = MONSTER_READ.matcher(path);
                    if (monsterMatcher.matches()) {
                        readMonster(exchange, monsterMatcher.group(1));
                        return;
                    }
                    Matcher itemMatcher = ITEM_READ.matcher(path);
                    if (itemMatcher.matches()) {
                        readItem(exchange, itemMatcher.group(1));
                        return;
                    }
                    Matcher campaignStateMatcher = CAMPAIGN_STATE.matcher(path);
                    if (campaignStateMatcher.matches()) {
                        readCampaignState(exchange, campaignStateMatcher.group(1));
                        return;
                    }
                }

                if (!"POST".equals(method)) {
                    send(exchange, 404, "{\"error\":\"not found\"}");
                    return;
                }

                Matcher conditionsMatcher = COMBAT_CONDITIONS.matcher(path);
                if (conditionsMatcher.matches()) {
                    addCondition(exchange, conditionsMatcher.group(1));
                    return;
                }
                Matcher advanceMatcher = COMBAT_ADVANCE.matcher(path);
                if (advanceMatcher.matches()) {
                    advanceCombat(exchange, advanceMatcher.group(1));
                    return;
                }
                Matcher campaignCharactersMatcher = CAMPAIGN_CHARACTERS.matcher(path);
                if (campaignCharactersMatcher.matches()) {
                    addCampaignCharacter(exchange, campaignCharactersMatcher.group(1));
                    return;
                }
                Matcher campaignEventsMatcher = CAMPAIGN_EVENTS.matcher(path);
                if (campaignEventsMatcher.matches()) {
                    addCampaignEvent(exchange, campaignEventsMatcher.group(1));
                    return;
                }

                switch (path) {
                    case "/v1/dice/stats" -> diceStats(exchange);
                    case "/v1/checks/ability" -> abilityCheck(exchange);
                    case "/v1/encounters/adjusted-xp" -> adjustedXp(exchange);
                    case "/v1/initiative/order" -> initiativeOrder(exchange);
                    case "/v1/characters/ability-modifier" -> abilityModifier(exchange);
                    case "/v1/characters/proficiency" -> proficiency(exchange);
                    case "/v1/characters/derived-stats" -> derivedStats(exchange);
                    case "/v1/combat/sessions" -> createCombatSession(exchange);
                    case "/v1/auth/register" -> registerUser(exchange);
                    case "/v1/auth/login" -> login(exchange);
                    case "/v1/storage/reset" -> resetStorage(exchange);
                    case "/v1/compendium/monsters" -> createMonster(exchange);
                    case "/v1/compendium/items" -> createItem(exchange);
                    case "/v1/campaigns" -> createCampaign(exchange);
                    case "/v1/phb/spell-slots" -> spellSlots(exchange);
                    case "/v1/phb/rests/long" -> longRest(exchange);
                    case "/v1/phb/equipment-load" -> equipmentLoad(exchange);
                    case "/v1/dm/encounter-builder" -> dmEncounterBuilder(exchange);
                    case "/v1/dm/loot-parcel" -> dmLootParcel(exchange);
                    case "/v1/dm/session-recap" -> dmSessionRecap(exchange);
                    default -> send(exchange, 404, "{\"error\":\"not found\"}");
                }
            } catch (BadRequest e) {
                send(exchange, 400, "{\"error\":\"bad request\"}");
            } catch (Unauthorized e) {
                send(exchange, 401, "{\"error\":\"unauthorized\"}");
            } catch (Conflict e) {
                send(exchange, 409, "{\"error\":\"conflict\"}");
            } catch (NotFound e) {
                send(exchange, 404, "{\"error\":\"not found\"}");
            } catch (Exception e) {
                send(exchange, 500, "{\"error\":\"internal server error\"}");
            }
        }
    }

    private static void diceStats(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String expression = asString(body.get("expression"));
        Matcher matcher = DICE.matcher(expression);
        if (!matcher.matches()) {
            throw new BadRequest();
        }

        int count = parsePositiveInt(matcher.group(1));
        int sides = parsePositiveInt(matcher.group(2));
        int modifier = 0;
        if (matcher.group(4) != null) {
            modifier = parseNonNegativeInt(matcher.group(4));
            if ("-".equals(matcher.group(3))) {
                modifier = -modifier;
            }
        }

        long min = (long) count + modifier;
        long max = (long) count * sides + modifier;
        double average = count * ((sides + 1) / 2.0) + modifier;

        send(exchange, 200, "{"
                + "\"dice_count\":" + count + ","
                + "\"sides\":" + sides + ","
                + "\"modifier\":" + modifier + ","
                + "\"min\":" + min + ","
                + "\"max\":" + max + ","
                + "\"average\":" + number(average)
                + "}");
    }

    private static void abilityCheck(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int roll = asInt(body.get("roll"));
        int modifier = asInt(body.get("modifier"));
        int dc = asInt(body.get("dc"));
        int total = roll + modifier;
        int margin = total - dc;

        send(exchange, 200, "{"
                + "\"total\":" + total + ","
                + "\"success\":" + (total >= dc) + ","
                + "\"margin\":" + margin
                + "}");
    }

    private static void adjustedXp(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        List<Object> party = asList(body.get("party"));
        List<Object> monsters = asList(body.get("monsters"));
        EncounterMath math = encounterMath(party, monsters);

        send(exchange, 200, "{"
                + "\"base_xp\":" + math.baseXp() + ","
                + "\"monster_count\":" + math.monsterCount() + ","
                + "\"multiplier\":" + number(math.multiplier()) + ","
                + "\"adjusted_xp\":" + number(math.adjustedXp()) + ","
                + "\"difficulty\":\"" + math.difficulty() + "\","
                + "\"thresholds\":{"
                + "\"easy\":" + math.easy() + ","
                + "\"medium\":" + math.medium() + ","
                + "\"hard\":" + math.hard() + ","
                + "\"deadly\":" + math.deadly()
                + "}"
                + "}");
    }

    private static EncounterMath encounterMath(List<Object> party, List<Object> monsters) {
        int easy = 0;
        int medium = 0;
        int hard = 0;
        int deadly = 0;
        for (Object memberObject : party) {
            Map<String, Object> member = asObject(memberObject);
            int level = asInt(member.get("level"));
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
        for (Object monsterObject : monsters) {
            Map<String, Object> monster = asObject(monsterObject);
            String cr = asString(monster.get("cr"));
            int count = asInt(monster.get("count"));
            if (count <= 0 || !CR_XP.containsKey(cr)) {
                throw new BadRequest();
            }
            baseXp += CR_XP.get(cr) * count;
            monsterCount += count;
        }

        double multiplier = monsterMultiplier(monsterCount);
        double adjustedXp = baseXp * multiplier;
        String difficulty = "trivial";
        if (adjustedXp >= deadly) {
            difficulty = "deadly";
        } else if (adjustedXp >= hard) {
            difficulty = "hard";
        } else if (adjustedXp >= medium) {
            difficulty = "medium";
        } else if (adjustedXp >= easy) {
            difficulty = "easy";
        }

        return new EncounterMath(baseXp, monsterCount, multiplier, adjustedXp, difficulty, easy, medium, hard, deadly);
    }

    private static void initiativeOrder(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        List<Object> combatants = asList(body.get("combatants"));
        List<Combatant> order = new ArrayList<>();

        for (Object combatantObject : combatants) {
            Map<String, Object> combatant = asObject(combatantObject);
            String name = asString(combatant.get("name"));
            int dex = asInt(combatant.get("dex"));
            int roll = asInt(combatant.get("roll"));
            order.add(new Combatant(name, dex, roll + dex));
        }

        order.sort(Comparator
                .comparingInt(Combatant::score).reversed()
                .thenComparing(Comparator.comparingInt(Combatant::dex).reversed())
                .thenComparing(Combatant::name));

        StringBuilder json = new StringBuilder("{\"order\":[");
        for (int i = 0; i < order.size(); i++) {
            Combatant combatant = order.get(i);
            if (i > 0) {
                json.append(',');
            }
            json.append("{\"name\":\"")
                    .append(escape(combatant.name()))
                    .append("\",\"score\":")
                    .append(combatant.score())
                    .append('}');
        }
        json.append("]}");
        send(exchange, 200, json.toString());
    }

    private static void abilityModifier(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int score = abilityScore(body.get("score"));
        send(exchange, 200, "{"
                + "\"score\":" + score + ","
                + "\"modifier\":" + abilityModifier(score)
                + "}");
    }

    private static void proficiency(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int level = level(body.get("level"));
        send(exchange, 200, "{"
                + "\"level\":" + level + ","
                + "\"proficiency_bonus\":" + proficiencyBonus(level)
                + "}");
    }

    private static void derivedStats(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int level = level(body.get("level"));
        Map<String, Object> abilities = asObject(body.get("abilities"));
        Map<String, Object> armor = asObject(body.get("armor"));

        int str = abilityModifier(abilityScore(abilities.get("str")));
        int dex = abilityModifier(abilityScore(abilities.get("dex")));
        int con = abilityModifier(abilityScore(abilities.get("con")));
        int intel = abilityModifier(abilityScore(abilities.get("int")));
        int wis = abilityModifier(abilityScore(abilities.get("wis")));
        int cha = abilityModifier(abilityScore(abilities.get("cha")));

        int base = asInt(armor.get("base"));
        int dexCap = asInt(armor.get("dex_cap"));
        int shieldBonus = asBoolean(armor.get("shield")) ? 2 : 0;
        int proficiencyBonus = proficiencyBonus(level);
        int hpMax = level * (6 + con);
        int armorClass = base + Math.min(dex, dexCap) + shieldBonus;

        send(exchange, 200, "{"
                + "\"level\":" + level + ","
                + "\"proficiency_bonus\":" + proficiencyBonus + ","
                + "\"hp_max\":" + hpMax + ","
                + "\"armor_class\":" + armorClass + ","
                + "\"modifiers\":{"
                + "\"str\":" + str + ","
                + "\"dex\":" + dex + ","
                + "\"con\":" + con + ","
                + "\"int\":" + intel + ","
                + "\"wis\":" + wis + ","
                + "\"cha\":" + cha
                + "}"
                + "}");
    }

    private static void createCombatSession(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String id = asString(body.get("id"));
        if (id.isEmpty()) {
            throw new BadRequest();
        }

        List<Combatant> order = initiativeOrderFrom(asList(body.get("combatants")));
        if (order.isEmpty()) {
            throw new BadRequest();
        }

        CombatSession session = new CombatSession(id, order);
        synchronized (COMBAT_SESSIONS) {
            if (COMBAT_SESSIONS.containsKey(id)) {
                throw new BadRequest();
            }
            COMBAT_SESSIONS.put(id, session);
            STORAGE.saveCombatSession(session);
        }

        send(exchange, 200, sessionJson(session, true));
    }

    private static void addCondition(HttpExchange exchange, String id) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String target = asString(body.get("target"));
        String conditionName = asString(body.get("condition"));
        int durationRounds = asInt(body.get("duration_rounds"));
        if (target.isEmpty() || conditionName.isEmpty() || durationRounds <= 0) {
            throw new BadRequest();
        }

        String response;
        synchronized (COMBAT_SESSIONS) {
            CombatSession session = combatSession(id);
            if (!session.hasCombatant(target)) {
                throw new BadRequest();
            }
            List<Condition> conditions = session.conditions.computeIfAbsent(target, ignored -> new ArrayList<>());
            conditions.add(new Condition(conditionName, durationRounds));
            STORAGE.saveConditions(session);
            response = "{\"target\":\"" + escape(target) + "\",\"conditions\":" + conditionsJson(conditions) + "}";
        }

        send(exchange, 200, response);
    }

    private static void advanceCombat(HttpExchange exchange, String id) throws IOException {
        String response;
        synchronized (COMBAT_SESSIONS) {
            CombatSession session = combatSession(id);
            session.turnIndex++;
            if (session.turnIndex >= session.order.size()) {
                session.turnIndex = 0;
                session.round++;
            }
            decrementActiveConditions(session);
            STORAGE.saveCombatState(session);
            response = sessionJson(session, false);
        }
        send(exchange, 200, response);
    }

    private static void registerUser(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String username = asString(body.get("username"));
        String password = asString(body.get("password"));
        String role = asString(body.get("role"));
        if (!USERNAME.matcher(username).matches()
                || password.length() < 8
                || (!"dm".equals(role) && !"player".equals(role))) {
            throw new BadRequest();
        }

        synchronized (USERS) {
            if (USERS.containsKey(username)) {
                throw new Conflict();
            }
            User user = new User(username, role, PASSWORDS.hash(password));
            USERS.put(username, user);
            STORAGE.saveUser(user);
        }

        send(exchange, 201, "{\"username\":\"" + escape(username) + "\",\"role\":\"" + role + "\"}");
    }

    private static void login(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String username = asString(body.get("username"));
        String password = asString(body.get("password"));

        User user;
        synchronized (USERS) {
            user = USERS.get(username);
        }
        if (user == null || !PASSWORDS.verify(password, user.passwordHash())) {
            throw new Unauthorized();
        }

        send(exchange, 200, "{\"username\":\"" + escape(username) + "\",\"token\":\"session-" + escape(username) + "\"}");
    }

    private static void storageStatus(HttpExchange exchange) throws IOException {
        send(exchange, 200, "{\"driver\":\"sqlite\",\"schema_version\":" + Storage.SCHEMA_VERSION + ",\"initialized\":" + STORAGE.initialized() + "}");
    }

    private static void resetStorage(HttpExchange exchange) throws IOException {
        STORAGE.reset();
        synchronized (COMBAT_SESSIONS) {
            COMBAT_SESSIONS.clear();
        }
        synchronized (USERS) {
            USERS.clear();
        }
        send(exchange, 200, "{\"ok\":true,\"schema_version\":" + Storage.SCHEMA_VERSION + "}");
    }

    private static void createMonster(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String slug = compendiumText(body.get("slug"));
        String name = compendiumText(body.get("name"));
        String cr = compendiumText(body.get("cr"));
        int armorClass = nonNegativeField(body.get("armor_class"));
        int hitPoints = nonNegativeField(body.get("hit_points"));
        List<String> tags = compendiumTags(body.get("tags"));

        Monster monster = new Monster(slug, name, cr, armorClass, hitPoints, tags);
        STORAGE.createMonster(monster);
        send(exchange, 201, monsterJson(monster, false));
    }

    private static void readMonster(HttpExchange exchange, String slug) throws IOException {
        Monster monster = STORAGE.findMonster(slug);
        if (monster == null) {
            throw new NotFound();
        }
        send(exchange, 200, monsterJson(monster, true));
    }

    private static void createItem(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String slug = compendiumText(body.get("slug"));
        String name = compendiumText(body.get("name"));
        String type = compendiumText(body.get("type"));
        String rarity = compendiumText(body.get("rarity"));
        int costGp = nonNegativeField(body.get("cost_gp"));

        Item item = new Item(slug, name, type, rarity, costGp);
        STORAGE.createItem(item);
        send(exchange, 201, itemJson(item));
    }

    private static void readItem(HttpExchange exchange, String slug) throws IOException {
        Item item = STORAGE.findItem(slug);
        if (item == null) {
            throw new NotFound();
        }
        send(exchange, 200, itemJson(item));
    }

    private static void createCampaign(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        Campaign campaign = new Campaign(
                campaignText(body.get("id")),
                campaignText(body.get("name")),
                campaignText(body.get("dm")));
        STORAGE.createCampaign(campaign);
        send(exchange, 201, campaignJson(campaign));
    }

    private static void addCampaignCharacter(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> body = readObject(exchange);
        CampaignCharacter character = new CampaignCharacter(
                campaignText(body.get("id")),
                campaignText(body.get("name")),
                level(body.get("level")),
                campaignText(body.get("class")));
        STORAGE.createCampaignCharacter(campaignId, character);
        send(exchange, 201, campaignCharacterJson(character));
    }

    private static void addCampaignEvent(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> body = readObject(exchange);
        CampaignEvent event = new CampaignEvent(
                campaignText(body.get("id")),
                campaignText(body.get("kind")),
                campaignText(body.get("summary")));
        STORAGE.createCampaignEvent(campaignId, event);
        send(exchange, 201, campaignEventJson(event));
    }

    private static void readCampaignState(HttpExchange exchange, String campaignId) throws IOException {
        CampaignState state = STORAGE.findCampaignState(campaignId);
        if (state == null) {
            throw new NotFound();
        }
        send(exchange, 200, campaignStateJson(state));
    }

    private static void spellSlots(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String characterClass = asString(body.get("class"));
        int level = asInt(body.get("level"));
        if (!"wizard".equals(characterClass) || level != 5) {
            throw new BadRequest();
        }

        send(exchange, 200, "{\"class\":\"wizard\",\"level\":5,\"slots\":{\"1\":4,\"2\":3,\"3\":2}}");
    }

    private static void longRest(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int level = level(body.get("level"));
        int hpCurrent = nonNegativeField(body.get("hp_current"));
        int hpMax = nonNegativeField(body.get("hp_max"));
        int hitDiceSpent = nonNegativeField(body.get("hit_dice_spent"));
        int exhaustionLevel = nonNegativeField(body.get("exhaustion_level"));
        if (hpCurrent > hpMax) {
            throw new BadRequest();
        }

        int restoredHitDice = Math.max(1, level / 2);
        int remainingHitDiceSpent = Math.max(0, hitDiceSpent - restoredHitDice);
        int remainingExhaustion = Math.max(0, exhaustionLevel - 1);

        send(exchange, 200, "{"
                + "\"hp_current\":" + hpMax + ","
                + "\"hit_dice_spent\":" + remainingHitDiceSpent + ","
                + "\"exhaustion_level\":" + remainingExhaustion
                + "}");
    }

    private static void equipmentLoad(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        int strength = abilityScore(body.get("strength"));
        int weight = nonNegativeField(body.get("weight"));
        int capacity = strength * 15;

        send(exchange, 200, "{"
                + "\"capacity\":" + capacity + ","
                + "\"weight\":" + weight + ","
                + "\"encumbered\":" + (weight > capacity)
                + "}");
    }

    private static void dmEncounterBuilder(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String campaignId = campaignText(body.get("campaign_id"));
        STORAGE.requireCampaign(campaignId);

        List<Object> monsterSlugs = asList(body.get("monster_slugs"));
        if (monsterSlugs.isEmpty()) {
            throw new BadRequest();
        }
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Object slugObject : monsterSlugs) {
            String slug = compendiumText(slugObject);
            Monster monster = STORAGE.findMonster(slug);
            if (monster == null || !CR_XP.containsKey(monster.cr())) {
                throw new BadRequest();
            }
            counts.merge(monster.cr(), 1, Integer::sum);
        }

        List<Object> monsters = new ArrayList<>();
        for (Map.Entry<String, Integer> entry : counts.entrySet()) {
            Map<String, Object> monster = new LinkedHashMap<>();
            monster.put("cr", entry.getKey());
            monster.put("count", entry.getValue());
            monsters.add(monster);
        }
        EncounterMath math = encounterMath(asList(body.get("party")), monsters);

        send(exchange, 200, "{"
                + "\"campaign_id\":\"" + escape(campaignId) + "\","
                + "\"base_xp\":" + math.baseXp() + ","
                + "\"adjusted_xp\":" + number(math.adjustedXp()) + ","
                + "\"difficulty\":\"" + math.difficulty() + "\","
                + "\"monster_count\":" + math.monsterCount() + ","
                + "\"recommendation\":\"" + recommendation(math.difficulty()) + "\""
                + "}");
    }

    private static void dmLootParcel(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String campaignId = campaignText(body.get("campaign_id"));
        STORAGE.requireCampaign(campaignId);
        int tier = asInt(body.get("tier"));
        asInt(body.get("seed"));
        if (tier != 1) {
            throw new BadRequest();
        }

        send(exchange, 200, "{"
                + "\"campaign_id\":\"" + escape(campaignId) + "\","
                + "\"coins_gp\":75,"
                + "\"items\":[{\"slug\":\"healing-potion\",\"quantity\":2}]"
                + "}");
    }

    private static void dmSessionRecap(HttpExchange exchange) throws IOException {
        Map<String, Object> body = readObject(exchange);
        String campaignId = campaignText(body.get("campaign_id"));
        String summary = STORAGE.latestCampaignEventSummary(campaignId);
        if (summary == null) {
            summary = "";
        }

        send(exchange, 200, "{"
                + "\"campaign_id\":\"" + escape(campaignId) + "\","
                + "\"summary\":\"" + escape(summary) + "\","
                + "\"open_threads\":[\"Resolve goblin trail ambush\"]"
                + "}");
    }

    private static String recommendation(String difficulty) {
        return switch (difficulty) {
            case "easy" -> "safe warm-up";
            case "medium" -> "balanced challenge";
            case "hard" -> "dangerous fight";
            case "deadly" -> "high risk";
            default -> "low risk";
        };
    }

    private static CombatSession combatSession(String id) {
        CombatSession session = COMBAT_SESSIONS.get(id);
        if (session == null) {
            throw new NotFound();
        }
        return session;
    }

    private static List<Combatant> initiativeOrderFrom(List<Object> combatants) {
        List<Combatant> order = new ArrayList<>();
        for (Object combatantObject : combatants) {
            Map<String, Object> combatant = asObject(combatantObject);
            String name = asString(combatant.get("name"));
            if (name.isEmpty()) {
                throw new BadRequest();
            }
            int dex = asInt(combatant.get("dex"));
            int roll = asInt(combatant.get("roll"));
            order.add(new Combatant(name, dex, roll + dex));
        }

        order.sort(Comparator
                .comparingInt(Combatant::score).reversed()
                .thenComparing(Comparator.comparingInt(Combatant::dex).reversed())
                .thenComparing(Combatant::name));
        return order;
    }

    private static void decrementActiveConditions(CombatSession session) {
        String activeName = session.active().name();
        List<Condition> conditions = session.conditions.get(activeName);
        if (conditions == null) {
            return;
        }
        conditions.replaceAll(condition -> new Condition(condition.name(), condition.remainingRounds() - 1));
        conditions.removeIf(condition -> condition.remainingRounds() <= 0);
    }

    private static String sessionJson(CombatSession session, boolean includeOrder) {
        StringBuilder json = new StringBuilder("{");
        json.append("\"id\":\"").append(escape(session.id)).append("\",")
                .append("\"round\":").append(session.round).append(',')
                .append("\"turn_index\":").append(session.turnIndex).append(',')
                .append("\"active\":").append(combatantJson(session.active()));
        if (includeOrder) {
            json.append(",\"order\":").append(orderJson(session.order));
        } else {
            json.append(",\"conditions\":").append(conditionsByTargetJson(session.conditions));
        }
        json.append('}');
        return json.toString();
    }

    private static String orderJson(List<Combatant> order) {
        StringBuilder json = new StringBuilder("[");
        for (int i = 0; i < order.size(); i++) {
            if (i > 0) {
                json.append(',');
            }
            json.append(combatantJson(order.get(i)));
        }
        json.append(']');
        return json.toString();
    }

    private static String combatantJson(Combatant combatant) {
        return "{\"name\":\"" + escape(combatant.name()) + "\",\"score\":" + combatant.score() + "}";
    }

    private static String conditionsByTargetJson(Map<String, List<Condition>> conditionsByTarget) {
        StringBuilder json = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, List<Condition>> entry : conditionsByTarget.entrySet()) {
            if (!first) {
                json.append(',');
            }
            first = false;
            json.append('"').append(escape(entry.getKey())).append("\":").append(conditionsJson(entry.getValue()));
        }
        json.append('}');
        return json.toString();
    }

    private static String conditionsJson(List<Condition> conditions) {
        StringBuilder json = new StringBuilder("[");
        for (int i = 0; i < conditions.size(); i++) {
            Condition condition = conditions.get(i);
            if (i > 0) {
                json.append(',');
            }
            json.append("{\"condition\":\"")
                    .append(escape(condition.name()))
                    .append("\",\"remaining_rounds\":")
                    .append(condition.remainingRounds())
                    .append('}');
        }
        json.append(']');
        return json.toString();
    }

    private static Map<String, Object> readObject(HttpExchange exchange) throws IOException {
        String text;
        try (InputStream input = exchange.getRequestBody()) {
            text = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        return asObject(new JsonParser(text).parse());
    }

    private static void send(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private static double monsterMultiplier(int count) {
        if (count <= 0) {
            return 1.0;
        }
        if (count == 1) {
            return 1.0;
        }
        if (count == 2) {
            return 1.5;
        }
        if (count <= 6) {
            return 2.0;
        }
        if (count <= 10) {
            return 2.5;
        }
        if (count <= 14) {
            return 3.0;
        }
        return 4.0;
    }

    private static String number(double value) {
        if (value == Math.rint(value)) {
            return Long.toString((long) value);
        }
        return Double.toString(value);
    }

    private static int parsePositiveInt(String text) {
        int value = parseNonNegativeInt(text);
        if (value <= 0) {
            throw new BadRequest();
        }
        return value;
    }

    private static int parseNonNegativeInt(String text) {
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException e) {
            throw new BadRequest();
        }
    }

    private static int abilityScore(Object value) {
        return boundedInt(value, 1, 30);
    }

    private static int level(Object value) {
        return boundedInt(value, 1, 20);
    }

    private static int boundedInt(Object value, int min, int max) {
        int number = asInt(value);
        if (number < min || number > max) {
            throw new BadRequest();
        }
        return number;
    }

    private static int abilityModifier(int score) {
        return Math.floorDiv(score - 10, 2);
    }

    private static int proficiencyBonus(int level) {
        return 2 + ((level - 1) / 4);
    }

    private static int nonNegativeField(Object value) {
        int number = asInt(value);
        if (number < 0) {
            throw new BadRequest();
        }
        return number;
    }

    private static String compendiumText(Object value) {
        String text = asString(value);
        if (text.isEmpty()) {
            throw new BadRequest();
        }
        for (int i = 0; i < text.length(); i++) {
            if (text.charAt(i) < 0x20) {
                throw new BadRequest();
            }
        }
        return text;
    }

    private static List<String> compendiumTags(Object value) {
        List<Object> values = asList(value);
        List<String> tags = new ArrayList<>();
        for (Object tag : values) {
            tags.add(compendiumText(tag));
        }
        return tags;
    }

    private static String campaignText(Object value) {
        return compendiumText(value);
    }

    private static String monsterJson(Monster monster, boolean includeTags) {
        StringBuilder json = new StringBuilder("{");
        json.append("\"slug\":\"").append(escape(monster.slug())).append("\",")
                .append("\"name\":\"").append(escape(monster.name())).append("\",")
                .append("\"cr\":\"").append(escape(monster.cr())).append("\",")
                .append("\"armor_class\":").append(monster.armorClass()).append(',')
                .append("\"hit_points\":").append(monster.hitPoints());
        if (includeTags) {
            json.append(",\"tags\":").append(stringArrayJson(monster.tags()));
        }
        json.append('}');
        return json.toString();
    }

    private static String itemJson(Item item) {
        return "{"
                + "\"slug\":\"" + escape(item.slug()) + "\","
                + "\"name\":\"" + escape(item.name()) + "\","
                + "\"type\":\"" + escape(item.type()) + "\","
                + "\"rarity\":\"" + escape(item.rarity()) + "\","
                + "\"cost_gp\":" + item.costGp()
                + "}";
    }

    private static String campaignJson(Campaign campaign) {
        return "{"
                + "\"id\":\"" + escape(campaign.id()) + "\","
                + "\"name\":\"" + escape(campaign.name()) + "\","
                + "\"dm\":\"" + escape(campaign.dm()) + "\""
                + "}";
    }

    private static String campaignCharacterJson(CampaignCharacter character) {
        return "{"
                + "\"id\":\"" + escape(character.id()) + "\","
                + "\"name\":\"" + escape(character.name()) + "\","
                + "\"level\":" + character.level() + ","
                + "\"class\":\"" + escape(character.characterClass()) + "\""
                + "}";
    }

    private static String campaignEventJson(CampaignEvent event) {
        return "{"
                + "\"id\":\"" + escape(event.id()) + "\","
                + "\"kind\":\"" + escape(event.kind()) + "\""
                + "}";
    }

    private static String campaignStateJson(CampaignState state) {
        StringBuilder json = new StringBuilder("{");
        json.append("\"id\":\"").append(escape(state.campaign().id())).append("\",")
                .append("\"name\":\"").append(escape(state.campaign().name())).append("\",")
                .append("\"dm\":\"").append(escape(state.campaign().dm())).append("\",")
                .append("\"characters\":[");
        for (int i = 0; i < state.characters().size(); i++) {
            if (i > 0) {
                json.append(',');
            }
            json.append(campaignCharacterJson(state.characters().get(i)));
        }
        json.append("],\"log_count\":").append(state.logCount()).append('}');
        return json.toString();
    }

    private static String stringArrayJson(List<String> values) {
        StringBuilder json = new StringBuilder("[");
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) {
                json.append(',');
            }
            json.append('"').append(escape(values.get(i))).append('"');
        }
        json.append(']');
        return json.toString();
    }

    private static String asString(Object value) {
        if (value instanceof String text) {
            return text;
        }
        throw new BadRequest();
    }

    private static int asInt(Object value) {
        if (value instanceof Integer number) {
            return number;
        }
        throw new BadRequest();
    }

    private static boolean asBoolean(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        throw new BadRequest();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asObject(Object value) {
        if (value instanceof Map<?, ?>) {
            return (Map<String, Object>) value;
        }
        throw new BadRequest();
    }

    @SuppressWarnings("unchecked")
    private static List<Object> asList(Object value) {
        if (value instanceof List<?>) {
            return (List<Object>) value;
        }
        throw new BadRequest();
    }

    private static String escape(String text) {
        StringBuilder escaped = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            switch (c) {
                case '"' -> escaped.append("\\\"");
                case '\\' -> escaped.append("\\\\");
                case '\b' -> escaped.append("\\b");
                case '\f' -> escaped.append("\\f");
                case '\n' -> escaped.append("\\n");
                case '\r' -> escaped.append("\\r");
                case '\t' -> escaped.append("\\t");
                default -> {
                    if (c < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) c));
                    } else {
                        escaped.append(c);
                    }
                }
            }
        }
        return escaped.toString();
    }

    private record Combatant(String name, int dex, int score) {
    }

    private record Condition(String name, int remainingRounds) {
    }

    private record User(String username, String role, PasswordHash passwordHash) {
    }

    private record PasswordHash(byte[] salt, byte[] hash) {
    }

    private record Monster(String slug, String name, String cr, int armorClass, int hitPoints, List<String> tags) {
    }

    private record Item(String slug, String name, String type, String rarity, int costGp) {
    }

    private record Campaign(String id, String name, String dm) {
    }

    private record CampaignCharacter(String id, String name, int level, String characterClass) {
    }

    private record CampaignEvent(String id, String kind, String summary) {
    }

    private record CampaignState(Campaign campaign, List<CampaignCharacter> characters, int logCount) {
    }

    private record EncounterMath(int baseXp, int monsterCount, double multiplier, double adjustedXp,
                                 String difficulty, int easy, int medium, int hard, int deadly) {
    }

    private static final class Storage {
        static final int SCHEMA_VERSION = 1;
        private final Path database = Path.of("game.db");
        private boolean initialized;

        synchronized void initialize() {
            runSql(schemaSql());
            initialized = Files.exists(database);
        }

        synchronized boolean initialized() {
            return initialized && Files.exists(database);
        }

        synchronized void reset() {
            try {
                Files.deleteIfExists(database);
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
            initialized = false;
            initialize();
        }

        synchronized void createMonster(Monster monster) {
            if (!queryLines("SELECT slug FROM monsters WHERE slug = " + sql(monster.slug()) + " LIMIT 1;").isEmpty()) {
                throw new Conflict();
            }
            StringBuilder sql = new StringBuilder();
            sql.append("BEGIN;\n");
            sql.append("INSERT INTO monsters(slug, name, cr, armor_class, hit_points) VALUES (")
                    .append(sql(monster.slug())).append(", ")
                    .append(sql(monster.name())).append(", ")
                    .append(sql(monster.cr())).append(", ")
                    .append(monster.armorClass()).append(", ")
                    .append(monster.hitPoints()).append(");\n");
            for (int i = 0; i < monster.tags().size(); i++) {
                sql.append("INSERT INTO monster_tags(monster_slug, position, tag) VALUES (")
                        .append(sql(monster.slug())).append(", ")
                        .append(i).append(", ")
                        .append(sql(monster.tags().get(i))).append(");\n");
            }
            sql.append("COMMIT;");
            runSql(sql.toString());
        }

        synchronized Monster findMonster(String slug) {
            List<String> rows = queryLines("SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = " + sql(slug) + " LIMIT 1;");
            if (rows.isEmpty()) {
                return null;
            }
            String[] fields = rows.getFirst().split("\u001f", -1);
            if (fields.length != 5) {
                throw new IllegalStateException("unexpected monster row");
            }
            List<String> tags = new ArrayList<>();
            for (String tag : queryLines("SELECT tag FROM monster_tags WHERE monster_slug = " + sql(slug) + " ORDER BY position;")) {
                tags.add(tag);
            }
            return new Monster(fields[0], fields[1], fields[2], parseStoredInt(fields[3]), parseStoredInt(fields[4]), tags);
        }

        synchronized void createItem(Item item) {
            if (!queryLines("SELECT slug FROM items WHERE slug = " + sql(item.slug()) + " LIMIT 1;").isEmpty()) {
                throw new Conflict();
            }
            runSql("INSERT INTO items(slug, name, type, rarity, cost_gp) VALUES ("
                    + sql(item.slug()) + ", "
                    + sql(item.name()) + ", "
                    + sql(item.type()) + ", "
                    + sql(item.rarity()) + ", "
                    + item.costGp() + ");");
        }

        synchronized Item findItem(String slug) {
            List<String> rows = queryLines("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = " + sql(slug) + " LIMIT 1;");
            if (rows.isEmpty()) {
                return null;
            }
            String[] fields = rows.getFirst().split("\u001f", -1);
            if (fields.length != 5) {
                throw new IllegalStateException("unexpected item row");
            }
            return new Item(fields[0], fields[1], fields[2], fields[3], parseStoredInt(fields[4]));
        }

        synchronized void createCampaign(Campaign campaign) {
            if (campaignExists(campaign.id())) {
                throw new Conflict();
            }
            runSql("INSERT INTO campaigns(id, name, dm) VALUES ("
                    + sql(campaign.id()) + ", "
                    + sql(campaign.name()) + ", "
                    + sql(campaign.dm()) + ");");
        }

        synchronized void createCampaignCharacter(String campaignId, CampaignCharacter character) {
            requireCampaign(campaignId);
            if (!queryLines("SELECT id FROM campaign_characters WHERE campaign_id = " + sql(campaignId)
                    + " AND id = " + sql(character.id()) + " LIMIT 1;").isEmpty()) {
                throw new Conflict();
            }
            runSql("INSERT INTO campaign_characters(campaign_id, id, name, level, class) VALUES ("
                    + sql(campaignId) + ", "
                    + sql(character.id()) + ", "
                    + sql(character.name()) + ", "
                    + character.level() + ", "
                    + sql(character.characterClass()) + ");");
        }

        synchronized void createCampaignEvent(String campaignId, CampaignEvent event) {
            requireCampaign(campaignId);
            if (!queryLines("SELECT id FROM campaign_events WHERE campaign_id = " + sql(campaignId)
                    + " AND id = " + sql(event.id()) + " LIMIT 1;").isEmpty()) {
                throw new Conflict();
            }
            runSql("INSERT INTO campaign_events(campaign_id, id, kind, summary) VALUES ("
                    + sql(campaignId) + ", "
                    + sql(event.id()) + ", "
                    + sql(event.kind()) + ", "
                    + sql(event.summary()) + ");");
        }

        synchronized CampaignState findCampaignState(String campaignId) {
            Campaign campaign = findCampaign(campaignId);
            if (campaign == null) {
                return null;
            }
            List<CampaignCharacter> characters = new ArrayList<>();
            List<String> characterRows = queryLines("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = "
                    + sql(campaignId) + " ORDER BY rowid;");
            for (String row : characterRows) {
                String[] fields = row.split("\u001f", -1);
                if (fields.length != 4) {
                    throw new IllegalStateException("unexpected campaign character row");
                }
                characters.add(new CampaignCharacter(fields[0], fields[1], parseStoredInt(fields[2]), fields[3]));
            }
            List<String> counts = queryLines("SELECT COUNT(*) FROM campaign_events WHERE campaign_id = " + sql(campaignId) + ";");
            int logCount = counts.isEmpty() ? 0 : parseStoredInt(counts.getFirst());
            return new CampaignState(campaign, characters, logCount);
        }

        private Campaign findCampaign(String campaignId) {
            List<String> rows = queryLines("SELECT id, name, dm FROM campaigns WHERE id = " + sql(campaignId) + " LIMIT 1;");
            if (rows.isEmpty()) {
                return null;
            }
            String[] fields = rows.getFirst().split("\u001f", -1);
            if (fields.length != 3) {
                throw new IllegalStateException("unexpected campaign row");
            }
            return new Campaign(fields[0], fields[1], fields[2]);
        }

        private boolean campaignExists(String campaignId) {
            return !queryLines("SELECT id FROM campaigns WHERE id = " + sql(campaignId) + " LIMIT 1;").isEmpty();
        }

        synchronized String latestCampaignEventSummary(String campaignId) {
            requireCampaign(campaignId);
            List<String> rows = queryLines("SELECT summary FROM campaign_events WHERE campaign_id = "
                    + sql(campaignId) + " ORDER BY rowid DESC LIMIT 1;");
            return rows.isEmpty() ? null : rows.getFirst();
        }

        private void requireCampaign(String campaignId) {
            if (!campaignExists(campaignId)) {
                throw new NotFound();
            }
        }

        synchronized void saveUser(User user) {
            runSql("INSERT OR REPLACE INTO users(username, role, salt_hex, password_hash_hex) VALUES ("
                    + sql(user.username()) + ", "
                    + sql(user.role()) + ", "
                    + sql(hex(user.passwordHash().salt())) + ", "
                    + sql(hex(user.passwordHash().hash())) + ");");
        }

        synchronized void saveCombatSession(CombatSession session) {
            StringBuilder sql = new StringBuilder();
            sql.append("BEGIN;\n");
            sql.append("INSERT OR REPLACE INTO combat_sessions(id, round, turn_index) VALUES (")
                    .append(sql(session.id)).append(", ")
                    .append(session.round).append(", ")
                    .append(session.turnIndex).append(");\n");
            sql.append("DELETE FROM combatants WHERE session_id = ").append(sql(session.id)).append(";\n");
            for (int i = 0; i < session.order.size(); i++) {
                Combatant combatant = session.order.get(i);
                sql.append("INSERT INTO combatants(session_id, position, name, dex, score) VALUES (")
                        .append(sql(session.id)).append(", ")
                        .append(i).append(", ")
                        .append(sql(combatant.name())).append(", ")
                        .append(combatant.dex()).append(", ")
                        .append(combatant.score()).append(");\n");
            }
            sql.append("COMMIT;");
            runSql(sql.toString());
        }

        synchronized void saveCombatState(CombatSession session) {
            StringBuilder sql = new StringBuilder();
            sql.append("BEGIN;\n");
            sql.append("UPDATE combat_sessions SET round = ")
                    .append(session.round)
                    .append(", turn_index = ")
                    .append(session.turnIndex)
                    .append(" WHERE id = ")
                    .append(sql(session.id))
                    .append(";\n");
            appendConditionSave(sql, session);
            sql.append("COMMIT;");
            runSql(sql.toString());
        }

        synchronized void saveConditions(CombatSession session) {
            StringBuilder sql = new StringBuilder();
            sql.append("BEGIN;\n");
            appendConditionSave(sql, session);
            sql.append("COMMIT;");
            runSql(sql.toString());
        }

        private void appendConditionSave(StringBuilder sql, CombatSession session) {
            sql.append("DELETE FROM conditions WHERE session_id = ").append(sql(session.id)).append(";\n");
            for (Map.Entry<String, List<Condition>> entry : session.conditions.entrySet()) {
                List<Condition> conditions = entry.getValue();
                for (int i = 0; i < conditions.size(); i++) {
                    Condition condition = conditions.get(i);
                    sql.append("INSERT INTO conditions(session_id, target, position, condition_name, remaining_rounds) VALUES (")
                            .append(sql(session.id)).append(", ")
                            .append(sql(entry.getKey())).append(", ")
                            .append(i).append(", ")
                            .append(sql(condition.name())).append(", ")
                            .append(condition.remainingRounds()).append(");\n");
                }
            }
        }

        private String schemaSql() {
            return """
                    PRAGMA foreign_keys = ON;
                    PRAGMA user_version = %d;
                    CREATE TABLE IF NOT EXISTS schema_meta (
                      key TEXT PRIMARY KEY NOT NULL,
                      value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS users (
                      username TEXT PRIMARY KEY NOT NULL,
                      role TEXT NOT NULL,
                      salt_hex TEXT NOT NULL,
                      password_hash_hex TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS combat_sessions (
                      id TEXT PRIMARY KEY NOT NULL,
                      round INTEGER NOT NULL,
                      turn_index INTEGER NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS combatants (
                      session_id TEXT NOT NULL,
                      position INTEGER NOT NULL,
                      name TEXT NOT NULL,
                      dex INTEGER NOT NULL,
                      score INTEGER NOT NULL,
                      PRIMARY KEY (session_id, position),
                      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS conditions (
                      session_id TEXT NOT NULL,
                      target TEXT NOT NULL,
                      position INTEGER NOT NULL,
                      condition_name TEXT NOT NULL,
                      remaining_rounds INTEGER NOT NULL,
                      PRIMARY KEY (session_id, target, position),
                      FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS monsters (
                      slug TEXT PRIMARY KEY NOT NULL,
                      name TEXT NOT NULL,
                      cr TEXT NOT NULL,
                      armor_class INTEGER NOT NULL,
                      hit_points INTEGER NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS monster_tags (
                      monster_slug TEXT NOT NULL,
                      position INTEGER NOT NULL,
                      tag TEXT NOT NULL,
                      PRIMARY KEY (monster_slug, position),
                      FOREIGN KEY (monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS items (
                      slug TEXT PRIMARY KEY NOT NULL,
                      name TEXT NOT NULL,
                      type TEXT NOT NULL,
                      rarity TEXT NOT NULL,
                      cost_gp INTEGER NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS campaigns (
                      id TEXT PRIMARY KEY NOT NULL,
                      name TEXT NOT NULL,
                      dm TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS campaign_characters (
                      campaign_id TEXT NOT NULL,
                      id TEXT NOT NULL,
                      name TEXT NOT NULL,
                      level INTEGER NOT NULL,
                      class TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (campaign_id, id),
                      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS campaign_events (
                      campaign_id TEXT NOT NULL,
                      id TEXT NOT NULL,
                      kind TEXT NOT NULL,
                      summary TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (campaign_id, id),
                      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                    );
                    INSERT OR REPLACE INTO schema_meta(key, value) VALUES
                      ('driver', 'sqlite'),
                      ('schema_version', '%d');
                    """.formatted(SCHEMA_VERSION, SCHEMA_VERSION);
        }

        private void runSql(String sql) {
            ProcessBuilder builder = new ProcessBuilder("sqlite3", database.toString());
            builder.redirectErrorStream(true);
            try {
                Process process = builder.start();
                try (OutputStream input = process.getOutputStream()) {
                    input.write(sql.getBytes(StandardCharsets.UTF_8));
                }
                String output;
                try (InputStream stream = process.getInputStream()) {
                    output = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
                }
                int status = process.waitFor();
                if (status != 0) {
                    throw new IllegalStateException(output);
                }
            } catch (IOException e) {
                throw new IllegalStateException(e);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            }
        }

        private List<String> queryLines(String sql) {
            ProcessBuilder builder = new ProcessBuilder("sqlite3", "-batch", "-noheader", "-separator", "\u001f", database.toString(), sql);
            builder.redirectErrorStream(true);
            try {
                Process process = builder.start();
                String output;
                try (InputStream stream = process.getInputStream()) {
                    output = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
                }
                int status = process.waitFor();
                if (status != 0) {
                    throw new IllegalStateException(output);
                }
                List<String> lines = new ArrayList<>();
                for (String line : output.split("\\R")) {
                    if (!line.isEmpty()) {
                        lines.add(line);
                    }
                }
                return lines;
            } catch (IOException e) {
                throw new IllegalStateException(e);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            }
        }

        private static int parseStoredInt(String text) {
            try {
                return Integer.parseInt(text);
            } catch (NumberFormatException e) {
                throw new IllegalStateException(e);
            }
        }

        private static String sql(String value) {
            return "'" + value.replace("'", "''") + "'";
        }

        private static String hex(byte[] bytes) {
            char[] digits = "0123456789abcdef".toCharArray();
            char[] output = new char[bytes.length * 2];
            for (int i = 0; i < bytes.length; i++) {
                int value = bytes[i] & 0xff;
                output[i * 2] = digits[value >>> 4];
                output[i * 2 + 1] = digits[value & 0x0f];
            }
            return new String(output);
        }
    }

    private static final class Passwords {
        private static final int SALT_BYTES = 16;
        private static final int ITERATIONS = 120_000;
        private static final int KEY_BITS = 256;
        private final SecureRandom random = new SecureRandom();

        PasswordHash hash(String password) {
            byte[] salt = new byte[SALT_BYTES];
            random.nextBytes(salt);
            return new PasswordHash(salt, derive(password, salt));
        }

        boolean verify(String password, PasswordHash stored) {
            byte[] candidate = derive(password, stored.salt());
            return MessageDigest.isEqual(candidate, stored.hash());
        }

        private byte[] derive(String password, byte[] salt) {
            char[] chars = password.toCharArray();
            try {
                KeySpec spec = new PBEKeySpec(chars, salt, ITERATIONS, KEY_BITS);
                SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
                return factory.generateSecret(spec).getEncoded();
            } catch (InvalidKeySpecException | java.security.NoSuchAlgorithmException e) {
                throw new IllegalStateException(e);
            } finally {
                Arrays.fill(chars, '\0');
            }
        }
    }

    private static final class CombatSession {
        private final String id;
        private final List<Combatant> order;
        private final Map<String, List<Condition>> conditions = new LinkedHashMap<>();
        private int round = 1;
        private int turnIndex = 0;

        CombatSession(String id, List<Combatant> order) {
            this.id = id;
            this.order = order;
        }

        Combatant active() {
            return order.get(turnIndex);
        }

        boolean hasCombatant(String name) {
            for (Combatant combatant : order) {
                if (combatant.name().equals(name)) {
                    return true;
                }
            }
            return false;
        }
    }

    private static final class BadRequest extends RuntimeException {
    }

    private static final class Unauthorized extends RuntimeException {
    }

    private static final class Conflict extends RuntimeException {
    }

    private static final class NotFound extends RuntimeException {
    }

    private static final class JsonParser {
        private final String text;
        private int index;

        JsonParser(String text) {
            this.text = text;
        }

        Object parse() {
            Object value = parseValue();
            skipWhitespace();
            if (index != text.length()) {
                throw new BadRequest();
            }
            return value;
        }

        private Object parseValue() {
            skipWhitespace();
            if (index >= text.length()) {
                throw new BadRequest();
            }
            char c = text.charAt(index);
            return switch (c) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> parseString();
                case 't' -> parseLiteral("true", Boolean.TRUE);
                case 'f' -> parseLiteral("false", Boolean.FALSE);
                case 'n' -> parseLiteral("null", null);
                default -> {
                    if (c == '-' || Character.isDigit(c)) {
                        yield parseInteger();
                    }
                    throw new BadRequest();
                }
            };
        }

        private Map<String, Object> parseObject() {
            expect('{');
            Map<String, Object> object = new LinkedHashMap<>();
            skipWhitespace();
            if (peek('}')) {
                index++;
                return object;
            }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                Object value = parseValue();
                object.put(key, value);
                skipWhitespace();
                if (peek('}')) {
                    index++;
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
                index++;
                return array;
            }
            while (true) {
                array.add(parseValue());
                skipWhitespace();
                if (peek(']')) {
                    index++;
                    return array;
                }
                expect(',');
            }
        }

        private String parseString() {
            expect('"');
            StringBuilder value = new StringBuilder();
            while (index < text.length()) {
                char c = text.charAt(index++);
                if (c == '"') {
                    return value.toString();
                }
                if (c == '\\') {
                    if (index >= text.length()) {
                        throw new BadRequest();
                    }
                    char escaped = text.charAt(index++);
                    switch (escaped) {
                        case '"' -> value.append('"');
                        case '\\' -> value.append('\\');
                        case '/' -> value.append('/');
                        case 'b' -> value.append('\b');
                        case 'f' -> value.append('\f');
                        case 'n' -> value.append('\n');
                        case 'r' -> value.append('\r');
                        case 't' -> value.append('\t');
                        case 'u' -> value.append(parseUnicode());
                        default -> throw new BadRequest();
                    }
                } else {
                    if (c < 0x20) {
                        throw new BadRequest();
                    }
                    value.append(c);
                }
            }
            throw new BadRequest();
        }

        private char parseUnicode() {
            if (index + 4 > text.length()) {
                throw new BadRequest();
            }
            String hex = text.substring(index, index + 4);
            index += 4;
            try {
                return (char) Integer.parseInt(hex, 16);
            } catch (NumberFormatException e) {
                throw new BadRequest();
            }
        }

        private Object parseLiteral(String literal, Object value) {
            if (!text.startsWith(literal, index)) {
                throw new BadRequest();
            }
            index += literal.length();
            return value;
        }

        private int parseInteger() {
            int start = index;
            if (peek('-')) {
                index++;
            }
            if (index >= text.length() || !Character.isDigit(text.charAt(index))) {
                throw new BadRequest();
            }
            if (text.charAt(index) == '0') {
                index++;
            } else {
                while (index < text.length() && Character.isDigit(text.charAt(index))) {
                    index++;
                }
            }
            if (index < text.length() && (text.charAt(index) == '.' || text.charAt(index) == 'e' || text.charAt(index) == 'E')) {
                throw new BadRequest();
            }
            try {
                return Integer.parseInt(text.substring(start, index));
            } catch (NumberFormatException e) {
                throw new BadRequest();
            }
        }

        private void expect(char expected) {
            if (!peek(expected)) {
                throw new BadRequest();
            }
            index++;
        }

        private boolean peek(char expected) {
            return index < text.length() && text.charAt(index) == expected;
        }

        private void skipWhitespace() {
            while (index < text.length()) {
                char c = text.charAt(index);
                if (c == ' ' || c == '\n' || c == '\r' || c == '\t') {
                    index++;
                } else {
                    return;
                }
            }
        }
    }
}
