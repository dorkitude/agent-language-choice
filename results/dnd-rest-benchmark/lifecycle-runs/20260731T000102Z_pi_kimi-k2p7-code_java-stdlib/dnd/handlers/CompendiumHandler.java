package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Monster and item compendium CRUD handlers.
 */
public final class CompendiumHandler extends BaseHandler {
    public CompendiumHandler(Storage storage) {
        super(storage);
    }

    public void handleMonsterCreate(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
                HttpSupport.sendResponse(exchange, 409, ERROR_MONSTER_EXISTS);
                return;
            }
            if (!storage.insertMonster(slug, name, cr, armorClass, hitPoints, tags)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MONSTER_EXISTS);
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
            badRequest(exchange);
        }
    }

    public void handleMonsterRead(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/compendium/monsters/";
        String slug = path.substring(prefix.length());
        if (slug.isEmpty()) {
            notFound(exchange);
            return;
        }
        Map<String, Object> monster = storage.getMonster(slug);
        if (monster == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Monster not found\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(monster));
    }

    public void handleItemCreate(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
                HttpSupport.sendResponse(exchange, 409, ERROR_ITEM_EXISTS);
                return;
            }
            if (!storage.insertItem(slug, name, type, rarity, costGp)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_ITEM_EXISTS);
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
            badRequest(exchange);
        }
    }

    public void handleItemRead(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/compendium/items/";
        String slug = path.substring(prefix.length());
        if (slug.isEmpty()) {
            notFound(exchange);
            return;
        }
        Map<String, Object> item = storage.getItem(slug);
        if (item == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"Item not found\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(item));
    }
}
