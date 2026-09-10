package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import dnd.json.JsonUtils;
import dnd.model.Combatant;
import dnd.model.CombatSession;
import dnd.model.Condition;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Handlers for persisted combat sessions: creation, conditions, and turns.
 */
public final class CombatHandler extends BaseHandler {
    public CombatHandler(Storage storage) {
        super(storage);
    }

    public void handleCombatSessionCreate(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
            badRequest(exchange);
        }
    }

    public void handleCombatSessionAction(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/combat/sessions/";
        if (!path.startsWith(prefix)) {
            notFound(exchange);
            return;
        }
        String rest = path.substring(prefix.length());
        int slash = rest.indexOf('/');
        if (slash < 0) {
            notFound(exchange);
            return;
        }
        String id = rest.substring(0, slash);
        String action = rest.substring(slash + 1);
        CombatSession session = storage.getCombatSession(id);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_SESSION_NOT_FOUND);
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
                notFound(exchange);
            }
        } catch (Exception e) {
            badRequest(exchange);
        }
    }

    private Map<String, Object> combatantJson(Combatant c) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", c.name);
        out.put("score", c.score);
        return out;
    }
}
