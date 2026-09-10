package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import dnd.game.Rules;
import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * DM helper endpoints: encounter builder, loot parcel, and session recap.
 */
public final class DmToolHandler extends BaseHandler {
    public DmToolHandler(Storage storage) {
        super(storage);
    }

    public void handleDmEncounterBuilder(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleDmLootParcel(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleDmSessionRecap(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }
}
