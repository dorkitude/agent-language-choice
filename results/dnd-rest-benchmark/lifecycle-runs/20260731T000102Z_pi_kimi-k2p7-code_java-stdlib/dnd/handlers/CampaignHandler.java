package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Campaign-management handlers: creation, characters, events, quests,
 * factions, NPCs, inventory, equipment, crafting, sessions, analytics,
 * and export.
 */
public final class CampaignHandler extends BaseHandler {
    public CampaignHandler(Storage storage) {
        super(storage);
    }

    public void handleCampaignCreate(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
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
                HttpSupport.sendResponse(exchange, 409, ERROR_CAMPAIGN_EXISTS);
                return;
            }
            if (!storage.insertCampaign(id, name, dm)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CAMPAIGN_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("name", name);
            res.put("dm", dm);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    public void handleCampaignAction(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/campaigns/";
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
        String campaignId = rest.substring(0, slash);
        String action = rest.substring(slash + 1);

        if ("GET".equals(exchange.getRequestMethod()) && "state".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
            if (!requireMethod(exchange, "GET")) return;
            handleCampaignAnalyticsSummary(exchange, campaignId);
            return;
        }

        if ("analytics/risk-report".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handleCampaignRiskReport(exchange, campaignId);
            return;
        }

        if ("sessions".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handleScheduleSession(exchange, campaignId);
            return;
        }

        if (action.startsWith("sessions/")) {
            String sessionRest = action.substring("sessions/".length());
            int sessionSlash = sessionRest.indexOf('/');
            if (sessionSlash < 0) {
                if ("next".equals(sessionRest)) {
                    if (!requireMethod(exchange, "GET")) return;
                    handleNextSession(exchange, campaignId);
                    return;
                }
                notFound(exchange);
                return;
            }
            String sessionId = sessionRest.substring(0, sessionSlash);
            String sessionAction = sessionRest.substring(sessionSlash + 1);
            if ("attendance".equals(sessionAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handleRecordAttendance(exchange, campaignId, sessionId);
                return;
            }
            notFound(exchange);
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && "downtime/crafting".equals(action)) {
            handleCraftingProjectCreate(exchange, campaignId);
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && action.startsWith("downtime/crafting/") && action.endsWith("/advance")) {
            String projectId = action.substring("downtime/crafting/".length(), action.length() - "/advance".length());
            if (projectId.isEmpty() || projectId.indexOf('/') >= 0) {
                notFound(exchange);
                return;
            }
            handleCraftingProjectAdvance(exchange, campaignId, projectId);
            return;
        }

        if ("GET".equals(exchange.getRequestMethod()) && "inventory/summary".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                    if (!requireMethod(exchange, "GET")) return;
                    Map<String, Object> campaign = storage.getCampaign(campaignId);
                    if (campaign == null) {
                        HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
                        return;
                    }
                    HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(storage.getQuestSummary(campaignId)));
                    return;
                }
                notFound(exchange);
                return;
            }
            String questId = questRest.substring(0, questSlash);
            String questAction = questRest.substring(questSlash + 1);
            if ("progress".equals(questAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handleQuestProgress(exchange, campaignId, questId);
                return;
            }
            notFound(exchange);
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && "inventory".equals(action)) {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                badRequest(exchange);
            }
            return;
        }

        if ("POST".equals(exchange.getRequestMethod()) && action.startsWith("characters/") && action.endsWith("/equipment")) {
            String charsPrefix = "characters/";
            String equipSuffix = "/equipment";
            if (action.length() <= charsPrefix.length() + equipSuffix.length()) {
                notFound(exchange);
                return;
            }
            String characterId = action.substring(charsPrefix.length(), action.length() - equipSuffix.length());
            if (characterId.isEmpty() || characterId.indexOf('/') >= 0) {
                notFound(exchange);
                return;
            }
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                badRequest(exchange);
            }
            return;
        }

        if (!requireMethod(exchange, "POST")) return;
        try {
            Map<String, Object> campaign = storage.getCampaign(campaignId);
            if (campaign == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                    HttpSupport.sendResponse(exchange, 409, ERROR_CHARACTER_EXISTS);
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
                    HttpSupport.sendResponse(exchange, 409, ERROR_QUEST_EXISTS);
                    return;
                }
                if (!storage.insertQuest(campaignId, id, title, status, milestones)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_QUEST_EXISTS);
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
                notFound(exchange);
            }
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handleCampaignAnalyticsSummary(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
            badRequest(exchange);
        }
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
            badRequest(exchange);
        }
    }

    private void handleCraftingProjectCreate(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
            badRequest(exchange);
        }
    }

    private void handleCraftingProjectAdvance(HttpExchange exchange, String campaignId, String projectId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
            badRequest(exchange);
        }
    }

    private void handleScheduleSession(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
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
                HttpSupport.sendResponse(exchange, 409, ERROR_SESSION_EXISTS);
                return;
            }
            if (!storage.insertSession(campaignId, id, startsAt, durationMinutes, agenda)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SESSION_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("starts_at", startsAt);
            res.put("duration_minutes", durationMinutes);
            res.put("agenda_count", agenda.size());
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handleRecordAttendance(HttpExchange exchange, String campaignId, String sessionId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> session = storage.getSession(sessionId, campaignId);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_SESSION_NOT_FOUND);
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
            badRequest(exchange);
        }
    }

    private void handleNextSession(HttpExchange exchange, String campaignId) throws IOException {
        Map<String, Object> campaign = storage.getCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> session = storage.getNextSession(campaignId);
        if (session == null) {
            HttpSupport.sendResponse(exchange, 404, "{\"error\":\"No upcoming session\"}");
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(session));
    }
}
