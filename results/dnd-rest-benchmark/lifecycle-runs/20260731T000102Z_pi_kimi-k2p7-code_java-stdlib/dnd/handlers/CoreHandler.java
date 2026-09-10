package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import dnd.game.Rules;
import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.server.ServiceState;
import dnd.storage.Storage;

/**
 * Stateless handlers for core dice, checks, encounter math, initiative,
 * and character-rule endpoints.
 */
public final class CoreHandler extends BaseHandler {
    private static final Pattern DICE_PATTERN = Pattern.compile("^(\\d+)d(\\d+)([+-]\\d+)?$");

    private static final String API_SCHEMA = "{\"version\":\"2026-07-29\",\"endpoints\":[{\"method\":\"GET\",\"path\":\"/v1/play/campaigns/{id}/rng-ledger\",\"auth\":\"member\"},{\"method\":\"GET\",\"path\":\"/v1/schema\",\"auth\":\"public\"},{\"method\":\"POST\",\"path\":\"/v1/play/campaigns\",\"auth\":\"dm\"},{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/fixture-seeds\",\"auth\":\"dm\"},{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/members\",\"auth\":\"member\"},{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/moderation/reports\",\"auth\":\"member\"},{\"method\":\"POST\",\"path\":\"/v1/play/campaigns/{id}/rng-rolls\",\"auth\":\"member\"},{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution\",\"auth\":\"dm\"},{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/rng-seed\",\"auth\":\"dm\"},{\"method\":\"PUT\",\"path\":\"/v1/play/campaigns/{id}/safety-boundaries\",\"auth\":\"dm\"}]}";

    public CoreHandler(Storage storage) {
        super(storage);
    }

    public void handleSchema(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        HttpSupport.sendResponse(exchange, 200, API_SCHEMA);
    }

    public void handleHealth(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        HttpSupport.sendResponse(exchange, 200, "{\"ok\":true}");
    }

    public void handleHealthz(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        HttpSupport.sendResponse(exchange, 200, "{\"status\":\"ok\"}");
    }

    public void handleReadyz(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        if (ServiceState.isMaintenance()) {
            HttpSupport.sendResponse(exchange, 503, "{\"status\":\"maintenance\",\"schema_version\":2}");
        } else {
            HttpSupport.sendResponse(exchange, 200, "{\"status\":\"ready\",\"schema_version\":2}");
        }
    }

    public void handleDiceStats(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleAbilityCheck(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleAdjustedXp(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleInitiative(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleAbilityModifier(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleProficiency(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleDerivedStats(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }
}
