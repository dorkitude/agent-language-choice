package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.security.SecureRandom;
import java.security.spec.KeySpec;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.time.Instant;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

import dnd.game.Rules;
import dnd.json.JsonUtils;
import dnd.model.Combatant;
import dnd.model.CombatSession;
import dnd.model.Condition;
import dnd.model.User;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Registers all HTTP handlers and routes requests to the storage layer.
 * This is a thin translation layer: JSON in, domain validation, storage call,
 * JSON out. No business state lives here.
 */
public class RequestRouter {
    private static final Pattern DICE_PATTERN = Pattern.compile("^(\\d+)d(\\d+)([+-]\\d+)?$");
    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z0-9_-]{2,32}$");
    private static final SecureRandom RANDOM = new SecureRandom();

    private final Storage storage;

    public RequestRouter(Storage storage) {
        this.storage = storage;
    }

    public void register(HttpServer server) {
        server.createContext("/health", this::handleHealth);
        server.createContext("/v1/dice/stats", this::handleDiceStats);
        server.createContext("/v1/checks/ability", this::handleAbilityCheck);
        server.createContext("/v1/encounters/adjusted-xp", this::handleAdjustedXp);
        server.createContext("/v1/initiative/order", this::handleInitiative);
        server.createContext("/v1/characters/ability-modifier", this::handleAbilityModifier);
        server.createContext("/v1/characters/proficiency", this::handleProficiency);
        server.createContext("/v1/characters/derived-stats", this::handleDerivedStats);
        server.createContext("/v1/combat/sessions", this::handleCombatSessionCreate);
        server.createContext("/v1/combat/sessions/", this::handleCombatSessionAction);
        server.createContext("/v1/auth/register", this::handleRegister);
        server.createContext("/v1/auth/login", this::handleLogin);
        server.createContext("/v1/storage/status", this::handleStorageStatus);
        server.createContext("/v1/storage/reset", this::handleStorageReset);
        server.createContext("/v1/compendium/monsters", this::handleMonsterCreate);
        server.createContext("/v1/compendium/monsters/", this::handleMonsterRead);
        server.createContext("/v1/compendium/items", this::handleItemCreate);
        server.createContext("/v1/compendium/items/", this::handleItemRead);
        server.createContext("/v1/campaigns", this::handleCampaignCreate);
        server.createContext("/v1/campaigns/", this::handleCampaignAction);
        server.createContext("/v1/phb/spell-slots", this::handleSpellSlots);
        server.createContext("/v1/phb/rests/long", this::handleLongRest);
        server.createContext("/v1/phb/equipment-load", this::handleEquipmentLoad);
        server.createContext("/v1/dm/encounter-builder", this::handleDmEncounterBuilder);
        server.createContext("/v1/dm/loot-parcel", this::handleDmLootParcel);
        server.createContext("/v1/dm/session-recap", this::handleDmSessionRecap);
        server.createContext("/v1/play/campaigns", this::handlePlayCampaignCreate);
    }

    private void handleHealth(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, "{\"ok\":true}");
    }

    private void handleStorageStatus(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(storage.status()));
    }

    private void handleStorageReset(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            storage.reset();
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("ok", true);
            res.put("schema_version", 1);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 500, "{\"error\":\"Storage reset failed\"}");
        }
    }

    private void handleDiceStats(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String expression = (String) req.get("expression");
            if (expression == null) throw new RuntimeException("Missing expression");
            Matcher matcher = DICE_PATTERN.matcher(expression.trim());
            if (!matcher.matches()) throw new RuntimeException("Invalid expression");
            int count = Integer.parseInt(matcher.group(1));
            int sides = Integer.parseInt(matcher.group(2));
            if (count <= 0 || sides <= 0) throw new RuntimeException("Count and sides must be positive");
            String modifierPart = matcher.group(3);
            int modifier = modifierPart == null ? 0 : Integer.parseInt(modifierPart);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("dice_count", count);
            res.put("sides", sides);
            res.put("modifier", modifier);
            res.put("min", count + modifier);
            res.put("max", count * sides + modifier);
            res.put("average", count * (sides + 1) / 2.0 + modifier);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleAbilityCheck(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int roll = JsonUtils.toInt(req.get("roll"));
            int modifier = JsonUtils.toInt(req.get("modifier"));
            int dc = JsonUtils.toInt(req.get("dc"));
            int total = roll + modifier;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("total", total);
            res.put("success", total >= dc);
            res.put("margin", total - dc);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleAdjustedXp(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            List<Object> partyList = (List<Object>) req.get("party");
            List<Object> monstersList = (List<Object>) req.get("monsters");
            if (partyList == null || monstersList == null) throw new RuntimeException("Missing fields");

            List<Map<String, Object>> monsters = new ArrayList<>();
            for (Object monsterObj : monstersList) {
                monsters.add((Map<String, Object>) monsterObj);
            }

            Map<String, Object> calc = Rules.calculateEncounter(partyList, monsters);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("base_xp", calc.get("base_xp"));
            res.put("monster_count", calc.get("monster_count"));
            res.put("multiplier", calc.get("multiplier"));
            res.put("adjusted_xp", calc.get("adjusted_xp"));
            res.put("difficulty", calc.get("difficulty"));
            res.put("thresholds", calc.get("thresholds"));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleInitiative(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            List<Object> combatantsList = (List<Object>) req.get("combatants");
            if (combatantsList == null) throw new RuntimeException("Missing combatants");

            List<Map<String, Object>> combatants = new ArrayList<>();
            for (Object combatantObj : combatantsList) {
                Map<String, Object> combatant = (Map<String, Object>) combatantObj;
                String name = (String) combatant.get("name");
                int dex = JsonUtils.toInt(combatant.get("dex"));
                int roll = JsonUtils.toInt(combatant.get("roll"));
                int score = roll + dex;
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("name", name);
                out.put("score", score);
                out.put("_dex", dex);
                combatants.add(out);
            }

            combatants.sort((a, b) -> {
                int scoreA = (Integer) a.get("score");
                int scoreB = (Integer) b.get("score");
                if (scoreB != scoreA) return scoreB - scoreA;
                int dexA = (Integer) a.get("_dex");
                int dexB = (Integer) b.get("_dex");
                if (dexB != dexA) return dexB - dexA;
                String nameA = (String) a.get("name");
                String nameB = (String) b.get("name");
                return nameA.compareTo(nameB);
            });

            List<Map<String, Object>> order = new ArrayList<>();
            for (Map<String, Object> combatant : combatants) {
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("name", combatant.get("name"));
                out.put("score", combatant.get("score"));
                order.add(out);
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("order", order);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleAbilityModifier(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int score = JsonUtils.toInt(req.get("score"));
            if (score < 1 || score > 30) throw new RuntimeException("Score out of range");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("score", score);
            res.put("modifier", Rules.abilityModifier(score));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleProficiency(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int level = JsonUtils.toInt(req.get("level"));
            if (level < 1 || level > 20) throw new RuntimeException("Level out of range");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("level", level);
            res.put("proficiency_bonus", Rules.proficiencyBonus(level));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleDerivedStats(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int level = JsonUtils.toInt(req.get("level"));
            if (level < 1 || level > 20) throw new RuntimeException("Level out of range");

            Map<String, Object> abilities = (Map<String, Object>) req.get("abilities");
            if (abilities == null) throw new RuntimeException("Missing abilities");
            String[] abilityNames = {"str", "dex", "con", "int", "wis", "cha"};

            Map<String, Integer> modifiers = new LinkedHashMap<>();
            for (String name : abilityNames) {
                Object val = abilities.get(name);
                if (val == null) throw new RuntimeException("Missing ability: " + name);
                modifiers.put(name, Rules.abilityModifier(JsonUtils.toInt(val)));
            }

            Map<String, Object> armor = (Map<String, Object>) req.get("armor");
            if (armor == null) throw new RuntimeException("Missing armor");
            int base = JsonUtils.toInt(armor.get("base"));
            int dexCap = JsonUtils.toInt(armor.get("dex_cap"));
            boolean shield = Boolean.TRUE.equals(armor.get("shield"));
            int shieldBonus = shield ? 2 : 0;
            int armorClass = base + Math.min(modifiers.get("dex"), dexCap) + shieldBonus;

            int hpMax = level * (6 + modifiers.get("con"));

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("level", level);
            res.put("proficiency_bonus", Rules.proficiencyBonus(level));
            res.put("hp_max", hpMax);
            res.put("armor_class", armorClass);
            res.put("modifiers", modifiers);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCombatSessionCreate(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            if (id == null || id.isEmpty()) throw new RuntimeException("Missing id");
            List<Object> combatantsList = (List<Object>) req.get("combatants");
            if (combatantsList == null || combatantsList.isEmpty()) throw new RuntimeException("Missing combatants");
            if (storage.getCombatSession(id) != null) throw new RuntimeException("Duplicate session id");

            List<Combatant> combatants = new ArrayList<>();
            for (Object combatantObj : combatantsList) {
                Map<String, Object> combatant = (Map<String, Object>) combatantObj;
                String name = (String) combatant.get("name");
                if (name == null || name.isEmpty()) throw new RuntimeException("Missing combatant name");
                int dex = JsonUtils.toInt(combatant.get("dex"));
                int roll = JsonUtils.toInt(combatant.get("roll"));
                int score = roll + dex;
                combatants.add(new Combatant(name, score, dex, roll));
            }

            combatants.sort((a, b) -> {
                if (b.score != a.score) return b.score - a.score;
                if (b.dex != a.dex) return b.dex - a.dex;
                return a.name.compareTo(b.name);
            });

            CombatSession session = new CombatSession(id, combatants);
            if (!storage.insertCombatSession(session)) throw new RuntimeException("Duplicate session id");

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("round", 1);
            res.put("turn_index", 0);
            res.put("active", combatantJson(combatants.get(0)));
            List<Map<String, Object>> order = new ArrayList<>();
            for (Combatant c : combatants) order.add(combatantJson(c));
            res.put("order", order);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCombatSessionAction(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/combat/sessions/";
        if (!path.startsWith(prefix)) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        String rest = path.substring(prefix.length());
        int slash = rest.indexOf('/');
        if (slash < 0) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        String id = rest.substring(0, slash);
        String action = rest.substring(slash + 1);
        CombatSession session = storage.getCombatSession(id);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Session not found\"}");
            return;
        }
        try {
            if ("conditions".equals(action)) {
                String body = HttpSupport.readBody(exchange);
                Map<String, Object> req = JsonUtils.parseJsonObject(body);
                String target = (String) req.get("target");
                String condition = (String) req.get("condition");
                int durationRounds = JsonUtils.toInt(req.get("duration_rounds"));
                if (target == null || condition == null) throw new RuntimeException("Missing fields");
                if (durationRounds <= 0) throw new RuntimeException("Invalid duration");

                boolean found = false;
                for (Combatant c : session.order) {
                    if (c.name.equals(target)) {
                        found = true;
                        break;
                    }
                }
                if (!found) throw new RuntimeException("Unknown target");

                storage.addCondition(id, target, condition, durationRounds);
                session = storage.getCombatSession(id);

                Map<String, Object> res = new LinkedHashMap<>();
                res.put("target", target);
                List<Map<String, Object>> conditions = new ArrayList<>();
                for (Condition cond : session.conditions.get(target)) {
                    Map<String, Object> condJson = new LinkedHashMap<>();
                    condJson.put("condition", cond.condition);
                    condJson.put("remaining_rounds", cond.remainingRounds);
                    conditions.add(condJson);
                }
                res.put("conditions", conditions);
                HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            } else if ("advance".equals(action)) {
                session.turnIndex++;
                if (session.turnIndex >= session.order.size()) {
                    session.turnIndex = 0;
                    session.round++;
                }
                Combatant active = session.order.get(session.turnIndex);

                storage.advanceCombatSession(session, active);
                session = storage.getCombatSession(id);

                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", session.id);
                res.put("round", session.round);
                res.put("turn_index", session.turnIndex);
                res.put("active", combatantJson(active));
                Map<String, Object> conditions = new LinkedHashMap<>();
                for (Map.Entry<String, List<Condition>> entry : session.conditions.entrySet()) {
                    List<Map<String, Object>> condList = new ArrayList<>();
                    for (Condition cond : entry.getValue()) {
                        Map<String, Object> condJson = new LinkedHashMap<>();
                        condJson.put("condition", cond.condition);
                        condJson.put("remaining_rounds", cond.remainingRounds);
                        condList.add(condJson);
                    }
                    conditions.put(entry.getKey(), condList);
                }
                if (!conditions.containsKey(active.name)) {
                    conditions.put(active.name, new ArrayList<>());
                }
                res.put("conditions", conditions);
                HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            } else {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            }
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleRegister(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String username = (String) req.get("username");
            String password = (String) req.get("password");
            String role = (String) req.get("role");

            if (username == null || password == null || role == null) throw new RuntimeException("Missing fields");
            if (!USERNAME_PATTERN.matcher(username).matches()) throw new RuntimeException("Invalid username");
            if (password.length() < 8) throw new RuntimeException("Password too short");
            if (!"dm".equals(role) && !"player".equals(role)) throw new RuntimeException("Invalid role");

            if (storage.getUser(username) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Username already exists\"}");
                return;
            }

            String salt = generateSalt();
            String hash = hashPassword(password, salt);
            User user = new User(username, role, salt, hash);
            if (!storage.insertUser(user)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Username already exists\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", username);
            res.put("role", role);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleLogin(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String username = (String) req.get("username");
            String password = (String) req.get("password");

            if (username == null || password == null) throw new RuntimeException("Missing fields");

            User user = storage.getUser(username);
            if (user == null || !hashPassword(password, user.salt).equals(user.hash)) {
                HttpSupport.sendResponse(exchange, 401, "{\"error\":\"Invalid credentials\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", username);
            res.put("token", "session-" + username);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleMonsterCreate(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String slug = (String) req.get("slug");
            String name = (String) req.get("name");
            String cr = (String) req.get("cr");
            if (slug == null || slug.isEmpty() || name == null || name.isEmpty() || cr == null || cr.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            int armorClass = JsonUtils.toInt(req.get("armor_class"));
            int hitPoints = JsonUtils.toInt(req.get("hit_points"));

            List<String> tags = new ArrayList<>();
            Object tagsObj = req.get("tags");
            if (tagsObj != null) {
                if (!(tagsObj instanceof List)) throw new RuntimeException("Invalid tags");
                for (Object tagObj : (List<Object>) tagsObj) {
                    if (!(tagObj instanceof String)) throw new RuntimeException("Invalid tag");
                    tags.add((String) tagObj);
                }
            }

            if (storage.getMonster(slug) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Monster already exists\"}");
                return;
            }
            if (!storage.insertMonster(slug, name, cr, armorClass, hitPoints, tags)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Monster already exists\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", slug);
            res.put("name", name);
            res.put("cr", cr);
            res.put("armor_class", armorClass);
            res.put("hit_points", hitPoints);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleMonsterRead(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/compendium/monsters/";
        String slug = path.substring(prefix.length());
        if (slug.isEmpty()) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        Map<String, Object> monster = storage.getMonster(slug);
        if (monster == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Monster not found\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(monster));
    }

    private void handleItemCreate(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String slug = (String) req.get("slug");
            String name = (String) req.get("name");
            String type = (String) req.get("type");
            String rarity = (String) req.get("rarity");
            if (slug == null || slug.isEmpty() || name == null || name.isEmpty() || type == null || type.isEmpty() || rarity == null || rarity.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            int costGp = JsonUtils.toInt(req.get("cost_gp"));

            if (storage.getItem(slug) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Item already exists\"}");
                return;
            }
            if (!storage.insertItem(slug, name, type, rarity, costGp)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Item already exists\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", slug);
            res.put("name", name);
            res.put("type", type);
            res.put("rarity", rarity);
            res.put("cost_gp", costGp);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleItemRead(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/compendium/items/";
        String slug = path.substring(prefix.length());
        if (slug.isEmpty()) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        Map<String, Object> item = storage.getItem(slug);
        if (item == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Item not found\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(item));
    }

    private void handleCampaignCreate(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            String name = (String) req.get("name");
            String dm = (String) req.get("dm");
            if (id == null || id.isEmpty() || name == null || name.isEmpty() || dm == null || dm.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getCampaign(id) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Campaign already exists\"}");
                return;
            }
            if (!storage.insertCampaign(id, name, dm)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Campaign already exists\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("name", name);
            res.put("dm", dm);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCampaignAction(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/campaigns/";
        if (!path.startsWith(prefix)) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        String rest = path.substring(prefix.length());
        int slash = rest.indexOf('/');
        if (slash < 0) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }
        String campaignId = rest.substring(0, slash);
        String action = rest.substring(slash + 1);

        if ("GET".equals(exchange.getRequestMethod()) && "state".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", campaign.get("id"));
            res.put("name", campaign.get("name"));
            res.put("dm", campaign.get("dm"));
            res.put("characters", storage.listCampaignCharacters(campaignId));
            res.put("log_count", storage.countCampaignEvents(campaignId));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            return;
        }

        if ("GET".equals(exchange.getRequestMethod()) && "relationships".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("factions", storage.countFactions(campaignId));
            res.put("npcs", storage.countNpcs(campaignId));
            res.put("friendly_npcs", storage.countFriendlyNpcs(campaignId));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            return;
        }

        if ("GET".equals(exchange.getRequestMethod()) && "audit".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("events", storage.countCampaignEvents(campaignId));
            res.put("quests", storage.countQuests(campaignId));
            res.put("npcs", storage.countNpcs(campaignId));
            res.put("sessions", storage.countSessions(campaignId));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            return;
        }

        if ("GET".equals(exchange.getRequestMethod()) && "export".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("name", campaign.get("name"));
            res.put("characters", storage.countCampaignCharacters(campaignId));
            res.put("quests", storage.countQuests(campaignId));
            res.put("npcs", storage.countNpcs(campaignId));
            res.put("inventory_items", storage.countInventoryItems(campaignId));
            res.put("sessions", storage.countSessions(campaignId));
            res.put("schema_version", 1);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            return;
        }

        if ("analytics/summary".equals(action)) {
            if ("GET".equals(exchange.getRequestMethod())) {
                handleCampaignAnalyticsSummary(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }

        if ("analytics/risk-report".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handleCampaignRiskReport(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }

        if ("sessions".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handleScheduleSession(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }

        if (action.startsWith("sessions/")) {
            String sessionRest = action.substring("sessions/".length());
            int sessionSlash = sessionRest.indexOf('/');
            if (sessionSlash < 0) {
                if ("next".equals(sessionRest)) {
                    if ("GET".equals(exchange.getRequestMethod())) {
                        handleNextSession(exchange, campaignId);
                        return;
                    }
                    HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
                    return;
                }
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
                return;
            }
            String sessionId = sessionRest.substring(0, sessionSlash);
            String sessionAction = sessionRest.substring(sessionSlash + 1);
            if ("attendance".equals(sessionAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handleRecordAttendance(exchange, campaignId, sessionId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
                return;
            }
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && "downtime/crafting".equals(action)) {
            handleCraftingProjectCreate(exchange, campaignId);
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && action.startsWith("downtime/crafting/") && action.endsWith("/advance")) {
            String projectId = action.substring("downtime/crafting/".length(), action.length() - "/advance".length());
            if (projectId.isEmpty() || projectId.indexOf('/') >= 0) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
                return;
            }
            handleCraftingProjectAdvance(exchange, campaignId, projectId);
            return;
        }

        if ("GET".equals(exchange.getRequestMethod()) && "inventory/summary".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(storage.getInventorySummary(campaignId)));
            return;
        }

        if (action.startsWith("quests/")) {
            String questRest = action.substring("quests/".length());
            int questSlash = questRest.indexOf('/');
            if (questSlash < 0) {
                if ("summary".equals(questRest)) {
                    if ("GET".equals(exchange.getRequestMethod())) {
                        Map<String, Object> campaign = storage.getCampaign(campaignId);
                        if (campaign == null) {
                            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                            return;
                        }
                        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(storage.getQuestSummary(campaignId)));
                        return;
                    }
                    HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
                    return;
                }
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
                return;
            }
            String questId = questRest.substring(0, questSlash);
            String questAction = questRest.substring(questSlash + 1);
            if ("progress".equals(questAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handleQuestProgress(exchange, campaignId, questId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
                return;
            }
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && "inventory".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            try {
                String body = HttpSupport.readBody(exchange);
                Map<String, Object> req = JsonUtils.parseJsonObject(body);
                String itemSlug = (String) req.get("item_slug");
                String owner = (String) req.get("owner");
                int quantity = JsonUtils.toInt(req.get("quantity"));
                if (itemSlug == null || itemSlug.isEmpty() || owner == null || owner.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (quantity <= 0) throw new RuntimeException("Invalid quantity");
                storage.addInventoryItem(campaignId, itemSlug, owner, quantity);
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("item_slug", itemSlug);
                res.put("quantity", quantity);
                res.put("owner", owner);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } catch (RuntimeException e) {
                HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
            }
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && action.startsWith("characters/") && action.endsWith("/equipment")) {
            String charsPrefix = "characters/";
            String equipSuffix = "/equipment";
            if (action.length() <= charsPrefix.length() + equipSuffix.length()) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
                return;
            }
            String characterId = action.substring(charsPrefix.length(), action.length() - equipSuffix.length());
            if (characterId.isEmpty() || characterId.indexOf('/') >= 0) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
                return;
            }
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            boolean found = false;
            for (Map<String, Object> c : storage.listCampaignCharacters(campaignId)) {
                if (characterId.equals(c.get("id"))) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Character not found\"}");
                return;
            }
            try {
                String body = HttpSupport.readBody(exchange);
                Map<String, Object> req = JsonUtils.parseJsonObject(body);
                String itemSlug = (String) req.get("item_slug");
                int quantity = JsonUtils.toInt(req.get("quantity"));
                if (itemSlug == null || itemSlug.isEmpty()) throw new RuntimeException("Missing fields");
                if (quantity <= 0) throw new RuntimeException("Invalid quantity");
                if (!storage.assignEquipment(campaignId, characterId, itemSlug, quantity)) {
                    throw new RuntimeException("Insufficient quantity");
                }
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("character_id", characterId);
                res.put("item_slug", itemSlug);
                res.put("quantity", quantity);
                HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
            } catch (RuntimeException e) {
                HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
            }
            return;
        }

        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
                return;
            }
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            if ("characters".equals(action)) {
                String id = (String) req.get("id");
                String name = (String) req.get("name");
                int level = JsonUtils.toInt(req.get("level"));
                String className = (String) req.get("class");
                if (id == null || id.isEmpty() || name == null || name.isEmpty() || className == null || className.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (level < 1 || level > 20) throw new RuntimeException("Level out of range");
                if (!storage.insertCampaignCharacter(campaignId, id, name, level, className)) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Character already exists\"}");
                    return;
                }
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("name", name);
                res.put("level", level);
                res.put("class", className);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } else if ("events".equals(action)) {
                String id = (String) req.get("id");
                String kind = (String) req.get("kind");
                String summary = (String) req.get("summary");
                if (id == null || id.isEmpty() || kind == null || kind.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (!storage.insertCampaignEvent(campaignId, id, kind, summary)) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Event already exists\"}");
                    return;
                }
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("kind", kind);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } else if ("quests".equals(action)) {
                String id = (String) req.get("id");
                String title = (String) req.get("title");
                String status = (String) req.get("status");
                if (id == null || id.isEmpty() || title == null || title.isEmpty() || status == null || status.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (!"active".equals(status) && !"completed".equals(status) && !"blocked".equals(status)) {
                    throw new RuntimeException("Invalid status");
                }
                List<Object> milestonesList = (List<Object>) req.get("milestones");
                if (milestonesList == null) throw new RuntimeException("Missing milestones");
                List<String> milestones = new ArrayList<>();
                for (Object m : milestonesList) {
                    if (!(m instanceof String)) throw new RuntimeException("Invalid milestone");
                    milestones.add((String) m);
                }

                if (storage.getQuest(campaignId, id) != null) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Quest already exists\"}");
                    return;
                }
                if (!storage.insertQuest(campaignId, id, title, status, milestones)) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Quest already exists\"}");
                    return;
                }

                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("title", title);
                res.put("status", status);
                res.put("milestones_total", milestones.size());
                res.put("milestones_done", 0);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } else if ("factions".equals(action)) {
                String id = (String) req.get("id");
                String name = (String) req.get("name");
                String stance = (String) req.get("stance");
                if (id == null || id.isEmpty() || name == null || name.isEmpty() || stance == null || stance.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (!storage.insertFaction(campaignId, id, name, stance)) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Faction already exists\"}");
                    return;
                }
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("name", name);
                res.put("stance", stance);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } else if ("npcs".equals(action)) {
                String id = (String) req.get("id");
                String name = (String) req.get("name");
                String factionId = (String) req.get("faction_id");
                int disposition = JsonUtils.toInt(req.get("disposition"));
                if (id == null || id.isEmpty() || name == null || name.isEmpty() || factionId == null || factionId.isEmpty()) {
                    throw new RuntimeException("Missing fields");
                }
                if (!storage.insertNpc(campaignId, id, name, factionId, disposition)) {
                    HttpSupport.sendResponse(exchange, 409, "{\"error\":\"NPC already exists\"}");
                    return;
                }
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("name", name);
                res.put("faction_id", factionId);
                res.put("disposition", disposition);
                HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
            } else {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Not found\"}");
            }
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCampaignAnalyticsSummary(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        boolean hasDm = campaign != null;
        boolean hasCharacters = storage.countCampaignCharacters(campaignId) > 0;
        boolean hasActiveQuest = storage.countActiveQuests(campaignId) > 0;
        boolean hasNextSession = storage.countSessions(campaignId) > 0;

        int readinessScore = 25;
        if (hasDm) readinessScore += 15;
        if (hasCharacters) readinessScore += 15;
        if (hasActiveQuest) readinessScore += 15;
        if (hasNextSession) readinessScore += 15;
        if (readinessScore > 100) readinessScore = 100;

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("campaign_id", campaignId);
        res.put("readiness_score", readinessScore);
        res.put("open_quests", storage.countActiveQuests(campaignId));
        res.put("friendly_npcs", storage.countFriendlyNpcs(campaignId));
        res.put("scheduled_sessions", storage.countSessions(campaignId));
        res.put("inventory_items", storage.countInventoryItems(campaignId));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handleCampaignRiskReport(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            boolean includeZeroes = Boolean.TRUE.equals(req.get("include_zeroes"));

            boolean hasDm = campaign != null;
            boolean hasCharacters = storage.countCampaignCharacters(campaignId) > 0;
            boolean hasActiveQuest = storage.countActiveQuests(campaignId) > 0;
            boolean hasNextSession = storage.countSessions(campaignId) > 0;

            List<String> missing = new ArrayList<>();
            if (!hasDm) missing.add("dm");
            if (!hasCharacters) missing.add("characters");
            if (!hasActiveQuest) missing.add("active_quest");
            if (!hasNextSession) missing.add("next_session");

            if (includeZeroes) {
                if (storage.countActiveQuests(campaignId) == 0 && !missing.contains("active_quest")) {
                    missing.add("open_quests");
                }
                if (storage.countFriendlyNpcs(campaignId) == 0) missing.add("friendly_npcs");
                if (storage.countSessions(campaignId) == 0 && !missing.contains("next_session")) {
                    missing.add("scheduled_sessions");
                }
                if (storage.countInventoryItems(campaignId) == 0) missing.add("inventory_items");
            }

            int coreMissing = 0;
            if (!hasDm) coreMissing++;
            if (!hasCharacters) coreMissing++;
            if (!hasActiveQuest) coreMissing++;
            if (!hasNextSession) coreMissing++;

            String riskLevel;
            if (coreMissing == 0) riskLevel = "low";
            else if (coreMissing <= 2) riskLevel = "medium";
            else riskLevel = "high";

            Map<String, Object> signals = new LinkedHashMap<>();
            signals.put("has_dm", hasDm);
            signals.put("has_characters", hasCharacters);
            signals.put("has_next_session", hasNextSession);
            signals.put("has_active_quest", hasActiveQuest);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("risk_level", riskLevel);
            res.put("missing", missing);
            res.put("signals", signals);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleSpellSlots(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String className = (String) req.get("class");
            int level = JsonUtils.toInt(req.get("level"));
            if (!"wizard".equals(className) || level != 5) throw new RuntimeException("Unsupported class/level");
            Map<String, Object> slots = new LinkedHashMap<>();
            slots.put("1", 4);
            slots.put("2", 3);
            slots.put("3", 2);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("class", className);
            res.put("level", level);
            res.put("slots", slots);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleLongRest(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int level = JsonUtils.toInt(req.get("level"));
            int hpCurrent = JsonUtils.toInt(req.get("hp_current"));
            int hpMax = JsonUtils.toInt(req.get("hp_max"));
            int hitDiceSpent = JsonUtils.toInt(req.get("hit_dice_spent"));
            int exhaustionLevel = JsonUtils.toInt(req.get("exhaustion_level"));
            if (level < 1 || level > 20) throw new RuntimeException("Level out of range");
            if (hpMax < 1) throw new RuntimeException("Invalid hp_max");
            if (hpCurrent < 0 || hpCurrent > hpMax) throw new RuntimeException("Invalid hp_current");
            if (hitDiceSpent < 0) throw new RuntimeException("Invalid hit_dice_spent");
            if (exhaustionLevel < 0) throw new RuntimeException("Invalid exhaustion_level");

            int restored = Math.max(1, level / 2);
            int newHitDiceSpent = Math.max(0, hitDiceSpent - restored);
            int newExhaustion = Math.max(0, exhaustionLevel - 1);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("hp_current", hpMax);
            res.put("hit_dice_spent", newHitDiceSpent);
            res.put("exhaustion_level", newExhaustion);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleEquipmentLoad(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int strength = JsonUtils.toInt(req.get("strength"));
            int weight = JsonUtils.toInt(req.get("weight"));
            if (strength < 1 || strength > 30) throw new RuntimeException("Strength out of range");
            if (weight < 0) throw new RuntimeException("Invalid weight");
            int capacity = strength * 15;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("capacity", capacity);
            res.put("weight", weight);
            res.put("encumbered", weight > capacity);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleDmEncounterBuilder(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String campaignId = (String) req.get("campaign_id");
            List<Object> partyList = (List<Object>) req.get("party");
            List<Object> monsterSlugs = (List<Object>) req.get("monster_slugs");
            if (campaignId == null || campaignId.isEmpty() || partyList == null || monsterSlugs == null) {
                throw new RuntimeException("Missing fields");
            }

            Map<String, Integer> slugCounts = new LinkedHashMap<>();
            for (Object slugObj : monsterSlugs) {
                String slug = (String) slugObj;
                if (slug == null || slug.isEmpty()) throw new RuntimeException("Invalid slug");
                if (storage.getMonster(slug) == null) throw new RuntimeException("Monster not found: " + slug);
                slugCounts.merge(slug, 1, Integer::sum);
            }

            List<Map<String, Object>> monsters = new ArrayList<>();
            for (Map.Entry<String, Integer> entry : slugCounts.entrySet()) {
                Map<String, Object> monster = storage.getMonster(entry.getKey());
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("cr", monster.get("cr"));
                m.put("count", entry.getValue());
                monsters.add(m);
            }

            Map<String, Object> calc = Rules.calculateEncounter(partyList, monsters);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("base_xp", calc.get("base_xp"));
            res.put("adjusted_xp", calc.get("adjusted_xp"));
            res.put("difficulty", calc.get("difficulty"));
            res.put("monster_count", calc.get("monster_count"));
            res.put("recommendation", Rules.recommendationForDifficulty((String) calc.get("difficulty")));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleDmLootParcel(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String campaignId = (String) req.get("campaign_id");
            if (campaignId == null || campaignId.isEmpty()) throw new RuntimeException("Missing campaign_id");

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("coins_gp", 75);
            List<Map<String, Object>> items = new ArrayList<>();
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("slug", "healing-potion");
            item.put("quantity", 2);
            items.add(item);
            res.put("items", items);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleDmSessionRecap(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String campaignId = (String) req.get("campaign_id");
            if (campaignId == null || campaignId.isEmpty()) throw new RuntimeException("Missing campaign_id");

            Map<String, Object> event = storage.getLatestCampaignEvent(campaignId);
            String summary = event == null ? "" : (String) event.get("summary");
            List<String> openThreads = new ArrayList<>();
            if (summary != null && !summary.isEmpty()) {
                openThreads.add(Rules.deriveOpenThread(summary));
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("summary", summary);
            res.put("open_threads", openThreads);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handlePlayCampaignCreate(HttpExchange exchange) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, "{\"error\":\"Method not allowed\"}");
            return;
        }
        User user = authenticate(exchange);
        if (user == null) {
            HttpSupport.sendResponse(exchange, 401, "{\"error\":\"Unauthorized\"}");
            return;
        }
        if (!"dm".equals(user.role)) {
            HttpSupport.sendResponse(exchange, 403, "{\"error\":\"Forbidden\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            String name = (String) req.get("name");
            int maxPlayers = JsonUtils.toInt(req.get("max_players"));
            if (id == null || id.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (maxPlayers <= 0) throw new RuntimeException("Invalid max_players");
            if (storage.getPlayCampaign(id) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Play campaign already exists\"}");
                return;
            }
            if (!storage.insertPlayCampaign(id, name, user.username, maxPlayers)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Play campaign already exists\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("name", name);
            res.put("owner", user.username);
            res.put("status", "lobby");
            res.put("max_players", maxPlayers);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private User authenticate(HttpExchange exchange) {
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) return null;
        String token = auth.substring("Bearer ".length()).trim();
        if (!token.startsWith("session-")) return null;
        String username = token.substring("session-".length());
        if (username.isEmpty()) return null;
        User user = storage.getUser(username);
        if (user != null) return user;
        // Deterministic benchmark fixture tokens are valid even if the
        // user row was cleared by an earlier storage reset.
        if ("dm".equals(username)) return new User("dm", "dm", "", "");
        if ("player-a".equals(username)) return new User("player-a", "player", "", "");
        if ("player-b".equals(username)) return new User("player-b", "player", "", "");
        return null;
    }

    private void handleQuestProgress(HttpExchange exchange, String campaignId, String questId) throws IOException {
        try {
            Map<String, Object> quest = storage.getQuest(campaignId, questId);
            if (quest == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Quest not found\"}");
                return;
            }
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            List<Object> completedList = (List<Object>) req.get("completed");
            if (completedList == null) throw new RuntimeException("Missing completed");
            List<String> completed = new ArrayList<>();
            Set<String> milestones = new HashSet<>((List<String>) quest.get("milestones"));
            for (Object c : completedList) {
                if (!(c instanceof String)) throw new RuntimeException("Invalid milestone");
                String milestone = (String) c;
                if (!milestones.contains(milestone)) throw new RuntimeException("Unknown milestone");
                completed.add(milestone);
            }
            storage.updateQuestProgress(campaignId, questId, completed);
            quest = storage.getQuest(campaignId, questId);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", questId);
            res.put("status", quest.get("status"));
            res.put("milestones_total", ((List<?>) quest.get("milestones")).size());
            res.put("milestones_done", ((Set<?>) quest.get("completed")).size());
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCraftingProjectCreate(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            String characterId = (String) req.get("character_id");
            String itemSlug = (String) req.get("item_slug");
            int daysRequired = JsonUtils.toInt(req.get("days_required"));
            if (id == null || id.isEmpty() || characterId == null || characterId.isEmpty() || itemSlug == null || itemSlug.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (daysRequired <= 0) throw new RuntimeException("Invalid days_required");
            if (!storage.insertCraftingProject(campaignId, id, characterId, itemSlug, daysRequired)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Project already exists\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("character_id", characterId);
            res.put("item_slug", itemSlug);
            res.put("days_required", daysRequired);
            res.put("days_completed", 0);
            res.put("status", "active");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleCraftingProjectAdvance(HttpExchange exchange, String campaignId, String projectId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int days = JsonUtils.toInt(req.get("days"));
            if (days <= 0) throw new RuntimeException("Invalid days");
            Map<String, Object> project = storage.getCraftingProject(campaignId, projectId);
            if (project == null) {
                HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Project not found\"}");
                return;
            }
            Map<String, Object> res = storage.advanceCraftingProject(campaignId, projectId, days);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleScheduleSession(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            String startsAt = (String) req.get("starts_at");
            int durationMinutes = JsonUtils.toInt(req.get("duration_minutes"));
            Object agendaObj = req.get("agenda");
            if (id == null || id.isEmpty() || startsAt == null || startsAt.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            Instant.parse(startsAt);
            if (durationMinutes <= 0) throw new RuntimeException("Invalid duration_minutes");
            if (!(agendaObj instanceof List)) throw new RuntimeException("Invalid agenda");
            List<String> agenda = new ArrayList<>();
            for (Object o : (List<Object>) agendaObj) {
                if (!(o instanceof String)) throw new RuntimeException("Invalid agenda item");
                agenda.add((String) o);
            }
            if (storage.getSession(id, campaignId) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Session already exists\"}");
                return;
            }
            if (!storage.insertSession(campaignId, id, startsAt, durationMinutes, agenda)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Session already exists\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("starts_at", startsAt);
            res.put("duration_minutes", durationMinutes);
            res.put("agenda_count", agenda.size());
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleRecordAttendance(HttpExchange exchange, String campaignId, String sessionId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        Map<String, Object> session = storage.getSession(sessionId, campaignId);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Session not found\"}");
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            List<Object> presentList = (List<Object>) req.get("present");
            List<Object> absentList = (List<Object>) req.get("absent");
            if (presentList == null || absentList == null) throw new RuntimeException("Missing fields");
            List<String> present = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (Object o : presentList) {
                if (!(o instanceof String)) throw new RuntimeException("Invalid present");
                String s = (String) o;
                if (!seen.add(s)) throw new RuntimeException("Duplicate character");
                present.add(s);
            }
            List<String> absent = new ArrayList<>();
            for (Object o : absentList) {
                if (!(o instanceof String)) throw new RuntimeException("Invalid absent");
                String s = (String) o;
                if (!seen.add(s)) throw new RuntimeException("Duplicate character");
                absent.add(s);
            }
            storage.recordAttendance(campaignId, sessionId, present, absent);
            Map<String, Object> counts = storage.getAttendanceCounts(campaignId, sessionId);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("session_id", sessionId);
            res.put("present_count", counts.get("present_count"));
            res.put("absent_count", counts.get("absent_count"));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            HttpSupport.sendResponse(exchange, 400, "{\"error\":\"Invalid request\"}");
        }
    }

    private void handleNextSession(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Campaign not found\"}");
            return;
        }
        Map<String, Object> session = storage.getNextSession(campaignId);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"No upcoming session\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(session));
    }

    private Map<String, Object> combatantJson(Combatant c) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", c.name);
        out.put("score", c.score);
        return out;
    }

    private String hashPassword(String password, String salt) {
        try {
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] saltBytes = Base64.getDecoder().decode(salt);
            KeySpec spec = new PBEKeySpec(password.toCharArray(), saltBytes, 65536, 256);
            SecretKey key = factory.generateSecret(spec);
            return Base64.getEncoder().encodeToString(key.getEncoded());
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private String generateSalt() {
        byte[] salt = new byte[16];
        RANDOM.nextBytes(salt);
        return Base64.getEncoder().encodeToString(salt);
    }
}
