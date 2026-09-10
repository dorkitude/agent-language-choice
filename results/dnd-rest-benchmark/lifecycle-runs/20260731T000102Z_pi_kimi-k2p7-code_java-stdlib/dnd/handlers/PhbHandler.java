package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Player's Handbook rule helpers: spell slots, long rests, and equipment load.
 */
public final class PhbHandler extends BaseHandler {
    public PhbHandler(Storage storage) {
        super(storage);
    }

    public void handleSpellSlots(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleLongRest(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleEquipmentLoad(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }
}
