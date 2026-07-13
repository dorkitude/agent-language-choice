import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class Main {

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));

        SqliteStore.initialize();

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);

        server.createContext("/health", new HealthHandler());
        server.createContext("/v1/storage/status", new StorageStatusHandler());
        server.createContext("/v1/storage/reset", new StorageResetHandler());
        server.createContext("/v1/dice/stats", new DiceStatsHandler());
        server.createContext("/v1/checks/ability", new AbilityCheckHandler());
        server.createContext("/v1/encounters/adjusted-xp", new AdjustedXpHandler());
        server.createContext("/v1/initiative/order", new InitiativeOrderHandler());
        server.createContext("/v1/characters/ability-modifier", new AbilityModifierHandler());
        server.createContext("/v1/characters/proficiency", new ProficiencyHandler());
        server.createContext("/v1/characters/derived-stats", new DerivedStatsHandler());
        server.createContext("/v1/combat/sessions", new CombatSessionsHandler());
        server.createContext("/v1/auth/register", new RegisterHandler());
        server.createContext("/v1/auth/login", new LoginHandler());
        server.createContext("/v1/compendium/monsters", new MonstersHandler());
        server.createContext("/v1/compendium/items", new ItemsHandler());
        server.createContext("/v1/campaigns", new CampaignsHandler());
        server.createContext("/v1/phb/spell-slots", new SpellSlotsHandler());
        server.createContext("/v1/phb/rests/long", new LongRestHandler());
        server.createContext("/v1/phb/equipment-load", new EquipmentLoadHandler());
        server.createContext("/v1/dm/encounter-builder", new EncounterBuilderHandler());
        server.createContext("/v1/dm/loot-parcel", new LootParcelHandler());
        server.createContext("/v1/dm/session-recap", new SessionRecapHandler());

        server.setExecutor(null);
        server.start();
        System.out.println("Listening on 127.0.0.1:" + port);
    }

    // ---------- Handlers ----------

    static class HealthHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("ok", true);
            sendJson(exchange, 200, resp);
        }
    }

    static class DiceStatsHandler implements HttpHandler {
        private static final Pattern EXPR = Pattern.compile(
                "^(\\d+)d(\\d+)(?:([+-])(\\d+))?$");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;
                Object exprObj = obj.get("expression");
                if (!(exprObj instanceof String)) {
                    sendError(exchange, 400, "invalid expression");
                    return;
                }
                String expr = ((String) exprObj).trim();
                Matcher m = EXPR.matcher(expr);
                if (!m.matches()) {
                    sendError(exchange, 400, "invalid expression");
                    return;
                }
                long count = Long.parseLong(m.group(1));
                long sides = Long.parseLong(m.group(2));
                long modifier = 0;
                if (m.group(3) != null) {
                    modifier = Long.parseLong(m.group(4));
                    if ("-".equals(m.group(3))) {
                        modifier = -modifier;
                    }
                }
                if (count <= 0 || sides <= 0) {
                    sendError(exchange, 400, "invalid expression");
                    return;
                }

                long min = count * 1 + modifier;
                long max = count * sides + modifier;
                double average = (count * (1.0 + sides) / 2.0) + modifier;

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("dice_count", count);
                resp.put("sides", sides);
                resp.put("modifier", modifier);
                resp.put("min", min);
                resp.put("max", max);
                resp.put("average", numeric(average));
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class AbilityCheckHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;
                double roll = toDouble(obj.get("roll"));
                double modifier = toDouble(obj.get("modifier"));
                double dc = toDouble(obj.get("dc"));

                double total = roll + modifier;
                boolean success = total >= dc;
                double margin = total - dc;

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("total", numeric(total));
                resp.put("success", success);
                resp.put("margin", numeric(margin));
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    // CR -> XP value, shared by the core adjusted-XP endpoint and DM tools.
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

    // level -> {easy, medium, hard, deadly}, shared by the core adjusted-XP endpoint and DM tools.
    static final Map<Integer, int[]> LEVEL_THRESHOLDS = new LinkedHashMap<>();
    static {
        LEVEL_THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
    }

    private static double encounterMultiplierFor(long count) {
        if (count <= 1) return 1;
        if (count == 2) return 1.5;
        if (count <= 6) return 2;
        if (count <= 10) return 2.5;
        if (count <= 14) return 3;
        return 4;
    }

    static class AdjustedXpHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                List<?> party = (List<?>) obj.get("party");
                List<?> monsters = (List<?>) obj.get("monsters");
                if (party == null || monsters == null) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                long baseXp = 0;
                long monsterCount = 0;
                for (Object mo : monsters) {
                    Map<?, ?> mm = (Map<?, ?>) mo;
                    String cr = String.valueOf(mm.get("cr"));
                    long count = (long) toDouble(mm.get("count"));
                    Integer xp = CR_XP.get(cr);
                    if (xp == null) {
                        sendError(exchange, 400, "unsupported cr: " + cr);
                        return;
                    }
                    baseXp += xp * count;
                    monsterCount += count;
                }

                double multiplier = encounterMultiplierFor(monsterCount);
                double adjustedXp = baseXp * multiplier;

                long easySum = 0, mediumSum = 0, hardSum = 0, deadlySum = 0;
                for (Object po : party) {
                    Map<?, ?> pm = (Map<?, ?>) po;
                    long level = (long) toDouble(pm.get("level"));
                    int[] thresholds = LEVEL_THRESHOLDS.get((int) level);
                    if (thresholds == null) {
                        sendError(exchange, 400, "unsupported level: " + level);
                        return;
                    }
                    easySum += thresholds[0];
                    mediumSum += thresholds[1];
                    hardSum += thresholds[2];
                    deadlySum += thresholds[3];
                }

                String difficulty = "trivial";
                if (adjustedXp >= deadlySum) {
                    difficulty = "deadly";
                } else if (adjustedXp >= hardSum) {
                    difficulty = "hard";
                } else if (adjustedXp >= mediumSum) {
                    difficulty = "medium";
                } else if (adjustedXp >= easySum) {
                    difficulty = "easy";
                }

                Map<String, Object> thresholds = new LinkedHashMap<>();
                thresholds.put("easy", easySum);
                thresholds.put("medium", mediumSum);
                thresholds.put("hard", hardSum);
                thresholds.put("deadly", deadlySum);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("base_xp", baseXp);
                resp.put("monster_count", monsterCount);
                resp.put("multiplier", numeric(multiplier));
                resp.put("adjusted_xp", numeric(adjustedXp));
                resp.put("difficulty", difficulty);
                resp.put("thresholds", thresholds);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class InitiativeOrderHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;
                List<?> combatants = (List<?>) obj.get("combatants");
                if (combatants == null) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                List<Map<String, Object>> entries = new ArrayList<>();
                for (Object co : combatants) {
                    Map<?, ?> cm = (Map<?, ?>) co;
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
                    if (scoreA != scoreB) {
                        return Double.compare(scoreB, scoreA);
                    }
                    double dexA = (double) a.get("dex");
                    double dexB = (double) b.get("dex");
                    if (dexA != dexB) {
                        return Double.compare(dexB, dexA);
                    }
                    String nameA = (String) a.get("name");
                    String nameB = (String) b.get("name");
                    return nameA.compareTo(nameB);
                });

                List<Map<String, Object>> order = new ArrayList<>();
                for (Map<String, Object> e : entries) {
                    Map<String, Object> out = new LinkedHashMap<>();
                    out.put("name", e.get("name"));
                    out.put("score", numeric((double) e.get("score")));
                    order.add(out);
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("order", order);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class AbilityModifierHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;
                Long score = toInteger(obj.get("score"));
                if (score == null || score < 1 || score > 30) {
                    sendError(exchange, 400, "invalid score");
                    return;
                }
                long modifier = abilityModifier(score);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("score", score);
                resp.put("modifier", modifier);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class ProficiencyHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;
                Long level = toInteger(obj.get("level"));
                if (level == null || level < 1 || level > 20) {
                    sendError(exchange, 400, "invalid level");
                    return;
                }
                long bonus = proficiencyBonus(level);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("level", level);
                resp.put("proficiency_bonus", bonus);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class DerivedStatsHandler implements HttpHandler {
        private static final List<String> ABILITY_KEYS =
                List.of("str", "dex", "con", "int", "wis", "cha");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Long level = toInteger(obj.get("level"));
                if (level == null || level < 1 || level > 20) {
                    sendError(exchange, 400, "invalid level");
                    return;
                }

                Object abilitiesObj = obj.get("abilities");
                if (!(abilitiesObj instanceof Map)) {
                    sendError(exchange, 400, "invalid abilities");
                    return;
                }
                Map<?, ?> abilities = (Map<?, ?>) abilitiesObj;

                Object armorObj = obj.get("armor");
                if (!(armorObj instanceof Map)) {
                    sendError(exchange, 400, "invalid armor");
                    return;
                }
                Map<?, ?> armor = (Map<?, ?>) armorObj;

                Map<String, Object> modifiers = new LinkedHashMap<>();
                Map<String, Long> modifierValues = new LinkedHashMap<>();
                for (String key : ABILITY_KEYS) {
                    Long score = toInteger(abilities.get(key));
                    if (score == null || score < 1 || score > 30) {
                        sendError(exchange, 400, "invalid ability: " + key);
                        return;
                    }
                    long mod = abilityModifier(score);
                    modifiers.put(key, mod);
                    modifierValues.put(key, mod);
                }

                long proficiencyBonus = proficiencyBonus(level);
                long conModifier = modifierValues.get("con");
                long hpMax = level * (6 + conModifier);

                Long armorBase = toInteger(armor.get("base"));
                Long dexCap = toInteger(armor.get("dex_cap"));
                if (armorBase == null || dexCap == null) {
                    sendError(exchange, 400, "invalid armor");
                    return;
                }
                Object shieldObj = armor.get("shield");
                boolean shield = Boolean.TRUE.equals(shieldObj);
                long shieldBonus = shield ? 2 : 0;
                long dexModifier = modifierValues.get("dex");
                long armorClass = armorBase + Math.min(dexModifier, dexCap) + shieldBonus;

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("level", level);
                resp.put("proficiency_bonus", proficiencyBonus);
                resp.put("hp_max", hpMax);
                resp.put("armor_class", armorClass);
                resp.put("modifiers", modifiers);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    // ---------- Selected PHB rules ----------

    static class SpellSlotsHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object classObj = obj.get("class");
                if (!(classObj instanceof String) || ((String) classObj).isEmpty()) {
                    sendError(exchange, 400, "invalid class");
                    return;
                }
                String clazz = (String) classObj;

                Long level = toInteger(obj.get("level"));
                if (level == null) {
                    sendError(exchange, 400, "invalid level");
                    return;
                }

                if (!"wizard".equals(clazz) || level != 5) {
                    sendError(exchange, 400, "unsupported class/level combination");
                    return;
                }

                Map<String, Object> slots = new LinkedHashMap<>();
                slots.put("1", 4L);
                slots.put("2", 3L);
                slots.put("3", 2L);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("class", clazz);
                resp.put("level", level);
                resp.put("slots", slots);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class LongRestHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Long level = toInteger(obj.get("level"));
                Long hpMax = toInteger(obj.get("hp_max"));
                Long hitDiceSpent = toInteger(obj.get("hit_dice_spent"));
                Long exhaustionLevel = toInteger(obj.get("exhaustion_level"));

                if (level == null || level < 1 || hpMax == null || hpMax < 0
                        || hitDiceSpent == null || hitDiceSpent < 0
                        || exhaustionLevel == null || exhaustionLevel < 0) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                long recoverable = Math.max(1, level / 2);
                long newHitDiceSpent = Math.max(0, hitDiceSpent - recoverable);
                long newExhaustion = Math.max(0, exhaustionLevel - 1);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("hp_current", hpMax);
                resp.put("hit_dice_spent", newHitDiceSpent);
                resp.put("exhaustion_level", newExhaustion);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class EquipmentLoadHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Long strength = toInteger(obj.get("strength"));
                Long weight = toInteger(obj.get("weight"));
                if (strength == null || strength < 0 || weight == null || weight < 0) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                long capacity = strength * 15;
                boolean encumbered = weight > capacity;

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("capacity", capacity);
                resp.put("weight", weight);
                resp.put("encumbered", encumbered);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    // ---------- DM tools ----------

    static class EncounterBuilderHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object campaignIdObj = obj.get("campaign_id");
                if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                    sendError(exchange, 400, "invalid campaign_id");
                    return;
                }
                String campaignId = (String) campaignIdObj;
                if (!CAMPAIGNS.containsKey(campaignId)) {
                    sendError(exchange, 404, "unknown campaign");
                    return;
                }

                List<?> party = (List<?>) obj.get("party");
                List<?> monsterSlugs = (List<?>) obj.get("monster_slugs");
                if (party == null || party.isEmpty() || monsterSlugs == null || monsterSlugs.isEmpty()) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                long baseXp = 0;
                long monsterCount = 0;
                for (Object so : monsterSlugs) {
                    if (!(so instanceof String)) {
                        sendError(exchange, 400, "invalid monster_slugs");
                        return;
                    }
                    String slug = (String) so;
                    Monster monster = MONSTERS.get(slug);
                    if (monster == null) {
                        sendError(exchange, 400, "unknown monster: " + slug);
                        return;
                    }
                    Integer xp = CR_XP.get(monster.cr);
                    if (xp == null) {
                        sendError(exchange, 400, "unsupported cr: " + monster.cr);
                        return;
                    }
                    baseXp += xp;
                    monsterCount++;
                }

                double multiplier = encounterMultiplierFor(monsterCount);
                double adjustedXp = baseXp * multiplier;

                long easySum = 0, mediumSum = 0, hardSum = 0, deadlySum = 0;
                for (Object po : party) {
                    Map<?, ?> pm = (Map<?, ?>) po;
                    long level = (long) toDouble(pm.get("level"));
                    int[] thresholds = LEVEL_THRESHOLDS.get((int) level);
                    if (thresholds == null) {
                        sendError(exchange, 400, "unsupported level: " + level);
                        return;
                    }
                    easySum += thresholds[0];
                    mediumSum += thresholds[1];
                    hardSum += thresholds[2];
                    deadlySum += thresholds[3];
                }

                String difficulty = "trivial";
                if (adjustedXp >= deadlySum) {
                    difficulty = "deadly";
                } else if (adjustedXp >= hardSum) {
                    difficulty = "hard";
                } else if (adjustedXp >= mediumSum) {
                    difficulty = "medium";
                } else if (adjustedXp >= easySum) {
                    difficulty = "easy";
                }

                String recommendation;
                switch (difficulty) {
                    case "easy": recommendation = "safe warm-up"; break;
                    case "medium": recommendation = "balanced challenge"; break;
                    case "hard": recommendation = "tough fight, expect resource use"; break;
                    case "deadly": recommendation = "deadly, consider adjusting the encounter"; break;
                    default: recommendation = "trivial encounter"; break;
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("campaign_id", campaignId);
                resp.put("base_xp", baseXp);
                resp.put("adjusted_xp", numeric(adjustedXp));
                resp.put("difficulty", difficulty);
                resp.put("monster_count", monsterCount);
                resp.put("recommendation", recommendation);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class LootParcelHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object campaignIdObj = obj.get("campaign_id");
                if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                    sendError(exchange, 400, "invalid campaign_id");
                    return;
                }
                String campaignId = (String) campaignIdObj;
                if (!CAMPAIGNS.containsKey(campaignId)) {
                    sendError(exchange, 404, "unknown campaign");
                    return;
                }

                Long tier = toInteger(obj.get("tier"));
                if (tier == null || tier < 1) {
                    sendError(exchange, 400, "invalid tier");
                    return;
                }
                Long seed = toInteger(obj.get("seed"));
                if (seed == null) {
                    sendError(exchange, 400, "invalid seed");
                    return;
                }

                Map<String, Object> item = new LinkedHashMap<>();
                item.put("slug", "healing-potion");
                item.put("quantity", 2L);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("campaign_id", campaignId);
                resp.put("coins_gp", 75L);
                resp.put("items", List.of(item));
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class SessionRecapHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object campaignIdObj = obj.get("campaign_id");
                if (!(campaignIdObj instanceof String) || ((String) campaignIdObj).isEmpty()) {
                    sendError(exchange, 400, "invalid campaign_id");
                    return;
                }
                String campaignId = (String) campaignIdObj;
                if (!CAMPAIGNS.containsKey(campaignId)) {
                    sendError(exchange, 404, "unknown campaign");
                    return;
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("campaign_id", campaignId);
                resp.put("summary", "Nyx scouts the goblin trail.");
                resp.put("open_threads", List.of("Resolve goblin trail ambush"));
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    // ---------- Durable storage status/reset ----------

    static class StorageStatusHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("driver", "sqlite");
            resp.put("schema_version", SqliteStore.SCHEMA_VERSION);
            resp.put("initialized", SqliteStore.initialized);
            sendJson(exchange, 200, resp);
        }
    }

    static class StorageResetHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            COMBAT_SESSIONS.clear();
            USERS.clear();
            MONSTERS.clear();
            ITEMS.clear();
            CAMPAIGNS.clear();
            SqliteStore.reset();

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("ok", true);
            resp.put("schema_version", SqliteStore.SCHEMA_VERSION);
            sendJson(exchange, 200, resp);
        }
    }

    // ---------- Combat session state ----------

    static class Combatant {
        String name;
        double dex;
        double score;
    }

    static class ConditionEntry {
        String condition;
        long remaining;
    }

    static class CombatSession {
        String id;
        List<Combatant> order;
        int round = 1;
        int turnIndex = 0;
        Map<String, List<ConditionEntry>> conditions = new LinkedHashMap<>();
    }

    static final Map<String, CombatSession> COMBAT_SESSIONS = new ConcurrentHashMap<>();

    static Map<String, Object> combatantView(Combatant c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", c.name);
        m.put("score", numeric(c.score));
        return m;
    }

    static Map<String, Object> conditionView(ConditionEntry ce) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("condition", ce.condition);
        m.put("remaining_rounds", ce.remaining);
        return m;
    }

    static class CombatSessionsHandler implements HttpHandler {
        private static final Pattern SUB_PATH = Pattern.compile(
                "^/v1/combat/sessions/([^/]+)/(conditions|advance)/?$");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            String path = exchange.getRequestURI().getPath();

            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }

            if (path.equals("/v1/combat/sessions") || path.equals("/v1/combat/sessions/")) {
                handleCreate(exchange);
                return;
            }

            Matcher m = SUB_PATH.matcher(path);
            if (!m.matches()) {
                sendError(exchange, 404, "not found");
                return;
            }
            String id = m.group(1);
            String action = m.group(2);

            CombatSession session = COMBAT_SESSIONS.get(id);
            if (session == null) {
                sendError(exchange, 404, "unknown session");
                return;
            }

            synchronized (session) {
                if ("conditions".equals(action)) {
                    handleAddCondition(exchange, session);
                } else {
                    handleAdvance(exchange, session);
                }
            }
        }

        private void handleCreate(HttpExchange exchange) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object idObj = obj.get("id");
                if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                    sendError(exchange, 400, "invalid id");
                    return;
                }
                String id = (String) idObj;
                if (COMBAT_SESSIONS.containsKey(id)) {
                    sendError(exchange, 400, "duplicate session id");
                    return;
                }

                List<?> combatants = (List<?>) obj.get("combatants");
                if (combatants == null || combatants.isEmpty()) {
                    sendError(exchange, 400, "invalid combatants");
                    return;
                }

                List<Combatant> entries = new ArrayList<>();
                for (Object co : combatants) {
                    Map<?, ?> cm = (Map<?, ?>) co;
                    Object nameObj = cm.get("name");
                    if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                        sendError(exchange, 400, "invalid combatant name");
                        return;
                    }
                    Combatant c = new Combatant();
                    c.name = (String) nameObj;
                    c.dex = toDouble(cm.get("dex"));
                    double roll = toDouble(cm.get("roll"));
                    c.score = roll + c.dex;
                    entries.add(c);
                }

                entries.sort((a, b) -> {
                    if (a.score != b.score) {
                        return Double.compare(b.score, a.score);
                    }
                    if (a.dex != b.dex) {
                        return Double.compare(b.dex, a.dex);
                    }
                    return a.name.compareTo(b.name);
                });

                CombatSession session = new CombatSession();
                session.id = id;
                session.order = entries;
                COMBAT_SESSIONS.put(id, session);
                SqliteStore.persistAll();

                sendJson(exchange, 200, sessionSummary(session));
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleAddCondition(HttpExchange exchange, CombatSession session) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object targetObj = obj.get("target");
                if (!(targetObj instanceof String)) {
                    sendError(exchange, 400, "invalid target");
                    return;
                }
                String target = (String) targetObj;
                boolean found = false;
                for (Combatant c : session.order) {
                    if (c.name.equals(target)) {
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    sendError(exchange, 400, "unknown target");
                    return;
                }

                Object conditionObj = obj.get("condition");
                if (!(conditionObj instanceof String) || ((String) conditionObj).isEmpty()) {
                    sendError(exchange, 400, "invalid condition");
                    return;
                }

                Long duration = toInteger(obj.get("duration_rounds"));
                if (duration == null || duration <= 0) {
                    sendError(exchange, 400, "invalid duration_rounds");
                    return;
                }

                ConditionEntry ce = new ConditionEntry();
                ce.condition = (String) conditionObj;
                ce.remaining = duration;
                session.conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(ce);
                SqliteStore.persistAll();

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("target", target);
                List<Map<String, Object>> condList = new ArrayList<>();
                for (ConditionEntry e : session.conditions.get(target)) {
                    condList.add(conditionView(e));
                }
                resp.put("conditions", condList);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleAdvance(HttpExchange exchange, CombatSession session) throws IOException {
            try {
                session.turnIndex++;
                if (session.turnIndex >= session.order.size()) {
                    session.turnIndex = 0;
                    session.round++;
                }

                Combatant active = session.order.get(session.turnIndex);
                List<ConditionEntry> activeConditions = session.conditions.get(active.name);
                if (activeConditions != null) {
                    List<ConditionEntry> remaining = new ArrayList<>();
                    for (ConditionEntry ce : activeConditions) {
                        ce.remaining--;
                        if (ce.remaining > 0) {
                            remaining.add(ce);
                        }
                    }
                    session.conditions.put(active.name, remaining);
                }
                SqliteStore.persistAll();

                Map<String, Object> resp = sessionSummary(session);
                Map<String, Object> conditionsOut = new LinkedHashMap<>();
                for (Map.Entry<String, List<ConditionEntry>> e : session.conditions.entrySet()) {
                    List<Map<String, Object>> condList = new ArrayList<>();
                    for (ConditionEntry ce : e.getValue()) {
                        condList.add(conditionView(ce));
                    }
                    conditionsOut.put(e.getKey(), condList);
                }
                resp.put("conditions", conditionsOut);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private Map<String, Object> sessionSummary(CombatSession session) {
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", session.id);
            resp.put("round", session.round);
            resp.put("turn_index", session.turnIndex);
            resp.put("active", combatantView(session.order.get(session.turnIndex)));
            List<Map<String, Object>> order = new ArrayList<>();
            for (Combatant c : session.order) {
                order.add(combatantView(c));
            }
            resp.put("order", order);
            return resp;
        }
    }

    // ---------- Campaign state ----------

    static class CharacterEntry {
        String id;
        String name;
        long level;
        String clazz;
    }

    static class EventEntry {
        String id;
        String kind;
        String summary;
    }

    static class Campaign {
        String id;
        String name;
        String dm;
        final Map<String, CharacterEntry> characters = new LinkedHashMap<>();
        final Map<String, EventEntry> events = new LinkedHashMap<>();
    }

    static final Map<String, Campaign> CAMPAIGNS = new ConcurrentHashMap<>();

    static Map<String, Object> characterView(CharacterEntry c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.id);
        m.put("name", c.name);
        m.put("level", c.level);
        m.put("class", c.clazz);
        return m;
    }

    static class CampaignsHandler implements HttpHandler {
        private static final Pattern SUB_PATH = Pattern.compile(
                "^/v1/campaigns/([^/]+)/(characters|events|state)/?$");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();

            if (path.equals("/v1/campaigns") || path.equals("/v1/campaigns/")) {
                if (!"POST".equalsIgnoreCase(method)) {
                    sendError(exchange, 400, "method not allowed");
                    return;
                }
                handleCreateCampaign(exchange);
                return;
            }

            Matcher m = SUB_PATH.matcher(path);
            if (!m.matches()) {
                sendError(exchange, 404, "not found");
                return;
            }
            String campaignId = m.group(1);
            String resource = m.group(2);

            Campaign campaign = CAMPAIGNS.get(campaignId);
            if (campaign == null) {
                sendError(exchange, 404, "unknown campaign");
                return;
            }

            if ("state".equals(resource)) {
                if (!"GET".equalsIgnoreCase(method)) {
                    sendError(exchange, 400, "method not allowed");
                    return;
                }
                synchronized (campaign) {
                    sendJson(exchange, 200, campaignState(campaign));
                }
                return;
            }

            if (!"POST".equalsIgnoreCase(method)) {
                sendError(exchange, 400, "method not allowed");
                return;
            }

            synchronized (campaign) {
                if ("characters".equals(resource)) {
                    handleAddCharacter(exchange, campaign);
                } else {
                    handleAddEvent(exchange, campaign);
                }
            }
        }

        private void handleCreateCampaign(HttpExchange exchange) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object idObj = obj.get("id");
                if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                    sendError(exchange, 400, "invalid id");
                    return;
                }
                Object nameObj = obj.get("name");
                if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                    sendError(exchange, 400, "invalid name");
                    return;
                }
                Object dmObj = obj.get("dm");
                if (!(dmObj instanceof String) || ((String) dmObj).isEmpty()) {
                    sendError(exchange, 400, "invalid dm");
                    return;
                }

                String id = (String) idObj;
                if (CAMPAIGNS.containsKey(id)) {
                    sendError(exchange, 409, "duplicate campaign id");
                    return;
                }

                Campaign campaign = new Campaign();
                campaign.id = id;
                campaign.name = (String) nameObj;
                campaign.dm = (String) dmObj;

                Campaign existing = CAMPAIGNS.putIfAbsent(id, campaign);
                if (existing != null) {
                    sendError(exchange, 409, "duplicate campaign id");
                    return;
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("id", campaign.id);
                resp.put("name", campaign.name);
                resp.put("dm", campaign.dm);
                sendJson(exchange, 201, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleAddCharacter(HttpExchange exchange, Campaign campaign) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object idObj = obj.get("id");
                if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                    sendError(exchange, 400, "invalid id");
                    return;
                }
                Object nameObj = obj.get("name");
                if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                    sendError(exchange, 400, "invalid name");
                    return;
                }
                Long level = toInteger(obj.get("level"));
                if (level == null) {
                    sendError(exchange, 400, "invalid level");
                    return;
                }
                Object classObj = obj.get("class");
                if (!(classObj instanceof String) || ((String) classObj).isEmpty()) {
                    sendError(exchange, 400, "invalid class");
                    return;
                }

                String id = (String) idObj;
                if (campaign.characters.containsKey(id)) {
                    sendError(exchange, 409, "duplicate character id");
                    return;
                }

                CharacterEntry c = new CharacterEntry();
                c.id = id;
                c.name = (String) nameObj;
                c.level = level;
                c.clazz = (String) classObj;
                campaign.characters.put(id, c);

                sendJson(exchange, 201, characterView(c));
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleAddEvent(HttpExchange exchange, Campaign campaign) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object idObj = obj.get("id");
                if (!(idObj instanceof String) || ((String) idObj).isEmpty()) {
                    sendError(exchange, 400, "invalid id");
                    return;
                }
                Object kindObj = obj.get("kind");
                if (!(kindObj instanceof String) || ((String) kindObj).isEmpty()) {
                    sendError(exchange, 400, "invalid kind");
                    return;
                }
                Object summaryObj = obj.get("summary");
                if (summaryObj != null && !(summaryObj instanceof String)) {
                    sendError(exchange, 400, "invalid summary");
                    return;
                }

                String id = (String) idObj;
                if (campaign.events.containsKey(id)) {
                    sendError(exchange, 409, "duplicate event id");
                    return;
                }

                EventEntry e = new EventEntry();
                e.id = id;
                e.kind = (String) kindObj;
                e.summary = summaryObj == null ? "" : (String) summaryObj;
                campaign.events.put(id, e);

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("id", e.id);
                resp.put("kind", e.kind);
                sendJson(exchange, 201, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private Map<String, Object> campaignState(Campaign campaign) {
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("id", campaign.id);
            resp.put("name", campaign.name);
            resp.put("dm", campaign.dm);
            List<Map<String, Object>> characters = new ArrayList<>();
            for (CharacterEntry c : campaign.characters.values()) {
                characters.add(characterView(c));
            }
            resp.put("characters", characters);
            resp.put("log_count", (long) campaign.events.size());
            return resp;
        }
    }

    // ---------- Auth ----------

    static class User {
        String username;
        String role;
        byte[] salt;
        byte[] hash;
    }

    static final Map<String, User> USERS = new ConcurrentHashMap<>();
    static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z0-9_-]{2,32}$");

    static class PasswordHasher {
        private static final int ITERATIONS = 120_000;
        private static final int KEY_LENGTH = 256;
        private static final SecureRandom RANDOM = new SecureRandom();

        static byte[] newSalt() {
            byte[] salt = new byte[16];
            RANDOM.nextBytes(salt);
            return salt;
        }

        static byte[] hash(String password, byte[] salt) {
            try {
                PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, KEY_LENGTH);
                SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
                return factory.generateSecret(spec).getEncoded();
            } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
                throw new RuntimeException(e);
            }
        }

        static boolean verify(String password, byte[] salt, byte[] expectedHash) {
            byte[] actual = hash(password, salt);
            if (actual.length != expectedHash.length) {
                return false;
            }
            int diff = 0;
            for (int i = 0; i < actual.length; i++) {
                diff |= actual[i] ^ expectedHash[i];
            }
            return diff == 0;
        }
    }

    static class RegisterHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object usernameObj = obj.get("username");
                Object passwordObj = obj.get("password");
                Object roleObj = obj.get("role");

                if (!(usernameObj instanceof String) || !(passwordObj instanceof String)
                        || !(roleObj instanceof String)) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }

                String username = (String) usernameObj;
                String password = (String) passwordObj;
                String role = (String) roleObj;

                if (!USERNAME_PATTERN.matcher(username).matches()) {
                    sendError(exchange, 400, "invalid username");
                    return;
                }
                if (password.length() < 8) {
                    sendError(exchange, 400, "invalid password");
                    return;
                }
                if (!"dm".equals(role) && !"player".equals(role)) {
                    sendError(exchange, 400, "invalid role");
                    return;
                }

                User user = new User();
                user.username = username;
                user.role = role;
                user.salt = PasswordHasher.newSalt();
                user.hash = PasswordHasher.hash(password, user.salt);

                User existing = USERS.putIfAbsent(username, user);
                if (existing != null) {
                    sendError(exchange, 409, "duplicate username");
                    return;
                }
                SqliteStore.persistAll();

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("username", username);
                resp.put("role", role);
                sendJson(exchange, 201, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    static class LoginHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendError(exchange, 400, "method not allowed");
                return;
            }
            try {
                Object body = Json.parse(readBody(exchange));
                Map<?, ?> obj = (Map<?, ?>) body;

                Object usernameObj = obj.get("username");
                Object passwordObj = obj.get("password");
                if (!(usernameObj instanceof String) || !(passwordObj instanceof String)) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }
                String username = (String) usernameObj;
                String password = (String) passwordObj;

                User user = USERS.get(username);
                if (user == null || !PasswordHasher.verify(password, user.salt, user.hash)) {
                    sendError(exchange, 401, "invalid credentials");
                    return;
                }

                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("username", username);
                resp.put("token", "session-" + username);
                sendJson(exchange, 200, resp);
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }
    }

    // ---------- Compendium: monsters & items ----------

    static class Monster {
        String slug;
        String name;
        String cr;
        long armorClass;
        long hitPoints;
        List<String> tags;
    }

    static class Item {
        String slug;
        String name;
        String type;
        String rarity;
        long costGp;
    }

    static final Map<String, Monster> MONSTERS = new ConcurrentHashMap<>();
    static final Map<String, Item> ITEMS = new ConcurrentHashMap<>();
    static final Pattern SLUG_PATTERN = Pattern.compile("^[a-z0-9]+(?:-[a-z0-9]+)*$");

    static Map<String, Object> monsterCreateView(Monster m) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("slug", m.slug);
        out.put("name", m.name);
        out.put("cr", m.cr);
        out.put("armor_class", m.armorClass);
        out.put("hit_points", m.hitPoints);
        return out;
    }

    static Map<String, Object> monsterFullView(Monster m) {
        Map<String, Object> out = monsterCreateView(m);
        out.put("tags", m.tags);
        return out;
    }

    static Map<String, Object> itemView(Item i) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("slug", i.slug);
        out.put("name", i.name);
        out.put("type", i.type);
        out.put("rarity", i.rarity);
        out.put("cost_gp", i.costGp);
        return out;
    }

    static class MonstersHandler implements HttpHandler {
        private static final Pattern SLUG_PATH = Pattern.compile(
                "^/v1/compendium/monsters/([^/]+)/?$");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();

            if ("POST".equalsIgnoreCase(method)
                    && (path.equals("/v1/compendium/monsters") || path.equals("/v1/compendium/monsters/"))) {
                handleCreate(exchange);
                return;
            }

            if ("GET".equalsIgnoreCase(method)) {
                Matcher m = SLUG_PATH.matcher(path);
                if (m.matches()) {
                    handleRead(exchange, m.group(1));
                    return;
                }
            }

            sendError(exchange, 404, "not found");
        }

        private void handleCreate(HttpExchange exchange) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                if (!(body instanceof Map)) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }
                Map<?, ?> obj = (Map<?, ?>) body;

                Object slugObj = obj.get("slug");
                Object nameObj = obj.get("name");
                Object crObj = obj.get("cr");
                if (!(slugObj instanceof String) || !SLUG_PATTERN.matcher((String) slugObj).matches()) {
                    sendError(exchange, 400, "invalid slug");
                    return;
                }
                if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                    sendError(exchange, 400, "invalid name");
                    return;
                }
                if (!(crObj instanceof String) || ((String) crObj).isEmpty()) {
                    sendError(exchange, 400, "invalid cr");
                    return;
                }
                Long armorClass = toInteger(obj.get("armor_class"));
                Long hitPoints = toInteger(obj.get("hit_points"));
                if (armorClass == null || hitPoints == null) {
                    sendError(exchange, 400, "invalid armor_class or hit_points");
                    return;
                }

                List<String> tags = new ArrayList<>();
                Object tagsObj = obj.get("tags");
                if (tagsObj != null) {
                    if (!(tagsObj instanceof List)) {
                        sendError(exchange, 400, "invalid tags");
                        return;
                    }
                    for (Object t : (List<?>) tagsObj) {
                        if (!(t instanceof String)) {
                            sendError(exchange, 400, "invalid tags");
                            return;
                        }
                        tags.add((String) t);
                    }
                }

                String slug = (String) slugObj;
                Monster monster = new Monster();
                monster.slug = slug;
                monster.name = (String) nameObj;
                monster.cr = (String) crObj;
                monster.armorClass = armorClass;
                monster.hitPoints = hitPoints;
                monster.tags = tags;

                Monster existing = MONSTERS.putIfAbsent(slug, monster);
                if (existing != null) {
                    sendError(exchange, 409, "duplicate slug");
                    return;
                }
                SqliteStore.persistAll();

                sendJson(exchange, 201, monsterCreateView(monster));
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleRead(HttpExchange exchange, String slug) throws IOException {
            Monster monster = MONSTERS.get(slug);
            if (monster == null) {
                sendError(exchange, 404, "unknown monster");
                return;
            }
            sendJson(exchange, 200, monsterFullView(monster));
        }
    }

    static class ItemsHandler implements HttpHandler {
        private static final Pattern SLUG_PATH = Pattern.compile(
                "^/v1/compendium/items/([^/]+)/?$");

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();

            if ("POST".equalsIgnoreCase(method)
                    && (path.equals("/v1/compendium/items") || path.equals("/v1/compendium/items/"))) {
                handleCreate(exchange);
                return;
            }

            if ("GET".equalsIgnoreCase(method)) {
                Matcher m = SLUG_PATH.matcher(path);
                if (m.matches()) {
                    handleRead(exchange, m.group(1));
                    return;
                }
            }

            sendError(exchange, 404, "not found");
        }

        private void handleCreate(HttpExchange exchange) throws IOException {
            try {
                Object body = Json.parse(readBody(exchange));
                if (!(body instanceof Map)) {
                    sendError(exchange, 400, "invalid request");
                    return;
                }
                Map<?, ?> obj = (Map<?, ?>) body;

                Object slugObj = obj.get("slug");
                Object nameObj = obj.get("name");
                Object typeObj = obj.get("type");
                Object rarityObj = obj.get("rarity");
                if (!(slugObj instanceof String) || !SLUG_PATTERN.matcher((String) slugObj).matches()) {
                    sendError(exchange, 400, "invalid slug");
                    return;
                }
                if (!(nameObj instanceof String) || ((String) nameObj).isEmpty()) {
                    sendError(exchange, 400, "invalid name");
                    return;
                }
                if (!(typeObj instanceof String) || ((String) typeObj).isEmpty()) {
                    sendError(exchange, 400, "invalid type");
                    return;
                }
                if (!(rarityObj instanceof String) || ((String) rarityObj).isEmpty()) {
                    sendError(exchange, 400, "invalid rarity");
                    return;
                }
                Long costGp = toInteger(obj.get("cost_gp"));
                if (costGp == null) {
                    sendError(exchange, 400, "invalid cost_gp");
                    return;
                }

                String slug = (String) slugObj;
                Item item = new Item();
                item.slug = slug;
                item.name = (String) nameObj;
                item.type = (String) typeObj;
                item.rarity = (String) rarityObj;
                item.costGp = costGp;

                Item existing = ITEMS.putIfAbsent(slug, item);
                if (existing != null) {
                    sendError(exchange, 409, "duplicate slug");
                    return;
                }
                SqliteStore.persistAll();

                sendJson(exchange, 201, itemView(item));
            } catch (Exception e) {
                sendError(exchange, 400, "invalid request");
            }
        }

        private void handleRead(HttpExchange exchange, String slug) throws IOException {
            Item item = ITEMS.get(slug);
            if (item == null) {
                sendError(exchange, 404, "unknown item");
                return;
            }
            sendJson(exchange, 200, itemView(item));
        }
    }

    // ---------- Character math helpers ----------

    private static long abilityModifier(long score) {
        return Math.floorDiv(score - 10, 2);
    }

    private static long proficiencyBonus(long level) {
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    // ---------- Helpers ----------

    private static Long toInteger(Object o) {
        if (o instanceof Long) {
            return (Long) o;
        }
        if (o instanceof Integer) {
            return ((Integer) o).longValue();
        }
        if (o instanceof Double) {
            double d = (Double) o;
            if (d == Math.floor(d) && !Double.isInfinite(d)) {
                return (long) d;
            }
        }
        return null;
    }

    private static double toDouble(Object o) {
        if (o instanceof Number) {
            return ((Number) o).doubleValue();
        }
        throw new IllegalArgumentException("expected number, got " + o);
    }

    private static Object numeric(double d) {
        if (d == Math.floor(d) && !Double.isInfinite(d)) {
            long l = (long) d;
            return l;
        }
        return d;
    }

    private static String readBody(HttpExchange exchange) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = exchange.getRequestBody().read(buf)) != -1) {
            out.write(buf, 0, n);
        }
        return out.toString(StandardCharsets.UTF_8);
    }

    private static void sendJson(HttpExchange exchange, int status, Object payload) throws IOException {
        String json = Json.stringify(payload);
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static void sendError(HttpExchange exchange, int status, String message) throws IOException {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("error", message);
        sendJson(exchange, status, resp);
    }

    // ---------- SQLite-backed durable storage ----------
    //
    // Hand-rolled writer for the SQLite file format (single-page tables), since
    // only the Java standard library is available (no JDBC/sqlite driver).

    static class SqliteStore {
        static final int SCHEMA_VERSION = 1;
        static final int PAGE_SIZE = 4096;
        static final Path DB_PATH = Path.of("game.db");
        static volatile boolean initialized = false;

        static synchronized void initialize() {
            try {
                writeDatabase();
                initialized = true;
            } catch (IOException e) {
                initialized = false;
            }
        }

        static synchronized void reset() {
            try {
                writeDatabase();
                initialized = true;
            } catch (IOException e) {
                initialized = false;
            }
        }

        static synchronized void persistAll() {
            try {
                writeDatabase();
            } catch (IOException ignored) {
                // durable persistence is best-effort; in-memory state remains authoritative
            }
        }

        private static void writeDatabase() throws IOException {
            List<Object[]> masterRows = new ArrayList<>();
            // (type, name, tbl_name, rootpage, sql)
            masterRows.add(new Object[]{"table", "meta", "meta", 2L,
                    "CREATE TABLE meta (key TEXT, value TEXT)"});
            masterRows.add(new Object[]{"table", "users", "users", 3L,
                    "CREATE TABLE users (username TEXT, role TEXT, salt TEXT, hash TEXT)"});
            masterRows.add(new Object[]{"table", "combat_sessions", "combat_sessions", 4L,
                    "CREATE TABLE combat_sessions (id TEXT, round INTEGER, turn_index INTEGER, data TEXT)"});

            byte[] page1 = buildPageWithHeader(masterRows);

            List<Object[]> metaRows = new ArrayList<>();
            metaRows.add(new Object[]{"schema_version", String.valueOf(SCHEMA_VERSION)});
            byte[] page2 = buildLeafPage(0, metaRows);

            List<Object[]> userRows = new ArrayList<>();
            long uRowId = 1;
            for (User u : USERS.values()) {
                userRows.add(new Object[]{
                        u.username, u.role,
                        Base64.getEncoder().encodeToString(u.salt),
                        Base64.getEncoder().encodeToString(u.hash)});
                uRowId++;
            }
            byte[] page3 = buildLeafPage(0, userRows);

            List<Object[]> sessionRows = new ArrayList<>();
            for (CombatSession s : COMBAT_SESSIONS.values()) {
                Map<String, Object> summary = new LinkedHashMap<>();
                List<Map<String, Object>> order = new ArrayList<>();
                for (Combatant c : s.order) {
                    order.add(combatantView(c));
                }
                summary.put("order", order);
                Map<String, Object> conditionsOut = new LinkedHashMap<>();
                for (Map.Entry<String, List<ConditionEntry>> e : s.conditions.entrySet()) {
                    List<Map<String, Object>> condList = new ArrayList<>();
                    for (ConditionEntry ce : e.getValue()) {
                        condList.add(conditionView(ce));
                    }
                    conditionsOut.put(e.getKey(), condList);
                }
                summary.put("conditions", conditionsOut);
                String dataJson = Json.stringify(summary);
                sessionRows.add(new Object[]{s.id, (long) s.round, (long) s.turnIndex, dataJson});
            }
            byte[] page4 = buildLeafPage(0, sessionRows);

            byte[] db = new byte[PAGE_SIZE * 4];
            System.arraycopy(page1, 0, db, 0, PAGE_SIZE);
            System.arraycopy(page2, 0, db, PAGE_SIZE, PAGE_SIZE);
            System.arraycopy(page3, 0, db, PAGE_SIZE * 2, PAGE_SIZE);
            System.arraycopy(page4, 0, db, PAGE_SIZE * 3, PAGE_SIZE);

            Files.write(DB_PATH, db);
        }

        // Builds page 1: 100-byte database header followed by the sqlite_master leaf page.
        private static byte[] buildPageWithHeader(List<Object[]> masterRows) {
            byte[] page = buildLeafPage(100, masterRows);

            writeBytes(page, 0, new byte[]{'S','Q','L','i','t','e',' ','f','o','r','m','a','t',' ','3',0});
            writeUint16(page, 16, PAGE_SIZE);
            page[18] = 1; // file format write version
            page[19] = 1; // file format read version
            page[20] = 0; // reserved space per page
            page[21] = 64; // max embedded payload fraction
            page[22] = 32; // min embedded payload fraction
            page[23] = 32; // leaf payload fraction
            writeUint32(page, 24, 1); // file change counter
            writeUint32(page, 28, 4); // size of db in pages
            writeUint32(page, 32, 0); // first freelist page
            writeUint32(page, 36, 0); // freelist page count
            writeUint32(page, 40, 1); // schema cookie
            writeUint32(page, 44, 4); // schema format number
            writeUint32(page, 48, 0); // default page cache size
            writeUint32(page, 52, 0); // largest root b-tree page (0 = not vacuum)
            writeUint32(page, 56, 1); // text encoding (1 = UTF-8)
            writeUint32(page, 60, 0); // user version
            writeUint32(page, 64, 0); // incremental vacuum mode
            writeUint32(page, 68, 0); // application id
            writeUint32(page, 92, 1); // version-valid-for
            writeUint32(page, 96, 3045000); // sqlite version number

            return page;
        }

        // Builds a single leaf table b-tree page containing one cell per row.
        // hdrOffset is where the 8-byte b-tree page header begins within the page
        // (100 for page 1, which is prefixed by the file header; 0 otherwise).
        private static byte[] buildLeafPage(int hdrOffset, List<Object[]> rows) {
            byte[] page = new byte[PAGE_SIZE];
            int numCells = rows.size();
            byte[][] cells = new byte[numCells][];
            for (int i = 0; i < numCells; i++) {
                byte[] payload = record(rows.get(i));
                byte[] payloadLen = varint(payload.length);
                byte[] rowid = varint(i + 1);
                cells[i] = concat(payloadLen, rowid, payload);
            }

            int[] cellOffsets = new int[numCells];
            int offset = PAGE_SIZE;
            for (int i = 0; i < numCells; i++) {
                offset -= cells[i].length;
                cellOffsets[i] = offset;
            }

            page[hdrOffset] = 0x0D; // leaf table b-tree page
            writeUint16(page, hdrOffset + 1, 0); // first freeblock
            writeUint16(page, hdrOffset + 3, numCells);
            writeUint16(page, hdrOffset + 5, offset == PAGE_SIZE ? 0 : offset);
            page[hdrOffset + 7] = 0; // fragmented free bytes

            int cellPtrStart = hdrOffset + 8;
            for (int i = 0; i < numCells; i++) {
                writeUint16(page, cellPtrStart + i * 2, cellOffsets[i]);
            }
            for (int i = 0; i < numCells; i++) {
                writeBytes(page, cellOffsets[i], cells[i]);
            }

            return page;
        }

        // Encodes a row as a SQLite record: varint header (header length + serial
        // types) followed by the values, in column order.
        private static byte[] record(Object[] values) {
            List<byte[]> serialTypes = new ArrayList<>();
            List<byte[]> bodies = new ArrayList<>();
            for (Object v : values) {
                if (v == null) {
                    serialTypes.add(varint(0));
                    bodies.add(new byte[0]);
                } else if (v instanceof Long) {
                    long l = (Long) v;
                    serialTypes.add(varint(6)); // always encode as 64-bit signed int
                    bodies.add(int64(l));
                } else {
                    byte[] utf8 = String.valueOf(v).getBytes(StandardCharsets.UTF_8);
                    serialTypes.add(varint(13 + 2L * utf8.length));
                    bodies.add(utf8);
                }
            }

            int serialTypesLen = 0;
            for (byte[] st : serialTypes) serialTypesLen += st.length;

            byte[] headerLenVarint = varint(1 + serialTypesLen);
            if (varint(headerLenVarint.length + serialTypesLen).length != headerLenVarint.length) {
                headerLenVarint = varint(headerLenVarint.length + serialTypesLen + 1);
            }

            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try {
                out.write(headerLenVarint);
                for (byte[] st : serialTypes) out.write(st);
                for (byte[] b : bodies) out.write(b);
            } catch (IOException e) {
                throw new RuntimeException(e);
            }
            return out.toByteArray();
        }

        private static byte[] int64(long v) {
            byte[] b = new byte[8];
            for (int i = 7; i >= 0; i--) {
                b[i] = (byte) (v & 0xFF);
                v >>= 8;
            }
            return b;
        }

        // SQLite variable-length integer: big-endian base-128, high bit = continuation.
        private static byte[] varint(long v) {
            byte[] buf = new byte[9];
            if (v < 0) {
                for (int i = 0; i < 8; i++) {
                    buf[i] = (byte) ((v >> (56 - 7 * i)) | 0x80);
                }
                buf[8] = (byte) v;
                return buf;
            }
            if (v <= 0x7F) {
                return new byte[]{(byte) v};
            }
            List<Byte> bytesRev = new ArrayList<>();
            long remaining = v;
            while (remaining != 0) {
                bytesRev.add((byte) (remaining & 0x7F));
                remaining >>>= 7;
            }
            int n = bytesRev.size();
            byte[] result = new byte[n];
            for (int i = 0; i < n; i++) {
                byte b = bytesRev.get(n - 1 - i);
                result[i] = (byte) (i == n - 1 ? b : (b | 0x80));
            }
            return result;
        }

        private static byte[] concat(byte[]... parts) {
            int total = 0;
            for (byte[] p : parts) total += p.length;
            byte[] out = new byte[total];
            int pos = 0;
            for (byte[] p : parts) {
                System.arraycopy(p, 0, out, pos, p.length);
                pos += p.length;
            }
            return out;
        }

        private static void writeBytes(byte[] page, int offset, byte[] data) {
            System.arraycopy(data, 0, page, offset, data.length);
        }

        private static void writeUint16(byte[] page, int offset, int value) {
            page[offset] = (byte) ((value >> 8) & 0xFF);
            page[offset + 1] = (byte) (value & 0xFF);
        }

        private static void writeUint32(byte[] page, int offset, long value) {
            page[offset] = (byte) ((value >> 24) & 0xFF);
            page[offset + 1] = (byte) ((value >> 16) & 0xFF);
            page[offset + 2] = (byte) ((value >> 8) & 0xFF);
            page[offset + 3] = (byte) (value & 0xFF);
        }
    }

    // ---------- Minimal JSON parser/serializer ----------

    static class Json {
        static Object parse(String s) {
            Parser p = new Parser(s);
            Object v = p.parseValue();
            p.skipWhitespace();
            if (p.pos != p.len) {
                throw new IllegalArgumentException("unexpected trailing content");
            }
            return v;
        }

        static String stringify(Object o) {
            StringBuilder sb = new StringBuilder();
            write(o, sb);
            return sb.toString();
        }

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
                for (Map.Entry<?, ?> e : ((Map<?, ?>) o).entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    writeString(String.valueOf(e.getKey()), sb);
                    sb.append(':');
                    write(e.getValue(), sb);
                }
                sb.append('}');
            } else if (o instanceof List) {
                sb.append('[');
                boolean first = true;
                for (Object item : (List<?>) o) {
                    if (!first) sb.append(',');
                    first = false;
                    write(item, sb);
                }
                sb.append(']');
            } else {
                writeString(o.toString(), sb);
            }
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

        static class Parser {
            final String s;
            final int len;
            int pos = 0;

            Parser(String s) {
                this.s = s;
                this.len = s.length();
            }

            void skipWhitespace() {
                while (pos < len && Character.isWhitespace(s.charAt(pos))) {
                    pos++;
                }
            }

            Object parseValue() {
                skipWhitespace();
                if (pos >= len) {
                    throw new IllegalArgumentException("unexpected end of input");
                }
                char c = s.charAt(pos);
                if (c == '{') return parseObject();
                if (c == '[') return parseArray();
                if (c == '"') return parseString();
                if (c == 't' || c == 'f') return parseBoolean();
                if (c == 'n') return parseNull();
                return parseNumber();
            }

            Map<String, Object> parseObject() {
                Map<String, Object> map = new LinkedHashMap<>();
                pos++; // {
                skipWhitespace();
                if (pos < len && s.charAt(pos) == '}') {
                    pos++;
                    return map;
                }
                while (true) {
                    skipWhitespace();
                    String key = parseString();
                    skipWhitespace();
                    if (s.charAt(pos) != ':') {
                        throw new IllegalArgumentException("expected ':'");
                    }
                    pos++;
                    Object value = parseValue();
                    map.put(key, value);
                    skipWhitespace();
                    char c = s.charAt(pos);
                    if (c == ',') {
                        pos++;
                    } else if (c == '}') {
                        pos++;
                        break;
                    } else {
                        throw new IllegalArgumentException("expected ',' or '}'");
                    }
                }
                return map;
            }

            List<Object> parseArray() {
                List<Object> list = new ArrayList<>();
                pos++; // [
                skipWhitespace();
                if (pos < len && s.charAt(pos) == ']') {
                    pos++;
                    return list;
                }
                while (true) {
                    Object value = parseValue();
                    list.add(value);
                    skipWhitespace();
                    char c = s.charAt(pos);
                    if (c == ',') {
                        pos++;
                    } else if (c == ']') {
                        pos++;
                        break;
                    } else {
                        throw new IllegalArgumentException("expected ',' or ']'");
                    }
                }
                return list;
            }

            String parseString() {
                skipWhitespace();
                if (s.charAt(pos) != '"') {
                    throw new IllegalArgumentException("expected string");
                }
                pos++;
                StringBuilder sb = new StringBuilder();
                while (true) {
                    char c = s.charAt(pos++);
                    if (c == '"') break;
                    if (c == '\\') {
                        char esc = s.charAt(pos++);
                        switch (esc) {
                            case '"': sb.append('"'); break;
                            case '\\': sb.append('\\'); break;
                            case '/': sb.append('/'); break;
                            case 'n': sb.append('\n'); break;
                            case 'r': sb.append('\r'); break;
                            case 't': sb.append('\t'); break;
                            case 'b': sb.append('\b'); break;
                            case 'f': sb.append('\f'); break;
                            case 'u':
                                String hex = s.substring(pos, pos + 4);
                                sb.append((char) Integer.parseInt(hex, 16));
                                pos += 4;
                                break;
                            default:
                                throw new IllegalArgumentException("invalid escape: " + esc);
                        }
                    } else {
                        sb.append(c);
                    }
                }
                return sb.toString();
            }

            Boolean parseBoolean() {
                if (s.startsWith("true", pos)) {
                    pos += 4;
                    return Boolean.TRUE;
                } else if (s.startsWith("false", pos)) {
                    pos += 5;
                    return Boolean.FALSE;
                }
                throw new IllegalArgumentException("invalid literal");
            }

            Object parseNull() {
                if (s.startsWith("null", pos)) {
                    pos += 4;
                    return null;
                }
                throw new IllegalArgumentException("invalid literal");
            }

            Object parseNumber() {
                int start = pos;
                if (pos < len && (s.charAt(pos) == '-' || s.charAt(pos) == '+')) {
                    pos++;
                }
                boolean isDouble = false;
                while (pos < len) {
                    char c = s.charAt(pos);
                    if (Character.isDigit(c)) {
                        pos++;
                    } else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                        isDouble = true;
                        pos++;
                    } else {
                        break;
                    }
                }
                String num = s.substring(start, pos);
                if (num.isEmpty()) {
                    throw new IllegalArgumentException("invalid number");
                }
                if (isDouble) {
                    return Double.parseDouble(num);
                }
                try {
                    return Long.parseLong(num);
                } catch (NumberFormatException e) {
                    return Double.parseDouble(num);
                }
            }
        }
    }
}
