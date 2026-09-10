package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import dnd.game.Rules;
import dnd.json.JsonUtils;
import dnd.model.User;
import dnd.server.HttpSupport;
import dnd.server.ServiceState;
import dnd.storage.Storage;

/**
 * Play-surface campaign handlers: creation, membership, turn queue,
 * narration, actions, resolutions, nudges, documents, and role-filtered views.
 */
public final class PlayCampaignHandler extends BaseHandler {
    public PlayCampaignHandler(Storage storage) {
        super(storage);
    }

    public void handlePlayCampaignCreate(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        if (!"dm".equals(user.role)) {
            forbidden(exchange);
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
                HttpSupport.sendResponse(exchange, 409, ERROR_PLAY_CAMPAIGN_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaign(id, name, user.username, maxPlayers)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_PLAY_CAMPAIGN_EXISTS);
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
            badRequest(exchange);
        }
    }

    public void handlePlayCampaignAction(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String prefix = "/v1/play/campaigns/";
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
        if ("members".equals(action)) {
            handlePlayCampaignJoin(exchange, campaignId);
            return;
        }
        if ("start".equals(action)) {
            handlePlayCampaignStart(exchange, campaignId);
            return;
        }
        if ("spectators".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignSpectatorsCreate(exchange, campaignId);
            return;
        }
        if ("spectator-view".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignSpectatorView(exchange, campaignId);
            return;
        }
        if ("feed-events".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignFeedEventCreate(exchange, campaignId);
            return;
        }
        if ("event-feed".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignEventFeedRead(exchange, campaignId);
            return;
        }
        if ("onboarding".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignOnboarding(exchange, campaignId);
            return;
        }
        if ("narrations".equals(action)) {
            handlePlayCampaignNarration(exchange, campaignId);
            return;
        }
        if ("messages".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignMessageCreate(exchange, campaignId);
            return;
        }
        if ("actions".equals(action)) {
            handlePlayCampaignActionSubmit(exchange, campaignId);
            return;
        }
        if ("resolutions".equals(action)) {
            handlePlayCampaignResolution(exchange, campaignId);
            return;
        }
        if ("turn".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignTurn(exchange, campaignId);
            return;
        }
        if (action.startsWith("turn/")) {
            String turnAction = action.substring("turn/".length());
            if ("nudge".equals(turnAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignNudge(exchange, campaignId);
                return;
            }
            if ("travel".equals(turnAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignTravelTurn(exchange, campaignId);
                return;
            }
            if ("rest".equals(turnAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignRestTurn(exchange, campaignId);
                return;
            }
        }
        if ("my-turn".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignMyTurn(exchange, campaignId);
            return;
        }
        if ("gm/status".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignGmStatus(exchange, campaignId);
            return;
        }
        if ("document".equals(action)) {
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignDocumentGet(exchange, campaignId);
                return;
            }
            if ("PUT".equals(exchange.getRequestMethod())) {
                handlePlayCampaignDocumentPut(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("scenes".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignSceneCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("scenes/")) {
            String scenesRest = action.substring("scenes/".length());
            if ("current".equals(scenesRest)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignSceneCurrent(exchange, campaignId);
                return;
            }
            int sceneSlash = scenesRest.indexOf('/');
            if (sceneSlash < 0) {
                notFound(exchange);
                return;
            }
            String sceneId = scenesRest.substring(0, sceneSlash);
            String sceneAction = scenesRest.substring(sceneSlash + 1);
            if ("enter".equals(sceneAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignSceneEnter(exchange, campaignId, sceneId);
                return;
            }
            if ("close".equals(sceneAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignSceneClose(exchange, campaignId, sceneId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("locations".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignLocationCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("locations/")) {
            String locRest = action.substring("locations/".length());
            int locSlash = locRest.indexOf('/');
            if (locSlash < 0) {
                notFound(exchange);
                return;
            }
            String locId = locRest.substring(0, locSlash);
            String locAction = locRest.substring(locSlash + 1);
            if ("connections".equals(locAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignConnectionCreate(exchange, campaignId, locId);
                return;
            }
            if ("travel".equals(locAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignTravel(exchange, campaignId, locId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("encounters".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignEncounterCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("encounters/")) {
            String encRest = action.substring("encounters/".length());
            int encSlash = encRest.indexOf('/');
            if (encSlash < 0) {
                notFound(exchange);
                return;
            }
            String encounterId = encRest.substring(0, encSlash);
            String monsterAction = encRest.substring(encSlash + 1);
            if ("monsters".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterMonsterCreate(exchange, campaignId, encounterId);
                return;
            }
            if (monsterAction.startsWith("monsters/")) {
                String monsterId = monsterAction.substring("monsters/".length());
                if (!requireMethod(exchange, "DELETE")) return;
                handlePlayCampaignEncounterMonsterDelete(exchange, campaignId, encounterId, monsterId);
                return;
            }
            if ("combatants".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterCombatantCreate(exchange, campaignId, encounterId);
                return;
            }
            if (monsterAction.startsWith("combatants/")) {
                String member = monsterAction.substring("combatants/".length());
                if (!requireMethod(exchange, "DELETE")) return;
                handlePlayCampaignEncounterCombatantDelete(exchange, campaignId, encounterId, member);
                return;
            }
            if ("turn".equals(monsterAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignEncounterTurn(exchange, campaignId, encounterId);
                return;
            }
            if ("turn/advance".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterTurnAdvance(exchange, campaignId, encounterId);
                return;
            }
            if ("turn/delay".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterDelay(exchange, campaignId, encounterId);
                return;
            }
            if ("turn/ready".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterReady(exchange, campaignId, encounterId);
                return;
            }
            if ("actions".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterAction(exchange, campaignId, encounterId);
                return;
            }
            if ("damage".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterDamage(exchange, campaignId, encounterId);
                return;
            }
            if ("heal".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterHeal(exchange, campaignId, encounterId);
                return;
            }
            if ("conditions".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterCondition(exchange, campaignId, encounterId);
                return;
            }
            if ("status".equals(monsterAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignEncounterStatus(exchange, campaignId, encounterId);
                return;
            }
            if ("rewards".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterRewards(exchange, campaignId, encounterId);
                return;
            }
            if ("close".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterClose(exchange, campaignId, encounterId);
                return;
            }
            if ("end".equals(monsterAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignEncounterEnd(exchange, campaignId, encounterId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("loot".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignLootCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("loot/")) {
            String lootRest = action.substring("loot/".length());
            int lootSlash = lootRest.indexOf('/');
            if (lootSlash < 0) {
                String lootId = lootRest;
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignLootGet(exchange, campaignId, lootId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            String lootId = lootRest.substring(0, lootSlash);
            String lootAction = lootRest.substring(lootSlash + 1);
            if ("votes".equals(lootAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignLootVote(exchange, campaignId, lootId);
                return;
            }
            if ("assign".equals(lootAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignLootAssign(exchange, campaignId, lootId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("downtime/activities".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignDowntimeActivityCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("characters/")) {
            String charsRest = action.substring("characters/".length());
            int charSlash = charsRest.indexOf('/');
            if (charSlash < 0) {
                notFound(exchange);
                return;
            }
            String charId = charsRest.substring(0, charSlash);
            String charAction = charsRest.substring(charSlash + 1);
            if ("sheet".equals(charAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignCharacterSheetGet(exchange, campaignId, charId);
                return;
            }
            if (charAction.startsWith("downtime/")) {
                String downtimeRest = charAction.substring("downtime/".length());
                if ("allocations".equals(downtimeRest)) {
                    if (!requireMethod(exchange, "POST")) return;
                    handlePlayCampaignDowntimeAllocationCreate(exchange, campaignId, charId);
                    return;
                }
                if (downtimeRest.startsWith("allocations/")) {
                    String allocRest = downtimeRest.substring("allocations/".length());
                    int allocSlash = allocRest.indexOf('/');
                    if (allocSlash < 0) {
                        String activityId = allocRest;
                        if ("GET".equals(exchange.getRequestMethod())) {
                            handlePlayCampaignDowntimeAllocationGet(exchange, campaignId, charId, activityId);
                            return;
                        }
                        HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                        return;
                    }
                    String activityId = allocRest.substring(0, allocSlash);
                    String allocAction = allocRest.substring(allocSlash + 1);
                    if ("progress".equals(allocAction)) {
                        if (!requireMethod(exchange, "POST")) return;
                        handlePlayCampaignDowntimeAllocationProgress(exchange, campaignId, charId, activityId);
                        return;
                    }
                    notFound(exchange);
                    return;
                }
                notFound(exchange);
                return;
            }
            if ("owner".equals(charAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignCharacterOwnerGet(exchange, campaignId, charId);
                return;
            }
            if ("currency".equals(charAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterCurrencyGet(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if ("currency/transfers".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterCurrencyTransfer(exchange, campaignId, charId);
                return;
            }
            if ("claim".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterOwnerClaim(exchange, campaignId, charId);
                return;
            }
            if ("transfer".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterOwnerTransfer(exchange, campaignId, charId);
                return;
            }
            if ("damage".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterDamage(exchange, campaignId, charId);
                return;
            }
            if ("death-saves".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterDeathSave(exchange, campaignId, charId);
                return;
            }
            if ("status".equals(charAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignCharacterStatus(exchange, campaignId, charId);
                return;
            }
            if ("build".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterBuild(exchange, campaignId, charId);
                return;
            }
            if ("level-up".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterLevelUp(exchange, campaignId, charId);
                return;
            }
            if ("skill-check".equals(charAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignCharacterSkillCheck(exchange, campaignId, charId);
                return;
            }
            if ("spells".equals(charAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterSpellsGet(exchange, campaignId, charId);
                    return;
                }
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterSpellsCreate(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if ("prepared-spells".equals(charAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterPreparedSpellsGet(exchange, campaignId, charId);
                    return;
                }
                if ("PUT".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterPreparedSpellsPut(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if ("casts".equals(charAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterCastsGet(exchange, campaignId, charId);
                    return;
                }
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterCastsCreate(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if ("concentration".equals(charAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterConcentrationGet(exchange, campaignId, charId);
                    return;
                }
                if ("PUT".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterConcentrationPut(exchange, campaignId, charId);
                    return;
                }
                if ("DELETE".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterConcentrationDelete(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if (charAction.startsWith("concentration/")) {
                String concentrationAction = charAction.substring("concentration/".length());
                if ("advance-turn".equals(concentrationAction)) {
                    if ("POST".equals(exchange.getRequestMethod())) {
                        handlePlayCampaignCharacterConcentrationAdvance(exchange, campaignId, charId);
                        return;
                    }
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if ("inventory/items".equals(charAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterInventoryAdd(exchange, campaignId, charId);
                    return;
                }
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignCharacterInventoryGet(exchange, campaignId, charId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if (charAction.startsWith("inventory/items/")) {
                String itemRest = charAction.substring("inventory/items/".length());
                int itemSlash = itemRest.indexOf('/');
                if (itemSlash < 0) {
                    String itemId = itemRest;
                    if (!requireMethod(exchange, "DELETE")) return;
                    handlePlayCampaignCharacterInventoryDelete(exchange, campaignId, charId, itemId);
                    return;
                }
                String itemId = itemRest.substring(0, itemSlash);
                String itemAction = itemRest.substring(itemSlash + 1);
                if ("consume".equals(itemAction)) {
                    if (!requireMethod(exchange, "POST")) return;
                    handlePlayCampaignCharacterInventoryConsume(exchange, campaignId, charId, itemId);
                    return;
                }
                notFound(exchange);
                return;
            }
            if (charAction.startsWith("equipment/")) {
                String equipRest = charAction.substring("equipment/".length());
                int equipSlash = equipRest.indexOf('/');
                if (equipSlash < 0) {
                    String slot = equipRest;
                    if ("PUT".equals(exchange.getRequestMethod())) {
                        handlePlayCampaignCharacterEquip(exchange, campaignId, charId, slot);
                        return;
                    }
                    if ("GET".equals(exchange.getRequestMethod())) {
                        handlePlayCampaignCharacterEquipmentGet(exchange, campaignId, charId, slot);
                        return;
                    }
                    HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                    return;
                }
                String slot = equipRest.substring(0, equipSlash);
                String equipAction = equipRest.substring(equipSlash + 1);
                if ("attune".equals(equipAction)) {
                    if (!requireMethod(exchange, "POST")) return;
                    handlePlayCampaignCharacterEquipmentAttune(exchange, campaignId, charId, slot);
                    return;
                }
                notFound(exchange);
                return;
            }
            if ("rewards".equals(charAction)) {
                if (!requireMethod(exchange, "GET")) return;
                handlePlayCampaignCharacterRewardsGet(exchange, campaignId, charId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("npcs".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignNpcCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("npcs/")) {
            String npcRest = action.substring("npcs/".length());
            int npcSlash = npcRest.indexOf('/');
            if (npcSlash < 0) {
                String npcId = npcRest;
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignNpcGet(exchange, campaignId, npcId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            String npcId = npcRest.substring(0, npcSlash);
            String npcAction = npcRest.substring(npcSlash + 1);
            if ("agenda".equals(npcAction)) {
                if (!requireMethod(exchange, "PUT")) return;
                handlePlayCampaignNpcUpdateAgenda(exchange, campaignId, npcId);
                return;
            }
            if ("dialogue".equals(npcAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignNpcDialogueCreate(exchange, campaignId, npcId);
                    return;
                }
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignNpcDialogueGet(exchange, campaignId, npcId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("factions".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignFactionCreate(exchange, campaignId);
            return;
        }
        if (action.startsWith("factions/")) {
            String factionRest = action.substring("factions/".length());
            int factionSlash = factionRest.indexOf('/');
            if (factionSlash < 0) {
                notFound(exchange);
                return;
            }
            String factionId = factionRest.substring(0, factionSlash);
            String factionAction = factionRest.substring(factionSlash + 1);
            if ("reputation".equals(factionAction)) {
                if ("GET".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignFactionReputationGet(exchange, campaignId, factionId);
                    return;
                }
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignFactionReputationPost(exchange, campaignId, factionId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("relationships".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRelationshipCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRelationshipList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("relationships/")) {
            String relRest = action.substring("relationships/".length());
            String[] relParts = relRest.split("/");
            if (relParts.length != 3) {
                notFound(exchange);
                return;
            }
            String sourceId = relParts[0];
            String targetId = relParts[1];
            String kind = relParts[2];
            if ("PUT".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRelationshipUpdate(exchange, campaignId, sourceId, targetId, kind);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("clues".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignClueCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignClueList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("quests".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignQuestCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignQuestList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("quests/")) {
            String questRest = action.substring("quests/".length());
            int questSlash = questRest.indexOf('/');
            if (questSlash < 0) {
                notFound(exchange);
                return;
            }
            String questId = questRest.substring(0, questSlash);
            String questAction = questRest.substring(questSlash + 1);
            if ("state".equals(questAction)) {
                if (!requireMethod(exchange, "PUT")) return;
                handlePlayCampaignQuestStateUpdate(exchange, campaignId, questId);
                return;
            }
            if ("rewards".equals(questAction)) {
                if (!requireMethod(exchange, "PUT")) return;
                handlePlayCampaignQuestRewardsConfigure(exchange, campaignId, questId);
                return;
            }
            if ("rewards/award".equals(questAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignQuestRewardsAward(exchange, campaignId, questId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("world-events".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignWorldEventCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignWorldEventList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("world-events/")) {
            String eventsRest = action.substring("world-events/".length());
            int eventSlash = eventsRest.indexOf('/');
            if (eventSlash < 0) {
                notFound(exchange);
                return;
            }
            String eventId = eventsRest.substring(0, eventSlash);
            String eventAction = eventsRest.substring(eventSlash + 1);
            if ("resolve".equals(eventAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignWorldEventResolve(exchange, campaignId, eventId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("calendar".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignCalendarInit(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignCalendarGet(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("calendar/advance".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignCalendarAdvance(exchange, campaignId);
            return;
        }
        if ("settlements".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSettlementCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSettlementList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("settlements/")) {
            String settlementRest = action.substring("settlements/".length());
            int settlementSlash = settlementRest.indexOf('/');
            if (settlementSlash < 0) {
                String settlementId = settlementRest;
                if ("PUT".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignSettlementUpdate(exchange, campaignId, settlementId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            String settlementId = settlementRest.substring(0, settlementSlash);
            String settlementAction = settlementRest.substring(settlementSlash + 1);
            if ("discover".equals(settlementAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignSettlementDiscover(exchange, campaignId, settlementId);
                return;
            }
            if ("shops".equals(settlementAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignShopCreate(exchange, campaignId, settlementId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            if (settlementAction.startsWith("shops/")) {
                String shopsRest = settlementAction.substring("shops/".length());
                int shopSlash = shopsRest.indexOf('/');
                if (shopSlash < 0) {
                    String shopId = shopsRest;
                    if ("GET".equals(exchange.getRequestMethod())) {
                        handlePlayCampaignShopGet(exchange, campaignId, settlementId, shopId);
                        return;
                    }
                    HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                    return;
                }
                String shopId = shopsRest.substring(0, shopSlash);
                String shopAction = shopsRest.substring(shopSlash + 1);
                if ("buy".equals(shopAction)) {
                    if (!requireMethod(exchange, "POST")) return;
                    handlePlayCampaignShopBuy(exchange, campaignId, settlementId, shopId);
                    return;
                }
                if ("sell".equals(shopAction)) {
                    if (!requireMethod(exchange, "POST")) return;
                    handlePlayCampaignShopSell(exchange, campaignId, settlementId, shopId);
                    return;
                }
                notFound(exchange);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("recipes".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRecipeCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRecipeList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("recipes/")) {
            String recipeRest = action.substring("recipes/".length());
            int recipeSlash = recipeRest.indexOf('/');
            if (recipeSlash < 0) {
                notFound(exchange);
                return;
            }
            String recipeId = recipeRest.substring(0, recipeSlash);
            String recipeAction = recipeRest.substring(recipeSlash + 1);
            if ("craft".equals(recipeAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignRecipeCraft(exchange, campaignId, recipeId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("session-zero".equals(action)) {
            if ("PUT".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSessionZeroPut(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSessionZeroGet(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("content".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignContentCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignContentList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("content/")) {
            String contentRest = action.substring("content/".length());
            int contentSlash = contentRest.indexOf('/');
            if (contentSlash < 0) {
                notFound(exchange);
                return;
            }
            String contentId = contentRest.substring(0, contentSlash);
            String contentAction = contentRest.substring(contentSlash + 1);
            if ("tags".equals(contentAction)) {
                if ("PUT".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignContentTagsPut(exchange, campaignId, contentId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("notes".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignNotesCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignNotesList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("notes/")) {
            String noteId = action.substring("notes/".length());
            if (noteId.isEmpty() || noteId.indexOf('/') >= 0) {
                notFound(exchange);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignNoteGet(exchange, campaignId, noteId);
                return;
            }
            if ("PUT".equals(exchange.getRequestMethod())) {
                handlePlayCampaignNotePut(exchange, campaignId, noteId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("whispers".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignWhispersCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignWhispersList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("invitations".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignInvitationCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignInvitationList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("invitations/")) {
            String invRest = action.substring("invitations/".length());
            int invSlash = invRest.indexOf('/');
            if (invSlash < 0) {
                notFound(exchange);
                return;
            }
            String invitationId = invRest.substring(0, invSlash);
            String invAction = invRest.substring(invSlash + 1);
            if ("accept".equals(invAction)) {
                if ("POST".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignInvitationAccept(exchange, campaignId, invitationId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("delegations".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignDelegationCreate(exchange, campaignId);
            return;
        }
        if ("delegations/audit".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignDelegationAudit(exchange, campaignId);
            return;
        }
        if (action.startsWith("delegations/")) {
            String delegateUsername = action.substring("delegations/".length());
            if (delegateUsername.isEmpty() || delegateUsername.indexOf('/') >= 0) {
                notFound(exchange);
                return;
            }
            if (!requireMethod(exchange, "DELETE")) return;
            handlePlayCampaignDelegationRevoke(exchange, campaignId, delegateUsername);
            return;
        }
        if ("audit-events".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignAuditEventCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignAuditEventList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("projection-events".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignProjectionEventCreate(exchange, campaignId);
            return;
        }
        if ("projection".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignProjectionGet(exchange, campaignId);
            return;
        }
        if ("projection/rebuild".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignProjectionRebuild(exchange, campaignId);
            return;
        }
        if ("idempotent-events".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignIdempotentEventCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignIdempotentEventList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("safe-turns".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSafeTurnSubmit(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSafeTurnList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("transactional-transfers".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignTransactionalTransferCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignTransactionalTransferList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("exports".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignExportCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignExportList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("exports/")) {
            String versionStr = action.substring("exports/".length());
            if (versionStr.isEmpty() || versionStr.indexOf('/') >= 0) {
                notFound(exchange);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                try {
                    int version = Integer.parseInt(versionStr);
                    if (version < 1) {
                        notFound(exchange);
                        return;
                    }
                    handlePlayCampaignExportGet(exchange, campaignId, version);
                    return;
                } catch (NumberFormatException e) {
                    notFound(exchange);
                    return;
                }
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("imports".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignImportCreate(exchange, campaignId);
            return;
        }
        if ("import-state".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignImportStateGet(exchange, campaignId);
            return;
        }
        if ("migrations".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignMigrationCreate(exchange, campaignId);
            return;
        }
        if ("migration-state".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignMigrationStateGet(exchange, campaignId);
            return;
        }
        if ("search-records".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSearchRecordCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSearchRecordList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("rate-events".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRateEventCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignRateEventList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("metrics".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignMetricsGet(exchange, campaignId);
            return;
        }
        if ("service-mode".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignServiceMode(exchange, campaignId);
            return;
        }
        if ("backups".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignBackupCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignBackupList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("backups/")) {
            String backupRest = action.substring("backups/".length());
            int backupSlash = backupRest.indexOf('/');
            if (backupSlash < 0) {
                notFound(exchange);
                return;
            }
            String backupId = backupRest.substring(0, backupSlash);
            String backupAction = backupRest.substring(backupSlash + 1);
            if ("restore".equals(backupAction)) {
                if (!requireMethod(exchange, "POST")) return;
                handlePlayCampaignBackupRestore(exchange, campaignId, backupId);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("replay-events".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignReplayEventCreate(exchange, campaignId);
            return;
        }
        if ("replay".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignReplayGet(exchange, campaignId);
            return;
        }
        if ("replay/check".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignReplayCheck(exchange, campaignId);
            return;
        }
        if ("rng-seed".equals(action)) {
            if (!requireMethod(exchange, "PUT")) return;
            handlePlayCampaignRngSeedPut(exchange, campaignId);
            return;
        }
        if ("rng-rolls".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignRngRollPost(exchange, campaignId);
            return;
        }
        if ("rng-ledger".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignRngLedgerGet(exchange, campaignId);
            return;
        }
        if ("moderation/reports".equals(action)) {
            if ("POST".equals(exchange.getRequestMethod())) {
                handlePlayCampaignModerationReportCreate(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignModerationReportList(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if (action.startsWith("moderation/reports/")) {
            String modRest = action.substring("moderation/reports/".length());
            int modSlash = modRest.indexOf('/');
            if (modSlash < 0) {
                notFound(exchange);
                return;
            }
            String reportId = modRest.substring(0, modSlash);
            String modAction = modRest.substring(modSlash + 1);
            if ("resolution".equals(modAction)) {
                if ("PUT".equals(exchange.getRequestMethod())) {
                    handlePlayCampaignModerationReportResolve(exchange, campaignId, reportId);
                    return;
                }
                HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
                return;
            }
            notFound(exchange);
            return;
        }
        if ("safety-boundaries".equals(action)) {
            if ("PUT".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSafetyBoundariesPut(exchange, campaignId);
                return;
            }
            if ("GET".equals(exchange.getRequestMethod())) {
                handlePlayCampaignSafetyBoundariesGet(exchange, campaignId);
                return;
            }
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return;
        }
        if ("safety-checks".equals(action)) {
            if (!requireMethod(exchange, "POST")) return;
            handlePlayCampaignSafetyCheckCreate(exchange, campaignId);
            return;
        }
        if ("safety-events".equals(action)) {
            if (!requireMethod(exchange, "GET")) return;
            handlePlayCampaignSafetyEventList(exchange, campaignId);
            return;
        }
        if ("fixture-seeds".equals(action)) {
            handlePlayCampaignFixtureSeed(exchange, campaignId);
            return;
        }
        if ("fixture-state".equals(action)) {
            handlePlayCampaignFixtureStateGet(exchange, campaignId);
            return;
        }
        notFound(exchange);
    }

    private void handlePlayCampaignCalendarInit(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object dayObj = req.get("day");
            String season = (String) req.get("season");
            if (dayObj == null || season == null || season.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            int day = JsonUtils.toInt(dayObj);
            if (day < 1) throw new RuntimeException("Invalid day");
            if (!isValidSeason(season)) throw new RuntimeException("Invalid season");
            if (storage.getPlayCampaignCalendar(campaignId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CALENDAR_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignCalendar(campaignId, day, season)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CALENDAR_EXISTS);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, calendarJson(day, season));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCalendarGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> calendar = storage.getPlayCampaignCalendar(campaignId);
        if (calendar == null) {
            notFound(exchange);
            return;
        }
        int day = JsonUtils.toInt(calendar.get("day"));
        String season = (String) calendar.get("season");
        HttpSupport.sendResponse(exchange, 200, calendarJson(day, season));
    }

    private void handlePlayCampaignCalendarAdvance(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> calendar = storage.getPlayCampaignCalendar(campaignId);
        if (calendar == null) {
            notFound(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object daysObj = req.get("days");
            if (daysObj == null) throw new RuntimeException("Missing days");
            int days = JsonUtils.toInt(daysObj);
            if (days < 1 || days > 30) throw new RuntimeException("Invalid days");
            int currentDay = JsonUtils.toInt(calendar.get("day"));
            String season = (String) calendar.get("season");
            int newDay = currentDay + days;
            if (!storage.advancePlayCampaignCalendar(campaignId, days)) {
                notFound(exchange);
                return;
            }
            HttpSupport.sendResponse(exchange, 200, calendarJson(newDay, season));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private boolean isValidSeason(String season) {
        return "spring".equals(season) || "summer".equals(season) || "autumn".equals(season) || "winter".equals(season);
    }

    private String computeWeather(String season, int day) {
        int offset;
        if ("spring".equals(season)) offset = 0;
        else if ("summer".equals(season)) offset = 1;
        else if ("autumn".equals(season)) offset = 2;
        else offset = 3;
        int value = (day + offset) % 4;
        if (value == 0) return "clear";
        if (value == 1) return "rain";
        if (value == 2) return "wind";
        return "snow";
    }

    private String calendarJson(int day, String season) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("day", day);
        res.put("season", season);
        res.put("weather", computeWeather(season, day));
        return JsonUtils.toJson(res);
    }

    private void handlePlayCampaignWorldEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            String title = (String) req.get("title");
            String text = (String) req.get("text");
            Object turnObj = req.get("turn_number");
            if (eventId == null || eventId.isEmpty() || title == null || title.isEmpty() || text == null || text.isEmpty() || turnObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int turnNumber = JsonUtils.toInt(turnObj);
            int currentTurnNumber = JsonUtils.toInt(campaign.get("turn_number"));
            if (turnNumber < currentTurnNumber) {
                throw new RuntimeException("Turn number before current");
            }
            if (storage.playCampaignWorldEventExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WORLD_EVENT_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignWorldEvent(campaignId, eventId, turnNumber, title, text)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WORLD_EVENT_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("turn_number", turnNumber);
            res.put("title", title);
            res.put("text", text);
            res.put("status", "scheduled");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignWorldEventResolve(HttpExchange exchange, String campaignId, String eventId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> event = storage.getPlayCampaignWorldEvent(campaignId, eventId);
        if (event == null) {
            notFound(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String text = (String) req.get("text");
            if (text == null || text.isEmpty()) throw new RuntimeException("Missing text");
            if ("resolved".equals(event.get("status"))) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WORLD_EVENT_ALREADY_RESOLVED);
                return;
            }
            int currentTurnNumber = JsonUtils.toInt(campaign.get("turn_number"));
            int eventTurnNumber = JsonUtils.toInt(event.get("turn_number"));
            if (currentTurnNumber != eventTurnNumber) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WORLD_EVENT_WRONG_TURN);
                return;
            }
            if (!storage.resolvePlayCampaignWorldEvent(campaignId, eventId, currentTurnNumber, text)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WORLD_EVENT_ALREADY_RESOLVED);
                return;
            }
            Map<String, Object> res = storage.getPlayCampaignWorldEvent(campaignId, eventId);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignWorldEventList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> events = storage.listPlayCampaignWorldEvents(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("events", events);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterDamage(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String target = (String) req.get("target");
            int amount = JsonUtils.toInt(req.get("amount"));
            if (target == null || target.isEmpty() || amount < 0) throw new RuntimeException("Missing or invalid fields");
            Map<String, Object> res = storage.applyDamageToEncounterTarget(campaignId, encounterId, target, amount);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterHeal(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String target = (String) req.get("target");
            int amount = JsonUtils.toInt(req.get("amount"));
            if (target == null || target.isEmpty() || amount < 0) throw new RuntimeException("Missing or invalid fields");
            Map<String, Object> res = storage.applyHealToEncounterTarget(campaignId, encounterId, target, amount);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignLocationCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String id = (String) req.get("id");
            String name = (String) req.get("name");
            if (id == null || id.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignLocation(campaignId, id) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_LOCATION_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignLocation(campaignId, id, name)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_LOCATION_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("name", name);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignConnectionCreate(HttpExchange exchange, String campaignId, String fromId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignLocation(campaignId, fromId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String toId = (String) req.get("to_id");
            Object travelTurnsObj = req.get("travel_turns");
            if (toId == null || toId.isEmpty() || travelTurnsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int travelTurns = JsonUtils.toInt(travelTurnsObj);
            if (travelTurns <= 0) throw new RuntimeException("Invalid travel_turns");
            if (storage.getPlayCampaignLocation(campaignId, toId) == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (storage.getPlayCampaignConnection(campaignId, fromId, toId) != null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_CONNECTION_INVALID);
                return;
            }
            if (!storage.insertPlayCampaignConnection(campaignId, fromId, toId, travelTurns)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_CONNECTION_INVALID);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("from_id", fromId);
            res.put("to_id", toId);
            res.put("travel_turns", travelTurns);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignTravel(HttpExchange exchange, String campaignId, String locId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        if (!isOwner && !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignLocation(campaignId, locId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> destinations = storage.listPlayCampaignConnectionsFrom(campaignId, locId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("destinations", destinations);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner")) && !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("campaign_id", campaignId);
        String status = (String) campaign.get("status");
        String owner = (String) campaign.get("owner");
        List<String> queue = new ArrayList<>();
        String currentActor = (String) campaign.get("current_actor");
        if ("active".equals(status)) {
            List<Map<String, Object>> members = storage.listPlayCampaignMembers(campaignId);
            for (Map<String, Object> member : members) {
                queue.add((String) member.get("username"));
                queue.add(owner);
            }
        }
        String phase;
        boolean inCombat = storage.hasActivePlayCampaignEncounter(campaignId);
        if ("lobby".equals(status)) {
            phase = "lobby";
        } else if (!inCombat && "exploration".equals(campaign.get("phase"))) {
            phase = "exploration";
            currentActor = owner;
        } else if (currentActor != null && currentActor.equals(owner)) {
            phase = "dm";
        } else {
            phase = "player";
        }
        res.put("current_actor", currentActor);
        res.put("phase", phase);
        Object turnNumber = campaign.get("turn_number");
        res.put("turn_number", turnNumber == null ? 1 : JsonUtils.toInt(turnNumber));
        Object deadline = campaign.get("deadline");
        res.put("logical_deadline", deadline == null ? 1 : JsonUtils.toInt(deadline));
        res.put("overdue", false);
        res.put("queue", queue);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignMyTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        if (!"player".equals(user.role)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
        if (member == null) {
            forbidden(exchange);
            return;
        }
        String currentActor = (String) campaign.get("current_actor");
        boolean isMyTurn = user.username.equals(currentActor);
        Map<String, Object> character = new LinkedHashMap<>();
        character.put("id", member.get("character_id"));
        character.put("name", member.get("name"));
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("is_my_turn", isMyTurn);
        res.put("current_actor", currentActor);
        res.put("character", character);
        res.put("recent_events", storage.listPlayCampaignNarrations(campaignId));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignGmStatus(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        String owner = (String) campaign.get("owner");
        String currentActor = (String) campaign.get("current_actor");
        boolean needsAttention = owner.equals(currentActor);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("needs_attention", needsAttention);
        res.put("current_actor", currentActor);
        res.put("party", storage.listPlayCampaignMembers(campaignId));
        res.put("recent_events", storage.listPlayCampaignNarrations(campaignId));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignDocumentGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> doc = storage.getPlayCampaignDocument(campaignId);
        String story = doc == null ? "" : (String) doc.get("story");
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("story", story);
        if (isOwner) {
            String dmNotes = doc == null ? "" : (String) doc.get("dm_notes");
            res.put("dm_notes", dmNotes);
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignDocumentPut(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String story = (String) req.get("story");
            String dmNotes = (String) req.get("dm_notes");
            if (story == null) story = "";
            if (dmNotes == null) dmNotes = "";
            storage.updatePlayCampaignDocument(campaignId, story, dmNotes);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("story", story);
            res.put("dm_notes", dmNotes);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignNudge(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String message = (String) req.get("message");
            if (message == null || message.isEmpty()) throw new RuntimeException("Missing message");
            int nudgeCount = storage.nudgePlayCampaign(campaignId, user.username, message);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("actor", user.username);
            res.put("target", campaign.get("current_actor"));
            res.put("message", message);
            res.put("nudge_count", nudgeCount);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignStart(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (!"lobby".equals(campaign.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_IN_LOBBY);
            return;
        }
        List<Map<String, Object>> members = storage.listPlayCampaignMembers(campaignId);
        if (members.size() < 2) {
            HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Party is under-populated\"}");
            return;
        }
        String currentActor = (String) members.get(0).get("username");
        if (!storage.startPlayCampaign(campaignId, currentActor)) {
            HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Campaign start failed\"}");
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", campaignId);
        res.put("status", "active");
        res.put("current_actor", currentActor);
        res.put("turn_number", 1);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignOnboarding(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        List<String> nextSteps = new ArrayList<>();
        if (isOwner) {
            res.put("role", "dm");
            nextSteps.add("configure-safety");
            nextSteps.add("invite-players");
            nextSteps.add("start-campaign");
        } else {
            res.put("role", "player");
            nextSteps.add("review-party");
            nextSteps.add("take-turn");
            nextSteps.add("submit-action");
        }
        res.put("next_steps", nextSteps);
        res.put("can_mutate", true);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignNarration(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = "dm".equals(user.role) && user.username.equals(campaign.get("owner"));
        boolean isNarrator = !isOwner && storage.hasActivePlayCampaignDelegationPower(campaignId, user.username, "narrate");
        if (!isOwner && !isNarrator) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String text = (String) req.get("text");
            if (text == null || text.isEmpty()) throw new RuntimeException("Missing text");
            String actor = isOwner ? "dm" : user.username;
            Map<String, Object> res = storage.insertPlayCampaignNarration(campaignId, actor, text);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignMessageCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String text = (String) req.get("text");
            if (text == null || text.isEmpty()) throw new RuntimeException("Missing text");
            String actor = isOwner ? "dm" : user.username;
            Map<String, Object> res = storage.insertPlayCampaignChatEvent(campaignId, actor, text);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignActionSubmit(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = (String) campaign.get("owner");
        boolean isOwner = user.username.equals(owner);
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isMember && !isOwner) {
            forbidden(exchange);
            return;
        }
        String currentActor = (String) campaign.get("current_actor");
        if (!"player".equals(user.role) || !"active".equals(campaign.get("status")) || !user.username.equals(currentActor)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String type = (String) req.get("type");
            String text = (String) req.get("text");
            if (type == null || type.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            Map<String, Object> res = storage.submitPlayCampaignAction(campaignId, user.username, type, text, owner);
            res.put("next_actor", "dm");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignResolution(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = (String) campaign.get("owner");
        String currentActor = (String) campaign.get("current_actor");
        if (!owner.equals(currentActor) || !user.username.equals(owner)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String text = (String) req.get("text");
            if (text == null || text.isEmpty()) throw new RuntimeException("Missing text");
            String nextActor = computeNextPlayer(campaignId, owner);
            Map<String, Object> res = storage.submitPlayCampaignResolution(campaignId, owner, text, nextActor);
            res.put("next_actor", nextActor);
            Map<String, Object> updatedCampaign = storage.getPlayCampaignTurn(campaignId);
            Object turnNumber = updatedCampaign == null ? null : updatedCampaign.get("turn_number");
            res.put("turn_number", turnNumber == null ? 1 : JsonUtils.toInt(turnNumber));
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignTravelTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = (String) campaign.get("owner");
        boolean isOwner = user.username.equals(owner);
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isMember && !isOwner) {
            forbidden(exchange);
            return;
        }
        String currentActor = (String) campaign.get("current_actor");
        if (!"player".equals(user.role) || !"active".equals(campaign.get("status")) || !user.username.equals(currentActor)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String destinationId = (String) req.get("destination_id");
            if (destinationId == null || destinationId.isEmpty()) {
                throw new RuntimeException("Missing destination_id");
            }
            String currentLocationId = (String) campaign.get("current_location_id");
            if (currentLocationId == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_DESTINATION);
                return;
            }
            Map<String, Object> connection = storage.getPlayCampaignConnection(campaignId, currentLocationId, destinationId);
            if (connection == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_DESTINATION);
                return;
            }
            int travelTurns = JsonUtils.toInt(connection.get("travel_turns"));
            Map<String, Object> res = storage.submitPlayCampaignTravel(campaignId, user.username, destinationId, travelTurns, owner);
            res.put("next_actor", owner);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRestTurn(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaignTurn(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = (String) campaign.get("owner");
        boolean isOwner = user.username.equals(owner);
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isMember && !isOwner) {
            forbidden(exchange);
            return;
        }
        String currentActor = (String) campaign.get("current_actor");
        if (!"player".equals(user.role) || !"active".equals(campaign.get("status")) || !user.username.equals(currentActor)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String type = (String) req.get("type");
            if (type == null || (!"long".equals(type) && !"short".equals(type))) {
                throw new RuntimeException("Invalid rest type");
            }
            Map<String, Object> res = storage.submitPlayCampaignRest(campaignId, user.username, type, owner);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignJoin(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        if (!"player".equals(user.role)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"lobby".equals(campaign.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_IN_LOBBY);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String characterId = (String) req.get("character_id");
            String name = (String) req.get("name");
            String className = (String) req.get("class");
            if (characterId == null || characterId.isEmpty() || name == null || name.isEmpty() || className == null || className.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            int currentMembers = storage.countPlayCampaignMembers(campaignId);
            int maxPlayers = JsonUtils.toInt(campaign.get("max_players"));
            if (currentMembers >= maxPlayers) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Party is full\"}");
                return;
            }
            if (!storage.insertPlayCampaignMember(campaignId, user.username, characterId, name, className)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Duplicate membership or character\"}");
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", user.username);
            res.put("character_id", characterId);
            res.put("name", name);
            res.put("class", className);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private String computeNextPlayer(String campaignId, String owner) {
        List<Map<String, Object>> members = storage.listPlayCampaignMembers(campaignId);
        if (members.isEmpty()) return owner;
        String previousActor = storage.getMostRecentPlayerEventActor(campaignId);
        if (previousActor == null) {
            return (String) members.get(0).get("username");
        }
        for (int i = 0; i < members.size(); i++) {
            if (previousActor.equals(members.get(i).get("username"))) {
                return (String) members.get((i + 1) % members.size()).get("username");
            }
        }
        return (String) members.get(0).get("username");
    }

    private void handlePlayCampaignEncounterCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String encounterId = (String) req.get("id");
            String name = (String) req.get("name");
            if (encounterId == null || encounterId.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignEncounter(campaignId, encounterId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_ENCOUNTER_EXISTS);
                return;
            }
            if (storage.hasActivePlayCampaignEncounter(campaignId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_IN_COMBAT);
                return;
            }
            Map<String, Object> campaignTurn = storage.getPlayCampaignTurn(campaignId);
            storage.setPreCombatActor(campaignId, campaignTurn == null ? null : (String) campaignTurn.get("current_actor"));
            if (!storage.insertPlayCampaignEncounter(campaignId, encounterId, name)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_ENCOUNTER_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", encounterId);
            res.put("name", name);
            res.put("status", "active");
            res.put("combatants", new ArrayList<>());
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterMonsterCreate(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String monsterId = (String) req.get("monster_id");
            String name = (String) req.get("name");
            int hpMax = JsonUtils.toInt(req.get("hp_max"));
            int initiative = JsonUtils.toInt(req.get("initiative"));
            if (monsterId == null || monsterId.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignEncounterMonster(campaignId, encounterId, monsterId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MONSTER_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignEncounterMonster(campaignId, encounterId, monsterId, name, hpMax, hpMax, initiative)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MONSTER_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("monster_id", monsterId);
            res.put("name", name);
            res.put("hp_max", hpMax);
            res.put("initiative", initiative);
            res.put("hp_current", hpMax);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterMonsterDelete(HttpExchange exchange, String campaignId, String encounterId, String monsterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> monster = storage.getPlayCampaignEncounterMonster(campaignId, encounterId, monsterId);
        if (monster == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        storage.deletePlayCampaignEncounterMonster(campaignId, encounterId, monsterId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("removed", monsterId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterCombatantCreate(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String member = (String) req.get("member");
            int initiative = JsonUtils.toInt(req.get("initiative"));
            if (member == null || member.isEmpty()) {
                throw new RuntimeException("Missing member");
            }
            Map<String, Object> memberInfo = storage.getPlayCampaignMember(campaignId, member);
            if (memberInfo == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (storage.getPlayCampaignEncounterCombatant(campaignId, encounterId, member) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_COMBATANT_EXISTS);
                return;
            }
            String characterId = (String) memberInfo.get("character_id");
            String name = (String) memberInfo.get("name");
            if (!storage.insertPlayCampaignEncounterCombatant(campaignId, encounterId, member, characterId, name, initiative)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_COMBATANT_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("member", member);
            res.put("character_id", characterId);
            res.put("name", name);
            res.put("initiative", initiative);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterCombatantDelete(HttpExchange exchange, String campaignId, String encounterId, String member) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> combatant = storage.getPlayCampaignEncounterCombatant(campaignId, encounterId, member);
        if (combatant == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        storage.deletePlayCampaignEncounterCombatant(campaignId, encounterId, member);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("removed", member);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSceneCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String sceneId = (String) req.get("id");
            String name = (String) req.get("name");
            if (sceneId == null || sceneId.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!storage.insertPlayCampaignScene(campaignId, sceneId, name)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SCENE_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", sceneId);
            res.put("name", name);
            res.put("status", "open");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSceneEnter(HttpExchange exchange, String campaignId, String sceneId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> scene = storage.getPlayCampaignScene(campaignId, sceneId);
        if (scene == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        if ("closed".equals(scene.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_SCENE_CLOSED);
            return;
        }
        storage.setPlayCampaignCurrentScene(campaignId, user.username, sceneId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("current_scene_id", sceneId);
        res.put("name", scene.get("name"));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSceneClose(HttpExchange exchange, String campaignId, String sceneId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> scene = storage.getPlayCampaignScene(campaignId, sceneId);
        if (scene == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        storage.closePlayCampaignScene(campaignId, sceneId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", sceneId);
        res.put("status", "closed");
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSceneCurrent(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> scene = storage.getPlayCampaignCurrentScene(campaignId);
        if (scene == null || !"open".equals(scene.get("status"))) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(scene));
    }

    private void handlePlayCampaignEncounterTurn(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        if (size == 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_COMBATANTS);
            return;
        }
        int round = JsonUtils.toInt(encounter.get("round"));
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index")) % size;
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("round", round);
        res.put("turn_index", turnIndex);
        res.put("active", activeCombatantJson(combatants, turnIndex));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterTurnAdvance(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        if (size == 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_COMBATANTS);
            return;
        }
        int round = JsonUtils.toInt(encounter.get("round"));
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index")) % size;
        Map<String, Object> current = combatants.get(turnIndex);
        boolean canAdvance = isOwner;
        if (!canAdvance) {
            String kind = (String) current.get("kind");
            String controller = (String) current.get("controller");
            if ("player".equals(kind) && user.username.equals(controller)) {
                canAdvance = true;
            }
        }
        if (!canAdvance) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        turnIndex++;
        if (turnIndex >= size) {
            turnIndex = 0;
            round++;
        }
        String activeTarget = (String) combatants.get(turnIndex).get("id");
        storage.advancePlayCampaignEncounterTurn(campaignId, encounterId, round, turnIndex, activeTarget);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("round", round);
        res.put("turn_index", turnIndex);
        res.put("active", activeCombatantJson(combatants, turnIndex));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterDelay(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        if (size == 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_COMBATANTS);
            return;
        }
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index")) % size;
        Map<String, Object> current = combatants.get(turnIndex);
        boolean canDelay = isOwner;
        if (!canDelay) {
            String kind = (String) current.get("kind");
            String controller = (String) current.get("controller");
            if ("player".equals(kind) && user.username.equals(controller)) {
                canDelay = true;
            }
        }
        if (!canDelay) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object newIndexObj = req.get("new_index");
            if (newIndexObj == null) throw new RuntimeException("missing new_index");
            int newIndex = JsonUtils.toInt(newIndexObj);
            if (newIndex <= turnIndex || newIndex >= size) throw new RuntimeException("illegal index");
            storage.delayPlayCampaignEncounter(campaignId, encounterId, turnIndex, newIndex);
            List<Map<String, Object>> order = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
            Map<String, Object> res = new LinkedHashMap<>();
            List<Map<String, Object>> orderJson = new ArrayList<>();
            for (Map<String, Object> c : order) {
                Map<String, Object> o = new LinkedHashMap<>();
                o.put("name", c.get("name"));
                orderJson.add(o);
            }
            res.put("order", orderJson);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterReady(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        if (size == 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_COMBATANTS);
            return;
        }
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index")) % size;
        Map<String, Object> current = combatants.get(turnIndex);
        String kind = (String) current.get("kind");
        String controller = (String) current.get("controller");
        if (!"player".equals(kind) || !user.username.equals(controller)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String trigger = (String) req.get("trigger");
            if (trigger == null || trigger.isEmpty()) throw new RuntimeException("missing trigger");
            storage.insertPlayCampaignEncounterReady(campaignId, encounterId, user.username, trigger);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("actor", user.username);
            res.put("trigger", trigger);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterAction(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        if (size == 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_COMBATANTS);
            return;
        }
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index")) % size;
        Map<String, Object> current = combatants.get(turnIndex);
        String kind = (String) current.get("kind");
        String controller = (String) current.get("controller");
        if (!"player".equals(kind) || !user.username.equals(controller)) {

            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_YOUR_TURN);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String type = (String) req.get("type");
            String target = (String) req.get("target");
            String text = (String) req.get("text");
            if (type == null || type.isEmpty() || target == null || target.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!"attack".equals(type) && !"help".equals(type) && !"dodge".equals(type) && !"ready".equals(type)) {
                throw new RuntimeException("Invalid action type");
            }
            Map<String, Object> res = storage.submitPlayCampaignEncounterAction(campaignId, encounterId, user.username, type, target, text);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterDamage(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int amount = JsonUtils.toInt(req.get("amount"));
            if (amount < 0) throw new RuntimeException("Invalid amount");
            Map<String, Object> target = storage.applyDamageToPlayCampaignCharacter(campaignId, charId, amount);
            if (target == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            target.put("target", charId);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(target));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterDeathSave(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> member = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (member == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        if (!user.username.equals(member.get("username"))) {
            forbidden(exchange);
            return;
        }
        if (!"unconscious".equals(member.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_STATE);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String outcome = (String) req.get("outcome");
            if (!"success".equals(outcome) && !"failure".equals(outcome)) {
                throw new RuntimeException("Invalid outcome");
            }
            Map<String, Object> res = storage.recordDeathSave(campaignId, charId, outcome);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_STATE);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterStatus(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.getPlayCampaignCharacterStatus(campaignId, charId);
        if (res == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterCondition(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String target = (String) req.get("target");
            String condition = (String) req.get("condition");
            int durationRounds = JsonUtils.toInt(req.get("duration_rounds"));
            if (target == null || target.isEmpty() || condition == null || condition.isEmpty() || durationRounds <= 0) {
                throw new RuntimeException("Missing or invalid fields");
            }
            if (!isValidEncounterTarget(campaignId, encounterId, target)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            storage.addPlayCampaignEncounterCondition(campaignId, encounterId, target, condition, durationRounds);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("target", target);
            List<Map<String, Object>> conditions = new ArrayList<>();
            Map<String, List<Map<String, Object>>> allConditions = storage.listPlayCampaignEncounterConditions(campaignId, encounterId);
            for (Map<String, Object> cond : allConditions.getOrDefault(target, new ArrayList<>())) {
                conditions.add(cond);
            }
            res.put("conditions", conditions);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterStatus(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounterTurn(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> combatants = storage.listPlayCampaignEncounterCombatants(campaignId, encounterId);
        int size = combatants.size();
        int round = JsonUtils.toInt(encounter.get("round"));
        int turnIndex = JsonUtils.toInt(encounter.get("turn_index"));
        if (size > 0) turnIndex = turnIndex % size;
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("round", round);
        res.put("turn_index", turnIndex);
        res.put("active", activeCombatantJson(combatants, turnIndex));
        List<Map<String, Object>> order = new ArrayList<>();
        for (Map<String, Object> c : combatants) {
            Map<String, Object> o = new LinkedHashMap<>();
            o.put("name", c.get("name"));
            o.put("kind", c.get("kind"));
            o.put("initiative", JsonUtils.toInt(c.get("initiative")));
            order.add(o);
        }
        res.put("order", order);
        res.put("conditions", storage.listPlayCampaignEncounterConditions(campaignId, encounterId));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterRewards(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object xpObj = req.get("xp");
            if (xpObj == null) throw new RuntimeException("missing xp");
            int xp = JsonUtils.toInt(xpObj);
            if (xp < 0) throw new RuntimeException("negative xp");
            List<Map<String, Object>> loot = new ArrayList<>();
            Object lootObj = req.get("loot");
            if (lootObj != null) {
                if (!(lootObj instanceof List)) throw new RuntimeException("loot not a list");
                for (Object o : (List<?>) lootObj) {
                    if (!(o instanceof Map)) throw new RuntimeException("loot item not object");
                    @SuppressWarnings("unchecked")
                    Map<String, Object> item = (Map<String, Object>) o;
                    String slug = (String) item.get("slug");
                    Object qtyObj = item.get("quantity");
                    if (slug == null || slug.isEmpty() || qtyObj == null) {
                        throw new RuntimeException("invalid loot item");
                    }
                    int quantity = JsonUtils.toInt(qtyObj);
                    if (quantity <= 0) throw new RuntimeException("nonpositive quantity");
                    Map<String, Object> clean = new LinkedHashMap<>();
                    clean.put("slug", slug);
                    clean.put("quantity", quantity);
                    loot.add(clean);
                }
            }
            if (!storage.awardEncounterRewards(campaignId, encounterId, xp, loot)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_REWARDS_ALREADY_AWARDED);
                return;
            }
            Map<String, Object> res = storage.getEncounterRewards(campaignId, encounterId);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEncounterClose(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> encounter = storage.getPlayCampaignEncounter(campaignId, encounterId);
        if (encounter == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = storage.closePlayCampaignEncounter(campaignId, encounterId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignEncounterEnd(HttpExchange exchange, String campaignId, String encounterId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.endPlayCampaignEncounter(campaignId, encounterId);
        if (res == null) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_IN_COMBAT);
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("campaign_id", campaignId);
        body.put("status", "active");
        body.put("phase", "exploration");
        body.put("current_actor", res.get("current_actor"));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(body));
    }

    private boolean isValidEncounterTarget(String campaignId, String encounterId, String target) {
        return storage.getPlayCampaignEncounterMonster(campaignId, encounterId, target) != null
            || storage.getPlayCampaignEncounterCombatant(campaignId, encounterId, target) != null;
    }

    private void handlePlayCampaignCharacterOwnerGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("owner", owner);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterCurrencyGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Integer gold = storage.getPlayCampaignCharacterGold(campaignId, charId);
        if (gold == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("gold", gold);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterCurrencyTransfer(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String currentOwner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (currentOwner == null || !currentOwner.equals(user.username)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String toCharacterId = (String) req.get("to_character_id");
            Object goldObj = req.get("gold");
            if (toCharacterId == null || toCharacterId.isEmpty() || goldObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int gold = JsonUtils.toInt(goldObj);
            if (gold <= 0) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (toCharacterId.equals(charId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            Map<String, Object> res = storage.transferPlayCampaignGold(campaignId, charId, toCharacterId, gold);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INSUFFICIENT_GOLD);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterOwnerClaim(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String currentOwner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (currentOwner != null && !currentOwner.equals(user.username)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_CHARACTER_OWNED);
            return;
        }
        storage.setPlayCampaignCharacterOwner(campaignId, charId, user.username);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("owner", user.username);
        HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterOwnerTransfer(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String currentOwner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (currentOwner == null || !currentOwner.equals(user.username)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String newOwner = (String) req.get("new_owner");
            if (newOwner == null || newOwner.isEmpty()) throw new RuntimeException("Missing new_owner");
            if (!storage.isPlayCampaignMember(campaignId, newOwner)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            storage.setPlayCampaignCharacterOwner(campaignId, charId, newOwner);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("owner", newOwner);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterBuild(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String race = (String) req.get("race");
            String className = (String) req.get("class");
            String background = (String) req.get("background");
            if (race == null || race.isEmpty() || className == null || className.isEmpty() || background == null || background.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!Rules.VALID_RACES.contains(race.toLowerCase())
                    || !Rules.VALID_CLASSES.contains(className.toLowerCase())
                    || !Rules.VALID_BACKGROUNDS.contains(background.toLowerCase())) {
                throw new RuntimeException("Invalid choice");
            }
            Map<String, Object> abilities = (Map<String, Object>) req.get("abilities");
            if (abilities == null) throw new RuntimeException("Missing abilities");
            String[] abilityNames = {"str", "dex", "con", "int", "wis", "cha"};
            int conScore = 0;
            for (String name : abilityNames) {
                Object val = abilities.get(name);
                if (val == null) throw new RuntimeException("Missing ability: " + name);
                int score = JsonUtils.toInt(val);
                if (score < 1 || score > 30) throw new RuntimeException("Ability out of range");
                if ("con".equals(name)) conScore = score;
            }
            int level = 1;
            int hpMax = Rules.hitDieAtLevel1(className) + Rules.abilityModifier(conScore);
            if (hpMax < 1) hpMax = 1;
            String abilitiesJson = JsonUtils.toJson(abilities);
            storage.updatePlayCampaignCharacterBuild(campaignId, charId, race, className, background, level, hpMax, abilitiesJson);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("race", race);
            res.put("class", className);
            res.put("background", background);
            res.put("level", level);
            res.put("hp_max", hpMax);
            res.put("proficiency_bonus", Rules.proficiencyBonus(level));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterLevelUp(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object levelObj = req.get("level");
            if (levelObj == null) throw new RuntimeException("Missing level");
            int requestedLevel = JsonUtils.toInt(levelObj);
            Map<String, Object> info = storage.getPlayCampaignCharacterLevelInfo(campaignId, charId);
            if (info == null) throw new RuntimeException("Character not found");
            int currentLevel = JsonUtils.toInt(info.get("level"));
            if (requestedLevel != currentLevel + 1) throw new RuntimeException("Invalid level");
            String className = (String) info.get("class");
            if (className == null) throw new RuntimeException("Missing class");
            int currentHpMax = JsonUtils.toInt(info.get("hp_max"));
            String abilitiesJson = (String) info.get("abilities");
            int conModifier = 0;
            if (abilitiesJson != null && !abilitiesJson.isEmpty()) {
                Map<String, Object> abilities = JsonUtils.parseJsonObject(abilitiesJson);
                Object conObj = abilities.get("con");
                if (conObj != null) conModifier = Rules.abilityModifier(JsonUtils.toInt(conObj));
            }
            int hitDie = Rules.hitDieAtLevel1(className);
            int average = hitDie / 2 + 1;
            int newHpMax = currentHpMax + average + conModifier;
            if (newHpMax < 1) newHpMax = 1;
            if (!storage.levelUpPlayCampaignCharacter(campaignId, charId, requestedLevel, newHpMax)) {
                throw new RuntimeException("Level up failed");
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("level", requestedLevel);
            res.put("hp_max", newHpMax);
            res.put("hit_dice", "1d" + hitDie);
            res.put("proficiency_bonus", Rules.proficiencyBonus(requestedLevel));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterSkillCheck(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String skill = (String) req.get("skill");
            String ability = (String) req.get("ability");
            Object proficientObj = req.get("proficient");
            int roll = JsonUtils.toInt(req.get("roll"));
            if (skill == null || skill.isEmpty() || ability == null || ability.isEmpty() || proficientObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!Rules.isValidSkill(skill) || !Rules.isValidAbility(ability)) {
                throw new RuntimeException("Unsupported skill or ability");
            }
            boolean proficient = Boolean.TRUE.equals(proficientObj);
            Map<String, Object> info = storage.getPlayCampaignCharacterLevelInfo(campaignId, charId);
            if (info == null) throw new RuntimeException("Character not found");
            int level = JsonUtils.toInt(info.get("level"));
            String abilitiesJson = (String) info.get("abilities");
            if (abilitiesJson == null || abilitiesJson.isEmpty()) throw new RuntimeException("Missing abilities");
            Map<String, Object> abilities = JsonUtils.parseJsonObject(abilitiesJson);
            Object scoreObj = abilities.get(ability);
            if (scoreObj == null) throw new RuntimeException("Missing ability score");
            int score = JsonUtils.toInt(scoreObj);
            int abilityModifier = Rules.abilityModifier(score);
            int proficiencyBonus = Rules.proficiencyBonus(level);
            int modifier = abilityModifier + (proficient ? proficiencyBonus : 0);
            int total = roll + modifier;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("skill", skill);
            res.put("ability", ability);
            res.put("modifier", modifier);
            res.put("total", total);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterSpellsGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> spells = storage.listPlayCampaignCharacterSpells(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("spells", spells);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterSpellsCreate(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String spellId = (String) req.get("spell_id");
            String name = (String) req.get("name");
            Object levelObj = req.get("level");
            if (spellId == null || spellId.isEmpty() || name == null || name.isEmpty() || levelObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int level = JsonUtils.toInt(levelObj);
            String className = (String) character.get("class");
            if (!Rules.isValidSpellForClass(spellId, className)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (!storage.insertPlayCampaignCharacterSpell(campaignId, charId, spellId, name, level)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SPELL_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("spell_id", spellId);
            res.put("name", name);
            res.put("level", level);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterPreparedSpellsGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        sendPreparedSpellsResponse(exchange, campaignId, charId);
    }

    private void handlePlayCampaignCharacterPreparedSpellsPut(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object spellIdsObj = req.get("spell_ids");
            if (spellIdsObj == null || !(spellIdsObj instanceof List)) {
                throw new RuntimeException("Missing spell_ids");
            }
            List<?> spellIdsRaw = (List<?>) spellIdsObj;
            Set<String> seenSpellIds = new HashSet<>();
            List<String> spellIds = new ArrayList<>();
            for (Object o : spellIdsRaw) {
                if (!(o instanceof String)) throw new RuntimeException("Non-string spell_id");
                String spellId = (String) o;
                if (spellId.isEmpty()) throw new RuntimeException("Empty spell_id");
                if (seenSpellIds.add(spellId)) {
                    spellIds.add(spellId);
                }
            }
            String className = (String) character.get("class");
            int level = JsonUtils.toInt(character.get("level"));
            if (!"wizard".equals(className)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            int maxPrepared = level;
            if (spellIds.size() > maxPrepared) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            List<Map<String, Object>> knownSpells = storage.listPlayCampaignCharacterSpells(campaignId, charId);
            Set<String> knownSpellIds = new HashSet<>();
            for (Map<String, Object> s : knownSpells) {
                knownSpellIds.add((String) s.get("spell_id"));
            }
            for (String spellId : spellIds) {
                if (!knownSpellIds.contains(spellId)) {
                    HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                    return;
                }
            }
            storage.setPlayCampaignCharacterPreparedSpells(campaignId, charId, spellIds);
            sendPreparedSpellsResponse(exchange, campaignId, charId);
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void sendPreparedSpellsResponse(HttpExchange exchange, String campaignId, String charId) throws IOException {
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        String className = character == null ? null : (String) character.get("class");
        int level = character == null ? 0 : JsonUtils.toInt(character.get("level"));
        int maxPrepared = "wizard".equals(className) ? level : 0;
        List<String> preparedSpells = storage.listPlayCampaignCharacterPreparedSpells(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("prepared_spells", preparedSpells);
        res.put("max_prepared", maxPrepared);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterCastsGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> casts = storage.listPlayCampaignCharacterCasts(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("casts", casts);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterCastsCreate(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String spellId = (String) req.get("spell_id");
            String target = (String) req.get("target");
            if (spellId == null || spellId.isEmpty() || target == null) {
                throw new RuntimeException("Missing fields");
            }
            String className = (String) character.get("class");
            int level = JsonUtils.toInt(character.get("level"));
            if (!Rules.isSpellcastingClass(className)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            Map<String, Object> spell = storage.getPlayCampaignCharacterSpell(campaignId, charId, spellId);
            if (spell == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (!storage.isPlayCampaignCharacterSpellPrepared(campaignId, charId, spellId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            int slotLevel = JsonUtils.toInt(spell.get("level"));
            int maxSlots = Rules.spellSlots(className, level, slotLevel);
            int castsAtLevel = storage.countPlayCampaignCharacterCastsAtSlotLevel(campaignId, charId, slotLevel);
            int slotsRemainingBefore = maxSlots - castsAtLevel;
            if (slotLevel > 0 && slotsRemainingBefore <= 0) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NO_SPELL_SLOTS);
                return;
            }
            int sequence = storage.getNextPlayCampaignCharacterCastSequence(campaignId, charId);
            int slotsRemainingAfter = slotLevel > 0 ? slotsRemainingBefore - 1 : 0;
            Map<String, Object> res = storage.insertPlayCampaignCharacterCast(campaignId, charId, spellId, target, slotLevel, slotsRemainingAfter, sequence);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterConcentrationGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> concentration = storage.getPlayCampaignCharacterConcentration(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("concentration", concentration);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterConcentrationPut(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String spellId = (String) req.get("spell_id");
            String target = (String) req.get("target");
            Object durationObj = req.get("duration_turns");
            if (spellId == null || spellId.isEmpty() || target == null || durationObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int durationTurns = JsonUtils.toInt(durationObj);
            if (durationTurns < 1) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            String className = (String) character.get("class");
            if (!Rules.isSpellcastingClass(className)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            Map<String, Object> spell = storage.getPlayCampaignCharacterSpell(campaignId, charId, spellId);
            if (spell == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (!storage.isPlayCampaignCharacterSpellPrepared(campaignId, charId, spellId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            storage.setPlayCampaignCharacterConcentration(campaignId, charId, spellId, target, durationTurns);
            Map<String, Object> concentration = new LinkedHashMap<>();
            concentration.put("spell_id", spellId);
            concentration.put("target", target);
            concentration.put("remaining_turns", durationTurns);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("concentration", concentration);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterConcentrationAdvance(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> concentration = storage.advancePlayCampaignCharacterConcentration(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("concentration", concentration);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterConcentrationDelete(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        storage.clearPlayCampaignCharacterConcentration(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("concentration", null);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private boolean isValidInventoryItemId(String itemId) {
        return "healing-potion".equals(itemId) || "torch".equals(itemId) || "leather-armor".equals(itemId) || "ring-of-protection".equals(itemId) || "amulet-of-health".equals(itemId);
    }

    private boolean isValidEquipmentItemId(String itemId) {
        return "leather-armor".equals(itemId) || "ring-of-protection".equals(itemId) || "amulet-of-health".equals(itemId);
    }

    private boolean isValidAttunableItemId(String itemId) {
        return "ring-of-protection".equals(itemId) || "amulet-of-health".equals(itemId);
    }

    private boolean isValidEquipmentSlot(String slot) {
        return "armor".equals(slot) || "accessory".equals(slot);
    }

    private boolean isItemSlotMatch(String itemId, String slot) {
        if ("leather-armor".equals(itemId)) return "armor".equals(slot);
        if ("ring-of-protection".equals(itemId) || "amulet-of-health".equals(itemId)) return "accessory".equals(slot);
        return false;
    }

    private void handlePlayCampaignCharacterInventoryGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> items = storage.listPlayCampaignCharacterInventory(campaignId, charId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("items", items);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterInventoryAdd(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String itemId = (String) req.get("item_id");
            int quantity = JsonUtils.toInt(req.get("quantity"));
            if (itemId == null || itemId.isEmpty() || !isValidInventoryItemId(itemId) || quantity <= 0) {
                throw new RuntimeException("Invalid inventory item");
            }
            int total = storage.addPlayCampaignCharacterInventoryItem(campaignId, charId, itemId, quantity);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("item_id", itemId);
            res.put("quantity", quantity);
            res.put("total_quantity", total);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterInventoryDelete(HttpExchange exchange, String campaignId, String charId, String itemId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            int quantity = JsonUtils.toInt(req.get("quantity"));
            if (!isValidInventoryItemId(itemId) || quantity <= 0) {
                throw new RuntimeException("Invalid inventory item");
            }
            int remaining = storage.removePlayCampaignCharacterInventoryItem(campaignId, charId, itemId, quantity);
            if (remaining < 0) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVENTORY_OVERDRAW);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("item_id", itemId);
            res.put("quantity", quantity);
            res.put("total_quantity", remaining);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterInventoryConsume(HttpExchange exchange, String campaignId, String charId, String itemId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        if (!"healing-potion".equals(itemId)) {
            badRequest(exchange);
            return;
        }
        int quantity = storage.getPlayCampaignCharacterInventoryQuantity(campaignId, charId, itemId);
        if (quantity <= 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NO_CONSUMABLE_STACK);
            return;
        }
        Map<String, Object> res = storage.consumePlayCampaignCharacterInventoryItem(campaignId, charId, itemId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterEquip(HttpExchange exchange, String campaignId, String charId, String slot) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String itemId = (String) req.get("item_id");
            if (itemId == null || itemId.isEmpty() || !isValidEquipmentItemId(itemId) || !isValidEquipmentSlot(slot) || !isItemSlotMatch(itemId, slot)) {
                throw new RuntimeException("Invalid equipment request");
            }
            if (storage.getPlayCampaignCharacterInventoryQuantity(campaignId, charId, itemId) <= 0) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            storage.setPlayCampaignCharacterEquipment(campaignId, charId, slot, itemId, false);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("slot", slot);
            res.put("item_id", itemId);
            res.put("attuned", false);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignCharacterEquipmentGet(HttpExchange exchange, String campaignId, String charId, String slot) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        if (!isValidEquipmentSlot(slot)) {
            HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> equipment = storage.getPlayCampaignCharacterEquipment(campaignId, charId, slot);
        String itemId = equipment == null ? "" : (String) equipment.get("item_id");
        boolean attuned = equipment != null && Boolean.TRUE.equals(equipment.get("attuned"));
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("slot", slot);
        res.put("item_id", itemId == null ? "" : itemId);
        res.put("attuned", attuned);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterEquipmentAttune(HttpExchange exchange, String campaignId, String charId, String slot) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        if (!"accessory".equals(slot)) {
            HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
            return;
        }
        Map<String, Object> equipment = storage.getPlayCampaignCharacterEquipment(campaignId, charId, slot);
        String itemId = equipment == null ? "" : (String) equipment.get("item_id");
        if (!isValidAttunableItemId(itemId)) {
            HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
            return;
        }
        int attunedCount = storage.countPlayCampaignCharacterAttunedEquipment(campaignId, charId);
        if (attunedCount > 0) {
            HttpSupport.sendResponse(exchange, 409, ERROR_ALREADY_ATTUNED);
            return;
        }
        storage.setPlayCampaignCharacterEquipmentAttuned(campaignId, charId, slot, true);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("slot", slot);
        res.put("item_id", itemId);
        res.put("attuned", true);
        res.put("attunement_count", 1);
        res.put("max_attunements", 1);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignLootCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String lootId = (String) req.get("loot_id");
            String itemId = (String) req.get("item_id");
            Object quantityObj = req.get("quantity");
            if (lootId == null || lootId.isEmpty() || itemId == null || itemId.isEmpty() || quantityObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int quantity = JsonUtils.toInt(quantityObj);
            if (quantity <= 0) throw new RuntimeException("Invalid quantity");
            if (!isValidCatalogItemId(itemId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (storage.getPlayCampaignLoot(campaignId, lootId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_LOOT_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignLoot(campaignId, lootId, itemId, quantity)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_LOOT_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("loot_id", lootId);
            res.put("item_id", itemId);
            res.put("quantity", quantity);
            res.put("status", "open");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private boolean isValidCatalogItemId(String itemId) {
        return isValidInventoryItemId(itemId) || storage.getItem(itemId) != null;
    }

    private void handlePlayCampaignLootVote(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"player".equals(user.role) || !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> loot = storage.getPlayCampaignLoot(campaignId, lootId);
        if (loot == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        if (!"open".equals(loot.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_LOOT_VOTE_EXISTS);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String recipientCharacterId = (String) req.get("recipient_character_id");
            if (recipientCharacterId == null || recipientCharacterId.isEmpty()) {
                throw new RuntimeException("Missing recipient_character_id");
            }
            if (storage.getPlayCampaignMemberByCharacterId(campaignId, recipientCharacterId) == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (!storage.insertPlayCampaignLootVote(campaignId, lootId, user.username, recipientCharacterId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_LOOT_VOTE_EXISTS);
                return;
            }
            int votesForRecipient = storage.countPlayCampaignLootVotesForRecipient(campaignId, lootId, recipientCharacterId);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("loot_id", lootId);
            res.put("voter", user.username);
            res.put("recipient_character_id", recipientCharacterId);
            res.put("votes_for_recipient", votesForRecipient);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignLootAssign(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> loot = storage.getPlayCampaignLoot(campaignId, lootId);
        if (loot == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = storage.assignPlayCampaignLoot(campaignId, lootId);
        if (res == null) {
            HttpSupport.sendResponse(exchange, 409, ERROR_LOOT_CANNOT_ASSIGN);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignLootGet(HttpExchange exchange, String campaignId, String lootId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> loot = storage.getPlayCampaignLoot(campaignId, lootId);
        if (loot == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("loot_id", loot.get("loot_id"));
        res.put("item_id", loot.get("item_id"));
        res.put("quantity", loot.get("quantity"));
        res.put("status", loot.get("status"));
        res.put("recipient_character_id", loot.get("recipient_character_id"));
        res.put("votes", storage.getPlayCampaignLootVoteDistribution(campaignId, lootId));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignNpcCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String npcId = (String) req.get("npc_id");
            String name = (String) req.get("name");
            String agenda = (String) req.get("agenda");
            String publicStatus = (String) req.get("public_status");
            if (npcId == null || npcId.isEmpty() || name == null || name.isEmpty() || agenda == null || agenda.isEmpty() || publicStatus == null || publicStatus.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignNpc(campaignId, npcId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NPC_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignNpc(campaignId, npcId, name, agenda, publicStatus)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NPC_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("npc_id", npcId);
            res.put("name", name);
            res.put("agenda", agenda);
            res.put("public_status", publicStatus);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignNpcUpdateAgenda(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> npc = storage.getPlayCampaignNpc(campaignId, npcId);
        if (npc == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String agenda = (String) req.get("agenda");
            String publicStatus = (String) req.get("public_status");
            if (agenda == null || agenda.isEmpty() || publicStatus == null || publicStatus.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!storage.updatePlayCampaignNpc(campaignId, npcId, agenda, publicStatus)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("npc_id", npcId);
            res.put("name", npc.get("name"));
            res.put("agenda", agenda);
            res.put("public_status", publicStatus);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignNpcGet(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> npc = storage.getPlayCampaignNpc(campaignId, npcId);
        if (npc == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("npc_id", npc.get("npc_id"));
        res.put("name", npc.get("name"));
        if (isOwner) {
            res.put("agenda", npc.get("agenda"));
        }
        res.put("public_status", npc.get("public_status"));
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignFactionCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String factionId = (String) req.get("faction_id");
            String name = (String) req.get("name");
            if (factionId == null || factionId.isEmpty() || name == null || name.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignFaction(campaignId, factionId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_FACTION_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignFaction(campaignId, factionId, name)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_FACTION_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("faction_id", factionId);
            res.put("name", name);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignFactionReputationPost(HttpExchange exchange, String campaignId, String factionId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignFaction(campaignId, factionId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String characterId = (String) req.get("character_id");
            Object deltaObj = req.get("delta");
            String reason = (String) req.get("reason");
            if (characterId == null || characterId.isEmpty() || reason == null || reason.isEmpty() || deltaObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignMemberByCharacterId(campaignId, characterId) == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            int delta = JsonUtils.toInt(deltaObj);
            if (delta == 0 || delta < -25 || delta > 25) {
                throw new RuntimeException("Invalid delta");
            }
            Map<String, Object> res = storage.insertPlayCampaignReputationChange(campaignId, factionId, characterId, delta, reason);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignFactionReputationGet(HttpExchange exchange, String campaignId, String factionId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignFaction(campaignId, factionId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String filterCharacterId = null;
        if (!isOwner) {
            Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
            if (member != null) {
                filterCharacterId = (String) member.get("character_id");
            }
        }
        List<Map<String, Object>> entries = storage.listPlayCampaignReputationHistory(campaignId, factionId, filterCharacterId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("faction_id", factionId);
        res.put("entries", entries);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignNpcDialogueCreate(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignNpc(campaignId, npcId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String dialogueId = (String) req.get("dialogue_id");
            String speaker = (String) req.get("speaker");
            String text = (String) req.get("text");
            String visibility = (String) req.get("visibility");
            if (dialogueId == null || dialogueId.isEmpty() || speaker == null || speaker.isEmpty() || text == null || text.isEmpty() || visibility == null || visibility.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!"public".equals(visibility) && !"private".equals(visibility)) {
                throw new RuntimeException("Invalid visibility");
            }
            if (!storage.insertPlayCampaignNpcDialogue(campaignId, npcId, dialogueId, speaker, text, visibility)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DIALOGUE_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("dialogue_id", dialogueId);
            res.put("speaker", speaker);
            res.put("text", text);
            res.put("visibility", visibility);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignNpcDialogueGet(HttpExchange exchange, String campaignId, String npcId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignNpc(campaignId, npcId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        List<Map<String, Object>> entries = storage.listPlayCampaignNpcDialogue(campaignId, npcId);
        if (!isOwner) {
            List<Map<String, Object>> filtered = new ArrayList<>();
            for (Map<String, Object> entry : entries) {
                if ("public".equals(entry.get("visibility"))) {
                    filtered.add(entry);
                }
            }
            entries = filtered;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("npc_id", npcId);
        res.put("entries", entries);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignRelationshipCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String sourceId = (String) req.get("source_id");
            String targetId = (String) req.get("target_id");
            String kind = (String) req.get("kind");
            Object scoreObj = req.get("score");
            if (sourceId == null || sourceId.isEmpty() || targetId == null || targetId.isEmpty() || kind == null || kind.isEmpty() || scoreObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (sourceId.equals(targetId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            int score = JsonUtils.toInt(scoreObj);
            if (score < -100 || score > 100) throw new RuntimeException("Score out of range");
            if (!storage.isPlayCampaignEntity(campaignId, sourceId) || !storage.isPlayCampaignEntity(campaignId, targetId)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            if (!storage.insertPlayCampaignRelationship(campaignId, sourceId, targetId, kind, score)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_RELATIONSHIP_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("source_id", sourceId);
            res.put("target_id", targetId);
            res.put("kind", kind);
            res.put("score", score);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRelationshipUpdate(HttpExchange exchange, String campaignId, String sourceId, String targetId, String kind) throws IOException {
        if (!requireMethod(exchange, "PUT")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignRelationship(campaignId, sourceId, targetId, kind) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object scoreObj = req.get("score");
            if (scoreObj == null) throw new RuntimeException("Missing score");
            int score = JsonUtils.toInt(scoreObj);
            if (score < -100 || score > 100) throw new RuntimeException("Score out of range");
            if (!storage.updatePlayCampaignRelationship(campaignId, sourceId, targetId, kind, score)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("source_id", sourceId);
            res.put("target_id", targetId);
            res.put("kind", kind);
            res.put("score", score);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRelationshipList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> edges = storage.listPlayCampaignRelationships(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("edges", edges);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignClueCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String clueId = (String) req.get("clue_id");
            String text = (String) req.get("text");
            String audience = (String) req.get("audience");
            if (clueId == null || clueId.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!"character".equals(audience) && !"party".equals(audience) && !"hidden".equals(audience)) {
                throw new RuntimeException("Invalid audience");
            }
            String characterId = (String) req.get("character_id");
            if ("character".equals(audience)) {
                if (characterId == null || characterId.isEmpty()) {
                    throw new RuntimeException("Missing character_id");
                }
                if (storage.getPlayCampaignMemberByCharacterId(campaignId, characterId) == null) {
                    HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                    return;
                }
            } else {
                if (characterId != null) {
                    throw new RuntimeException("character_id not allowed for this audience");
                }
            }
            if (storage.getPlayCampaignClue(campaignId, clueId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CLUE_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignClue(campaignId, clueId, text, audience, characterId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CLUE_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("clue_id", clueId);
            res.put("text", text);
            res.put("audience", audience);
            if ("character".equals(audience)) {
                res.put("character_id", characterId);
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignClueList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> clues = storage.listPlayCampaignClues(campaignId);
        if (!isOwner) {
            String viewerCharacterId = null;
            Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
            if (member != null) {
                viewerCharacterId = (String) member.get("character_id");
            }
            List<Map<String, Object>> filtered = new ArrayList<>();
            for (Map<String, Object> clue : clues) {
                String audience = (String) clue.get("audience");
                if ("party".equals(audience)) {
                    filtered.add(clue);
                } else if ("character".equals(audience)) {
                    Object clueCharacterId = clue.get("character_id");
                    if (viewerCharacterId != null && viewerCharacterId.equals(clueCharacterId)) {
                        filtered.add(clue);
                    }
                }
            }
            clues = filtered;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("clues", clues);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignQuestCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String questId = (String) req.get("quest_id");
            String title = (String) req.get("title");
            Object depsObj = req.get("depends_on");
            if (questId == null || questId.isEmpty() || title == null || title.isEmpty() || depsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!(depsObj instanceof List)) {
                throw new RuntimeException("depends_on not array");
            }
            List<?> depsRaw = (List<?>) depsObj;
            Set<String> seen = new HashSet<>();
            List<String> deps = new ArrayList<>();
            for (Object o : depsRaw) {
                if (!(o instanceof String)) throw new RuntimeException("non-string dependency");
                String dep = (String) o;
                if (dep.isEmpty()) throw new RuntimeException("empty dependency");
                if (dep.equals(questId)) throw new RuntimeException("self dependency");
                if (!seen.add(dep)) throw new RuntimeException("duplicate dependency");
                if (!storage.playCampaignQuestExists(campaignId, dep)) {
                    HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                    return;
                }
                deps.add(dep);
            }
            if (storage.playCampaignQuestExists(campaignId, questId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_QUEST_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignQuest(campaignId, questId, title, deps)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_QUEST_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("quest_id", questId);
            res.put("title", title);
            res.put("depends_on", deps);
            res.put("state", "locked");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignQuestStateUpdate(HttpExchange exchange, String campaignId, String questId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> quest = storage.getPlayCampaignQuest(campaignId, questId);
        if (quest == null) {
            notFound(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String state = (String) req.get("state");
            if (!"active".equals(state) && !"completed".equals(state)) {
                throw new RuntimeException("Invalid state");
            }
            String current = (String) quest.get("state");
            if ("locked".equals(current)) {
                if (!"active".equals(state)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                    return;
                }
                if (!storage.arePlayCampaignQuestDependenciesCompleted(campaignId, questId)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                    return;
                }
            } else if ("active".equals(current)) {
                if (!"completed".equals(state)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                    return;
                }
            } else {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                return;
            }
            if (!storage.updatePlayCampaignQuestState(campaignId, questId, state)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                return;
            }
            Map<String, Object> res = storage.getPlayCampaignQuest(campaignId, questId);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignQuestList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> quests = storage.listPlayCampaignQuests(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("quests", quests);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignQuestRewardsConfigure(HttpExchange exchange, String campaignId, String questId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> quest = storage.getPlayCampaignQuest(campaignId, questId);
        if (quest == null) {
            notFound(exchange);
            return;
        }
        String state = (String) quest.get("state");
        if (!"locked".equals(state) && !"active".equals(state)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object xpObj = req.get("xp");
            Object itemsObj = req.get("items");
            if (xpObj == null || itemsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int xp = JsonUtils.toInt(xpObj);
            if (xp < 0) {
                throw new RuntimeException("Negative xp");
            }
            if (!(itemsObj instanceof Map)) {
                throw new RuntimeException("items not object");
            }
            Map<?, ?> itemsRaw = (Map<?, ?>) itemsObj;
            Map<String, Integer> items = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : itemsRaw.entrySet()) {
                String itemId = entry.getKey().toString();
                int quantity = JsonUtils.toInt(entry.getValue());
                if (quantity <= 0) {
                    throw new RuntimeException("Non-positive quantity");
                }
                if (storage.getItem(itemId) == null) {
                    HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                    return;
                }
                items.put(itemId, quantity);
            }
            if (!storage.configurePlayCampaignQuestRewards(campaignId, questId, xp, items)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
                return;
            }
            Map<String, Object> res = storage.getPlayCampaignQuest(campaignId, questId);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignQuestRewardsAward(HttpExchange exchange, String campaignId, String questId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> quest = storage.getPlayCampaignQuest(campaignId, questId);
        if (quest == null) {
            notFound(exchange);
            return;
        }
        if (!"completed".equals(quest.get("state"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
            return;
        }
        if (!storage.arePlayCampaignQuestRewardsConfigured(campaignId, questId)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
            return;
        }
        if (storage.arePlayCampaignQuestRewardsAwarded(campaignId, questId)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_REWARDS_ALREADY_AWARDED);
            return;
        }
        if (!storage.awardPlayCampaignQuestRewards(campaignId, questId)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVALID_QUEST_TRANSITION);
            return;
        }
        Map<String, Object> config = storage.getPlayCampaignQuestRewardConfig(campaignId, questId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("quest_id", questId);
        res.put("awarded", true);
        res.put("xp", config.get("xp"));
        res.put("items", config.get("items"));
        HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterRewardsGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignMemberByCharacterId(campaignId, charId) == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = storage.getPlayCampaignCharacterQuestRewards(campaignId, charId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSettlementCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String settlementId = (String) req.get("settlement_id");
            String name = (String) req.get("name");
            Object servicesObj = req.get("services");
            String availability = (String) req.get("availability");
            if (settlementId == null || settlementId.isEmpty() || name == null || name.isEmpty() || availability == null || availability.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            List<String> services = parseSettlementServices(servicesObj);
            if (!isValidAvailability(availability)) throw new RuntimeException("Invalid availability");
            String servicesJson = JsonUtils.toJson(services);
            int sortOrder = storage.getNextPlayCampaignSettlementSortOrder(campaignId);
            if (storage.getPlayCampaignSettlement(campaignId, settlementId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SETTLEMENT_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignSettlement(campaignId, settlementId, name, servicesJson, availability, sortOrder)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SETTLEMENT_EXISTS);
                return;
            }
            Map<String, Object> res = settlementResponse(settlementId, name, services, availability, new ArrayList<String>());
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSettlementUpdate(HttpExchange exchange, String campaignId, String settlementId) throws IOException {
        if (!requireMethod(exchange, "PUT")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> existing = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (existing == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String name = (String) req.get("name");
            Object servicesObj = req.get("services");
            String availability = (String) req.get("availability");
            if (name == null || name.isEmpty() || availability == null || availability.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            List<String> services = parseSettlementServices(servicesObj);
            if (!isValidAvailability(availability)) throw new RuntimeException("Invalid availability");
            String servicesJson = JsonUtils.toJson(services);
            if (!storage.updatePlayCampaignSettlement(campaignId, settlementId, name, servicesJson, availability)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            List<String> discoveredBy = storage.listPlayCampaignSettlementDiscoveries(campaignId, settlementId);
            Map<String, Object> res = settlementResponse(settlementId, name, services, availability, discoveredBy);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSettlementDiscover(HttpExchange exchange, String campaignId, String settlementId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        if (isOwner) {
            forbidden(exchange);
            return;
        }
        if (!"player".equals(user.role) || !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settlement = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (settlement == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
        String characterId = member == null ? null : (String) member.get("character_id");
        if (characterId == null) {
            forbidden(exchange);
            return;
        }
        List<String> discoveredBy = storage.listPlayCampaignSettlementDiscoveries(campaignId, settlementId);
        boolean alreadyDiscovered = discoveredBy.contains(characterId);
        if (!alreadyDiscovered) {
            storage.insertPlayCampaignSettlementDiscovery(campaignId, settlementId, characterId);
            discoveredBy = storage.listPlayCampaignSettlementDiscoveries(campaignId, settlementId);
        }
        List<String> filteredDiscoveredBy = new ArrayList<>();
        filteredDiscoveredBy.add(characterId);
        Map<String, Object> res = settlementResponse(settlementId, (String) settlement.get("name"), (List<String>) settlement.get("services"), (String) settlement.get("availability"), filteredDiscoveredBy);
        HttpSupport.sendResponse(exchange, alreadyDiscovered ? 200 : 201, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSettlementList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        String viewerCharacterId = null;
        if (!isOwner) {
            Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
            if (member != null) {
                viewerCharacterId = (String) member.get("character_id");
            }
        }
        List<Map<String, Object>> settlements = storage.listPlayCampaignSettlements(campaignId);
        List<Map<String, Object>> resList = new ArrayList<>();
        for (Map<String, Object> settlement : settlements) {
            String settlementId = (String) settlement.get("settlement_id");
            List<String> discoveredBy = storage.listPlayCampaignSettlementDiscoveries(campaignId, settlementId);
            if (!isOwner) {
                if (viewerCharacterId == null || !discoveredBy.contains(viewerCharacterId)) {
                    continue;
                }
                List<String> filtered = new ArrayList<>();
                filtered.add(viewerCharacterId);
                discoveredBy = filtered;
            }
            Map<String, Object> s = settlementResponse(settlementId, (String) settlement.get("name"), (List<String>) settlement.get("services"), (String) settlement.get("availability"), discoveredBy);
            resList.add(s);
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("settlements", resList);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private List<String> parseSettlementServices(Object servicesObj) {
        if (!(servicesObj instanceof List)) throw new RuntimeException("services not list");
        List<?> raw = (List<?>) servicesObj;
        if (raw.isEmpty()) throw new RuntimeException("services empty");
        List<String> services = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object o : raw) {
            if (!(o instanceof String)) throw new RuntimeException("service not string");
            String s = ((String) o).trim();
            if (s.isEmpty()) throw new RuntimeException("empty service");
            if (!seen.add(s)) throw new RuntimeException("duplicate service");
            services.add(s);
        }
        return services;
    }

    private boolean isValidAvailability(String availability) {
        return "open".equals(availability) || "limited".equals(availability) || "closed".equals(availability);
    }

    private Map<String, Object> settlementResponse(String settlementId, String name, List<String> services, String availability, List<String> discoveredBy) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("settlement_id", settlementId);
        res.put("name", name);
        res.put("services", services);
        res.put("availability", availability);
        res.put("discovered_by", discoveredBy);
        return res;
    }

    private void handlePlayCampaignShopCreate(HttpExchange exchange, String campaignId, String settlementId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settlement = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (settlement == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String shopId = (String) req.get("shop_id");
            String name = (String) req.get("name");
            Object stockObj = req.get("stock");
            Object buyPriceObj = req.get("buy_price");
            Object sellPriceObj = req.get("sell_price");
            if (shopId == null || shopId.isEmpty() || name == null || name.isEmpty() || stockObj == null || buyPriceObj == null || sellPriceObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!(stockObj instanceof Map)) throw new RuntimeException("stock not object");
            @SuppressWarnings("unchecked")
            Map<String, Object> stockRaw = (Map<String, Object>) stockObj;
            if (stockRaw.isEmpty()) throw new RuntimeException("stock empty");
            Map<String, Object> stock = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : stockRaw.entrySet()) {
                String itemId = entry.getKey();
                if (itemId == null || itemId.isEmpty() || !isValidCatalogItemId(itemId)) {
                    throw new RuntimeException("Invalid stock item");
                }
                int qty = JsonUtils.toInt(entry.getValue());
                if (qty <= 0) throw new RuntimeException("Non-positive stock quantity");
                stock.put(itemId, qty);
            }
            int buyPrice = JsonUtils.toInt(buyPriceObj);
            int sellPrice = JsonUtils.toInt(sellPriceObj);
            if (buyPrice <= 0 || sellPrice < 0) throw new RuntimeException("Invalid price");
            if (storage.getPlayCampaignShop(campaignId, settlementId, shopId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SHOP_EXISTS);
                return;
            }
            String stockJson = JsonUtils.toJson(stock);
            if (!storage.insertPlayCampaignShop(campaignId, settlementId, shopId, name, stockJson, buyPrice, sellPrice)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SHOP_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("shop_id", shopId);
            res.put("name", name);
            res.put("stock", stock);
            res.put("buy_price", buyPrice);
            res.put("sell_price", sellPrice);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignShopGet(HttpExchange exchange, String campaignId, String settlementId, String shopId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settlement = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (settlement == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        if (!isOwner) {
            Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
            String characterId = member == null ? null : (String) member.get("character_id");
            List<String> discoveredBy = storage.listPlayCampaignSettlementDiscoveries(campaignId, settlementId);
            if (characterId == null || !discoveredBy.contains(characterId)) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
        }
        Map<String, Object> shop = storage.getPlayCampaignShop(campaignId, settlementId, shopId);
        if (shop == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(shop));
    }

    private void handlePlayCampaignShopBuy(HttpExchange exchange, String campaignId, String settlementId, String shopId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"player".equals(user.role) || !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settlement = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (settlement == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> shop = storage.getPlayCampaignShop(campaignId, settlementId, shopId);
        if (shop == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String characterId = (String) req.get("character_id");
            String itemId = (String) req.get("item_id");
            Object quantityObj = req.get("quantity");
            if (characterId == null || characterId.isEmpty() || itemId == null || itemId.isEmpty() || quantityObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int quantity = JsonUtils.toInt(quantityObj);
            if (quantity <= 0 || !isValidCatalogItemId(itemId)) {
                throw new RuntimeException("Invalid item or quantity");
            }
            Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, characterId);
            if (character == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            String owner = storage.getPlayCampaignCharacterOwner(campaignId, characterId);
            if (owner == null || !owner.equals(user.username)) {
                forbidden(exchange);
                return;
            }
            Map<String, Object> result = storage.buyFromPlayCampaignShop(campaignId, settlementId, shopId, characterId, itemId, quantity);
            if (result == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            if (result.containsKey("error")) {
                String error = (String) result.get("error");
                if ("insufficient_stock".equals(error)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_SHOP_INSUFFICIENT_STOCK);
                } else {
                    HttpSupport.sendResponse(exchange, 409, ERROR_SHOP_INSUFFICIENT_FUNDS);
                }
                return;
            }
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(result));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignShopSell(HttpExchange exchange, String campaignId, String settlementId, String shopId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"player".equals(user.role) || !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settlement = storage.getPlayCampaignSettlement(campaignId, settlementId);
        if (settlement == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> shop = storage.getPlayCampaignShop(campaignId, settlementId, shopId);
        if (shop == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String characterId = (String) req.get("character_id");
            String itemId = (String) req.get("item_id");
            Object quantityObj = req.get("quantity");
            if (characterId == null || characterId.isEmpty() || itemId == null || itemId.isEmpty() || quantityObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int quantity = JsonUtils.toInt(quantityObj);
            if (quantity <= 0 || !isValidCatalogItemId(itemId)) {
                throw new RuntimeException("Invalid item or quantity");
            }
            Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, characterId);
            if (character == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            String owner = storage.getPlayCampaignCharacterOwner(campaignId, characterId);
            if (owner == null || !owner.equals(user.username)) {
                forbidden(exchange);
                return;
            }
            Map<String, Object> result = storage.sellToPlayCampaignShop(campaignId, settlementId, shopId, characterId, itemId, quantity);
            if (result == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            if (result.containsKey("error")) {
                HttpSupport.sendResponse(exchange, 409, ERROR_SHOP_INSUFFICIENT_STOCK);
                return;
            }
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(result));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRecipeCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String recipeId = (String) req.get("recipe_id");
            String name = (String) req.get("name");
            Object ingredientsObj = req.get("ingredients");
            String outputItem = (String) req.get("output_item");
            Object outputQuantityObj = req.get("output_quantity");
            if (recipeId == null || recipeId.isEmpty() || name == null || name.isEmpty() || outputItem == null || outputItem.isEmpty() || outputQuantityObj == null || ingredientsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!(ingredientsObj instanceof Map)) throw new RuntimeException("ingredients not object");
            @SuppressWarnings("unchecked")
            Map<String, Object> ingredientsRaw = (Map<String, Object>) ingredientsObj;
            if (ingredientsRaw.isEmpty()) throw new RuntimeException("ingredients empty");
            Map<String, Object> ingredients = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : ingredientsRaw.entrySet()) {
                String itemId = entry.getKey();
                if (itemId == null || itemId.isEmpty() || !isValidCatalogItemId(itemId)) {
                    throw new RuntimeException("Invalid ingredient item");
                }
                int quantity = JsonUtils.toInt(entry.getValue());
                if (quantity <= 0) throw new RuntimeException("Non-positive ingredient quantity");
                ingredients.put(itemId, quantity);
            }
            if (!isValidCatalogItemId(outputItem)) {
                throw new RuntimeException("Invalid output item");
            }
            int outputQuantity = JsonUtils.toInt(outputQuantityObj);
            if (outputQuantity <= 0) throw new RuntimeException("Non-positive output quantity");
            if (storage.getPlayCampaignRecipe(campaignId, recipeId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_RECIPE_EXISTS);
                return;
            }
            int sortOrder = storage.getNextPlayCampaignRecipeSortOrder(campaignId);
            String ingredientsJson = JsonUtils.toJson(ingredients);
            if (!storage.insertPlayCampaignRecipe(campaignId, recipeId, name, outputItem, outputQuantity, ingredientsJson, sortOrder)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_RECIPE_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("recipe_id", recipeId);
            res.put("name", name);
            res.put("ingredients", ingredients);
            res.put("output_item", outputItem);
            res.put("output_quantity", outputQuantity);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRecipeList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> recipes = storage.listPlayCampaignRecipes(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("recipes", recipes);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignRecipeCraft(HttpExchange exchange, String campaignId, String recipeId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"player".equals(user.role) || !storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> recipe = storage.getPlayCampaignRecipe(campaignId, recipeId);
        if (recipe == null) {
            notFound(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String characterId = (String) req.get("character_id");
            if (characterId == null || characterId.isEmpty()) throw new RuntimeException("Missing character_id");
            Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, characterId);
            if (character == null) {
                notFound(exchange);
                return;
            }
            String owner = storage.getPlayCampaignCharacterOwner(campaignId, characterId);
            if (owner == null || !owner.equals(user.username)) {
                forbidden(exchange);
                return;
            }
            Map<String, Object> result = storage.craftPlayCampaignRecipe(campaignId, recipeId, characterId);
            if (result == null) {
                notFound(exchange);
                return;
            }
            if (result.containsKey("error")) {
                HttpSupport.sendResponse(exchange, 409, ERROR_RECIPE_INSUFFICIENT_INGREDIENTS);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(result));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignDowntimeActivityCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String activityId = (String) req.get("activity_id");
            String name = (String) req.get("name");
            Object cyclesObj = req.get("cycles_required");
            if (activityId == null || activityId.isEmpty() || name == null || name.isEmpty() || cyclesObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int cyclesRequired = JsonUtils.toInt(cyclesObj);
            if (cyclesRequired < 1 || cyclesRequired > 10) throw new RuntimeException("Invalid cycles_required");
            if (storage.getPlayCampaignDowntimeActivity(campaignId, activityId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DOWNTIME_ACTIVITY_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignDowntimeActivity(campaignId, activityId, name, cyclesRequired)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DOWNTIME_ACTIVITY_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("activity_id", activityId);
            res.put("name", name);
            res.put("cycles_required", cyclesRequired);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignDowntimeAllocationCreate(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null || !owner.equals(user.username)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String activityId = (String) req.get("activity_id");
            if (activityId == null || activityId.isEmpty()) throw new RuntimeException("Missing activity_id");
            Map<String, Object> activity = storage.getPlayCampaignDowntimeActivity(campaignId, activityId);
            if (activity == null) {
                HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
                return;
            }
            if (storage.getPlayCampaignDowntimeAllocation(campaignId, charId, activityId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DOWNTIME_ALLOCATION_EXISTS);
                return;
            }
            if (!storage.insertPlayCampaignDowntimeAllocation(campaignId, charId, activityId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DOWNTIME_ALLOCATION_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", charId);
            res.put("activity_id", activityId);
            res.put("cycles_completed", 0);
            res.put("completions", 0);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignDowntimeAllocationProgress(HttpExchange exchange, String campaignId, String charId, String activityId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        if (owner == null || !owner.equals(user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> activity = storage.getPlayCampaignDowntimeActivity(campaignId, activityId);
        if (activity == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> allocation = storage.getPlayCampaignDowntimeAllocation(campaignId, charId, activityId);
        if (allocation == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> res = storage.progressPlayCampaignDowntimeAllocation(campaignId, charId, activityId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignDowntimeAllocationGet(HttpExchange exchange, String campaignId, String charId, String activityId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (character == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> activity = storage.getPlayCampaignDowntimeActivity(campaignId, activityId);
        if (activity == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        Map<String, Object> allocation = storage.getPlayCampaignDowntimeAllocation(campaignId, charId, activityId);
        if (allocation == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(allocation));
    }

    private void handlePlayCampaignSessionZeroPut(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        if (!"lobby".equals(campaign.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_NOT_IN_LOBBY);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String rules = (String) req.get("rules");
            String tone = (String) req.get("tone");
            Object consentObj = req.get("consent");
            if (rules == null || rules.isEmpty() || tone == null || tone.isEmpty()) {
                throw new RuntimeException("Missing or empty rules/tone");
            }
            if (!(consentObj instanceof List)) {
                throw new RuntimeException("consent not list");
            }
            List<?> consentRaw = (List<?>) consentObj;
            if (consentRaw.isEmpty()) {
                throw new RuntimeException("consent empty");
            }
            List<String> consent = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (Object o : consentRaw) {
                if (!(o instanceof String)) throw new RuntimeException("non-string consent");
                String s = (String) o;
                if (s.isEmpty()) throw new RuntimeException("empty consent");
                if (!seen.add(s)) throw new RuntimeException("duplicate consent");
                consent.add(s);
            }
            if (!storage.setPlayCampaignSessionZero(campaignId, rules, tone, consent)) {
                throw new RuntimeException("Failed to save session-zero settings");
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("rules", rules);
            res.put("tone", tone);
            res.put("consent", consent);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSessionZeroGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> settings = storage.getPlayCampaignSessionZero(campaignId);
        if (settings == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(settings));
    }

    private void handlePlayCampaignContentCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String contentId = (String) req.get("content_id");
            String kind = (String) req.get("kind");
            String text = (String) req.get("text");
            Object tagsObj = req.get("tags");
            if (contentId == null || contentId.isEmpty() || kind == null || kind.isEmpty() || text == null || text.isEmpty() || tagsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!(tagsObj instanceof List)) throw new RuntimeException("Invalid tags");
            List<?> tagsRaw = (List<?>) tagsObj;
            if (tagsRaw.isEmpty()) throw new RuntimeException("Empty tags");
            List<String> tags = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (Object o : tagsRaw) {
                if (!(o instanceof String)) throw new RuntimeException("Non-string tag");
                String tag = (String) o;
                if (tag.isEmpty()) throw new RuntimeException("Empty tag");
                if (!seen.add(tag)) throw new RuntimeException("Duplicate tag");
                tags.add(tag);
            }
            if (storage.playCampaignContentExists(campaignId, contentId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONTENT_EXISTS);
                return;
            }
            int sortOrder = storage.getNextPlayCampaignContentSortOrder(campaignId);
            if (!storage.insertPlayCampaignContent(campaignId, contentId, kind, text, JsonUtils.toJson(tags), sortOrder)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONTENT_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("content_id", contentId);
            res.put("kind", kind);
            res.put("text", text);
            res.put("tags", tags);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignContentTagsPut(HttpExchange exchange, String campaignId, String contentId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> content = storage.getPlayCampaignContent(campaignId, contentId);
        if (content == null) {
            notFound(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object tagsObj = req.get("tags");
            if (tagsObj == null) throw new RuntimeException("Missing tags");
            if (!(tagsObj instanceof List)) throw new RuntimeException("Invalid tags");
            List<?> tagsRaw = (List<?>) tagsObj;
            List<String> tags = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (Object o : tagsRaw) {
                if (!(o instanceof String)) throw new RuntimeException("Non-string tag");
                String tag = (String) o;
                if (tag.isEmpty()) throw new RuntimeException("Empty tag");
                if (!seen.add(tag)) throw new RuntimeException("Duplicate tag");
                tags.add(tag);
            }
            if (!storage.updatePlayCampaignContentTags(campaignId, contentId, JsonUtils.toJson(tags))) {
                notFound(exchange);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("content_id", content.get("content_id"));
            res.put("kind", content.get("kind"));
            res.put("text", content.get("text"));
            res.put("tags", tags);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignContentList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        String excludeTag = null;
        String query = exchange.getRequestURI().getQuery();
        if (query != null && !query.isEmpty()) {
            for (String pair : query.split("&")) {
                int eq = pair.indexOf('=');
                if (eq >= 0 && "exclude_tag".equals(pair.substring(0, eq))) {
                    excludeTag = URLDecoder.decode(pair.substring(eq + 1), StandardCharsets.UTF_8);
                    break;
                }
            }
        }
        if (excludeTag != null && excludeTag.isEmpty()) {
            HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
            return;
        }
        List<Map<String, Object>> allContent = storage.listPlayCampaignContent(campaignId);
        List<Map<String, Object>> filtered = new ArrayList<>();
        for (Map<String, Object> item : allContent) {
            @SuppressWarnings("unchecked")
            List<String> tags = (List<String>) item.get("tags");
            if (isOwner || excludeTag == null || !tags.contains(excludeTag)) {
                filtered.add(item);
            }
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("content", filtered);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private Map<String, Object> activeCombatantJson(List<Map<String, Object>> combatants, int turnIndex) {
        if (combatants == null || combatants.isEmpty() || turnIndex < 0 || turnIndex >= combatants.size()) {
            return null;
        }
        Map<String, Object> c = combatants.get(turnIndex);
        Map<String, Object> active = new LinkedHashMap<>();
        active.put("name", c.get("name"));
        active.put("kind", c.get("kind"));
        active.put("initiative", JsonUtils.toInt(c.get("initiative")));
        return active;
    }

    private void handlePlayCampaignNotesCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String noteId = (String) req.get("note_id");
            String text = (String) req.get("text");
            String visibility = (String) req.get("visibility");
            if (noteId == null || noteId.isEmpty() || text == null || text.isEmpty() || visibility == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!"private".equals(visibility) && !"party".equals(visibility)) {
                throw new RuntimeException("Invalid visibility");
            }
            if (storage.playCampaignNoteExists(campaignId, noteId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NOTE_EXISTS);
                return;
            }
            int sortOrder = storage.getNextPlayCampaignNoteSortOrder(campaignId);
            if (!storage.insertPlayCampaignNote(campaignId, noteId, text, visibility, user.username, sortOrder)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_NOTE_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("note_id", noteId);
            res.put("text", text);
            res.put("visibility", visibility);
            res.put("owner", user.username);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignNotesList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> notes = storage.listPlayCampaignNotes(campaignId);
        List<Map<String, Object>> filtered = new ArrayList<>();
        for (Map<String, Object> note : notes) {
            if (isOwner || "party".equals(note.get("visibility")) || user.username.equals(note.get("owner"))) {
                filtered.add(note);
            }
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("notes", filtered);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignNoteGet(HttpExchange exchange, String campaignId, String noteId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> note = storage.getPlayCampaignNote(campaignId, noteId);
        if (note == null) {
            notFound(exchange);
            return;
        }
        if ("private".equals(note.get("visibility")) && !user.username.equals(note.get("owner")) && !isOwner) {
            forbidden(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(note));
    }

    private void handlePlayCampaignNotePut(HttpExchange exchange, String campaignId, String noteId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> note = storage.getPlayCampaignNote(campaignId, noteId);
        if (note == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(note.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String text = (String) req.get("text");
            String visibility = (String) req.get("visibility");
            if (text == null || text.isEmpty() || visibility == null || (!"private".equals(visibility) && !"party".equals(visibility))) {
                throw new RuntimeException("Invalid fields");
            }
            if (!storage.updatePlayCampaignNote(campaignId, noteId, text, visibility)) {
                notFound(exchange);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("note_id", noteId);
            res.put("text", text);
            res.put("visibility", visibility);
            res.put("owner", note.get("owner"));
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignWhispersCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!storage.isPlayCampaignMember(campaignId, user.username)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
        if (member == null || member.get("character_id") == null) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String whisperId = (String) req.get("whisper_id");
            String toCharacterId = (String) req.get("to_character_id");
            String text = (String) req.get("text");
            if (whisperId == null || whisperId.isEmpty() || toCharacterId == null || toCharacterId.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            Map<String, Object> toMember = storage.getPlayCampaignMemberByCharacterId(campaignId, toCharacterId);
            if (toMember == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (storage.playCampaignWhisperExists(campaignId, whisperId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WHISPER_EXISTS);
                return;
            }
            String fromCharacterId = (String) member.get("character_id");
            if (!storage.insertPlayCampaignWhisper(campaignId, whisperId, fromCharacterId, toCharacterId, text)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_WHISPER_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("whisper_id", whisperId);
            res.put("from_character_id", fromCharacterId);
            res.put("to_character_id", toCharacterId);
            res.put("text", text);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignWhispersList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> whispers = storage.listPlayCampaignWhispers(campaignId);
        if (!isOwner) {
            Map<String, Object> member = storage.getPlayCampaignMember(campaignId, user.username);
            String characterId = member == null ? null : (String) member.get("character_id");
            List<Map<String, Object>> filtered = new ArrayList<>();
            for (Map<String, Object> whisper : whispers) {
                if (characterId != null && (characterId.equals(whisper.get("from_character_id")) || characterId.equals(whisper.get("to_character_id")))) {
                    filtered.add(whisper);
                }
            }
            whispers = filtered;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("whispers", whispers);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignCharacterSheetGet(HttpExchange exchange, String campaignId, String charId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        String owner = storage.getPlayCampaignCharacterOwner(campaignId, charId);
        Map<String, Object> character = storage.getPlayCampaignMemberByCharacterId(campaignId, charId);
        if (owner == null || character == null) {
            notFound(exchange);
            return;
        }
        if (!isOwner && !user.username.equals(owner)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("character_id", charId);
        res.put("owner", owner);
        res.put("name", character == null ? "" : character.get("name"));
        res.put("class", character == null ? "" : character.get("class"));
        res.put("level", 1);
        res.put("proficiency_bonus", 2);
        res.put("hp_max", 10);
        res.put("armor_class", 10);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignInvitationCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String invitationId = (String) req.get("invitation_id");
            String username = (String) req.get("username");
            String characterId = (String) req.get("character_id");
            if (invitationId == null || invitationId.isEmpty() || username == null || username.isEmpty() || characterId == null || characterId.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.getPlayCampaignInvitation(campaignId, invitationId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVITATION_EXISTS);
                return;
            }
            if (storage.hasPendingPlayCampaignInvitationForUser(campaignId, username)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVITATION_EXISTS);
                return;
            }
            if (!isRegisteredPlayer(username)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (!storage.insertPlayCampaignInvitation(campaignId, invitationId, username, characterId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INVITATION_EXISTS);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("invitation_id", invitationId);
            res.put("username", username);
            res.put("character_id", characterId);
            res.put("status", "pending");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignInvitationAccept(HttpExchange exchange, String campaignId, String invitationId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        Map<String, Object> invitation = storage.getPlayCampaignInvitation(campaignId, invitationId);
        if (invitation == null) {
            notFound(exchange);
            return;
        }
        if (!user.username.equals(invitation.get("username"))) {
            forbidden(exchange);
            return;
        }
        if (!"pending".equals(invitation.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVITATION_ALREADY_ACCEPTED);
            return;
        }
        String characterId = (String) invitation.get("character_id");
        if (!storage.acceptPlayCampaignInvitation(campaignId, invitationId, user.username, characterId)) {
            HttpSupport.sendResponse(exchange, 409, ERROR_INVITATION_ALREADY_ACCEPTED);
            return;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("invitation_id", invitationId);
        res.put("username", user.username);
        res.put("character_id", characterId);
        res.put("status", "accepted");
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private boolean isRegisteredPlayer(String username) {
        User user = storage.getUser(username);
        return user != null && "player".equals(user.role);
    }

    private void handlePlayCampaignInvitationList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        boolean hasInvitation = storage.hasPlayCampaignInvitationForUser(campaignId, user.username);
        if (!isOwner && !isMember && !hasInvitation) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> invitations = storage.listPlayCampaignInvitations(campaignId);
        if (!isOwner) {
            List<Map<String, Object>> filtered = new ArrayList<>();
            for (Map<String, Object> inv : invitations) {
                if (user.username.equals(inv.get("username"))) {
                    filtered.add(inv);
                }
            }
            invitations = filtered;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("invitations", invitations);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignDelegationCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String target = (String) req.get("username");
            Object powersObj = req.get("powers");
            if (target == null || target.isEmpty() || !(powersObj instanceof List) || ((List<?>) powersObj).isEmpty()) {
                throw new RuntimeException("Invalid delegation payload");
            }
            Set<String> seen = new HashSet<>();
            List<String> powers = new ArrayList<>();
            for (Object o : (List<?>) powersObj) {
                if (!(o instanceof String)) throw new RuntimeException("Invalid power");
                String p = (String) o;
                if (!"narrate".equals(p)) throw new RuntimeException("Invalid power");
                if (!seen.add(p)) throw new RuntimeException("Duplicate power");
                powers.add(p);
            }
            if (!storage.isPlayCampaignMember(campaignId, target)) {
                badRequest(exchange);
                return;
            }
            Map<String, Object> res = storage.grantPlayCampaignDelegation(campaignId, target, powers);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_DELEGATION_EXISTS);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignDelegationRevoke(HttpExchange exchange, String campaignId, String username) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.revokePlayCampaignDelegation(campaignId, username);
        if (res == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignDelegationAudit(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> entries = storage.listPlayCampaignDelegationAudit(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("entries", entries);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignAuditEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String kind = (String) req.get("kind");
            String correlationId = (String) req.get("correlation_id");
            if (kind == null || kind.isEmpty() || correlationId == null || correlationId.isEmpty()) {
                throw new RuntimeException("Invalid audit payload");
            }
            String role = isOwner ? "DM" : "player";
            Map<String, Object> res = storage.createPlayCampaignAuditEvent(campaignId, user.username, role, kind, correlationId);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignAuditEventList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> entries = storage.listPlayCampaignAuditEvents(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("entries", entries);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignProjectionEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (isOwner || !isMember || !"player".equals(user.role)) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            String kind = (String) req.get("kind");
            if (eventId == null || eventId.isEmpty() || kind == null || (!"set-story".equals(kind) && !"increment-danger".equals(kind))) {
                throw new RuntimeException("Invalid projection event payload");
            }
            String value = null;
            if ("set-story".equals(kind)) {
                if (!req.containsKey("value")) throw new RuntimeException("Missing value");
                Object valueObj = req.get("value");
                if (!(valueObj instanceof String) || ((String) valueObj).isEmpty()) {
                    throw new RuntimeException("Invalid value");
                }
                value = (String) valueObj;
            } else if ("increment-danger".equals(kind)) {
                if (req.containsKey("value")) throw new RuntimeException("Value must be omitted");
            }
            if (storage.playCampaignProjectionEventExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_PROJECTION_EVENT_EXISTS);
                return;
            }
            Map<String, Object> res = storage.insertPlayCampaignProjectionEvent(campaignId, eventId, kind, value);
            storage.incrementPlayCampaignMetric(campaignId, "projection_events");
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignProjectionGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.buildPlayCampaignProjection(campaignId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignProjectionRebuild(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.buildPlayCampaignProjection(campaignId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignIdempotentEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        String idempotencyKey = exchange.getRequestHeaders().getFirst("Idempotency-Key");
        if (idempotencyKey == null || idempotencyKey.trim().isEmpty()) {
            badRequest(exchange);
            return;
        }
        idempotencyKey = idempotencyKey.trim();
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object eventIdObj = req.get("event_id");
            Object valueObj = req.get("value");
            if (!(eventIdObj instanceof String) || ((String) eventIdObj).isEmpty()
                    || !(valueObj instanceof String) || ((String) valueObj).isEmpty()) {
                throw new RuntimeException("Invalid idempotent event payload");
            }
            String eventId = (String) eventIdObj;
            String value = (String) valueObj;
            Map<String, Object> existing = storage.getPlayCampaignIdempotentEventByKey(campaignId, idempotencyKey);
            if (existing != null) {
                if (eventId.equals(existing.get("event_id")) && value.equals(existing.get("value"))) {
                    HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(existing));
                } else {
                    HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                }
                return;
            }
            if (storage.playCampaignIdempotentEventIdExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            Map<String, Object> res = storage.insertPlayCampaignIdempotentEvent(campaignId, eventId, value, idempotencyKey);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignIdempotentEventList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> events = storage.listPlayCampaignIdempotentEvents(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("events", events);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSafeTurnSubmit(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object submissionIdObj = req.get("submission_id");
            Object expectedTurnObj = req.get("expected_turn");
            Object actionObj = req.get("action");
            if (!(submissionIdObj instanceof String) || ((String) submissionIdObj).isEmpty()
                    || !(actionObj instanceof String) || ((String) actionObj).isEmpty()
                    || expectedTurnObj == null) {
                throw new RuntimeException("Invalid safe turn payload");
            }
            String submissionId = (String) submissionIdObj;
            String action = (String) actionObj;
            int expectedTurn = JsonUtils.toInt(expectedTurnObj);
            if (expectedTurn <= 0) throw new RuntimeException("Invalid expected_turn");
            Map<String, Object> result = storage.submitPlayCampaignSafeTurn(campaignId, submissionId, action, expectedTurn);
            String status = (String) result.get("status");
            if ("duplicate".equals(status)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            if ("stale".equals(status)) {
                int currentTurn = JsonUtils.toInt(result.get("current_turn"));
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("current_turn", currentTurn);
                HttpSupport.sendResponse(exchange, 409, JsonUtils.toJson(res));
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("submission_id", submissionId);
            res.put("action", action);
            res.put("accepted_turn", result.get("accepted_turn"));
            res.put("next_turn", result.get("next_turn"));
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSafeTurnList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        int currentTurn = storage.getPlayCampaignSafeTurnCurrent(campaignId);
        List<Map<String, Object>> accepted = storage.listPlayCampaignSafeTurns(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("current_turn", currentTurn);
        res.put("accepted", accepted);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignTransactionalTransferCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String fromCharacterId = (String) req.get("from_character_id");
            String toCharacterId = (String) req.get("to_character_id");
            Object amountObj = req.get("amount");
            Object simulateFailureObj = req.get("simulate_failure");
            if (fromCharacterId == null || fromCharacterId.isEmpty() || toCharacterId == null || toCharacterId.isEmpty() || amountObj == null || simulateFailureObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int amount = JsonUtils.toInt(amountObj);
            if (amount <= 0) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            if (fromCharacterId.equals(toCharacterId)) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            Map<String, Object> fromCharacter = storage.getPlayCampaignMemberByCharacterId(campaignId, fromCharacterId);
            Map<String, Object> toCharacter = storage.getPlayCampaignMemberByCharacterId(campaignId, toCharacterId);
            if (fromCharacter == null || toCharacter == null) {
                HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
                return;
            }
            String fromOwner = storage.getPlayCampaignCharacterOwner(campaignId, fromCharacterId);
            if (fromOwner == null || !fromOwner.equals(user.username)) {
                forbidden(exchange);
                return;
            }
            boolean simulateFailure = Boolean.TRUE.equals(simulateFailureObj);
            Map<String, Object> res = storage.executePlayCampaignTransactionalTransfer(campaignId, fromCharacterId, toCharacterId, amount, simulateFailure);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_INSUFFICIENT_GOLD);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            if ("simulated failure".equals(e.getMessage())) {
                HttpSupport.sendResponse(exchange, 500, "{\"error\":\"simulated failure\"}");
                return;
            }
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignTransactionalTransferList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> transfers = storage.listPlayCampaignTransactionalTransfers(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("transfers", transfers);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignExportCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.createPlayCampaignExport(campaignId);
        HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignExportList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> exports = storage.listPlayCampaignExports(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("exports", exports);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignExportGet(HttpExchange exchange, String campaignId, int version) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> snapshot = storage.getPlayCampaignExport(campaignId, version);
        if (snapshot == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(snapshot));
    }

    private void handlePlayCampaignImportCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object versionObj = req.get("version");
            String story = (String) req.get("story");
            String status = (String) req.get("status");
            if (versionObj == null || story == null || status == null) {
                throw new RuntimeException("Missing fields");
            }
            int version = JsonUtils.toInt(versionObj);
            if (version != 1) throw new RuntimeException("Invalid version");
            if (story.isEmpty()) throw new RuntimeException("Empty story");
            if (!"lobby".equals(status) && !"started".equals(status)) {
                throw new RuntimeException("Invalid status");
            }
            Map<String, Object> res = storage.createPlayCampaignImport(campaignId, version, story, status);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignImportStateGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> snapshot = storage.getPlayCampaignImport(campaignId);
        if (snapshot == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(snapshot));
    }

    private void handlePlayCampaignMigrationCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object versionObj = req.get("schema_version");
            String story = (String) req.get("story");
            if (versionObj == null || story == null) {
                throw new RuntimeException("Missing fields");
            }
            int schemaVersion = JsonUtils.toInt(versionObj);
            if (schemaVersion != 1) throw new RuntimeException("Invalid schema_version");
            if (story.isEmpty()) throw new RuntimeException("Empty story");
            String campaignName = (String) campaign.get("name");
            Storage.MigrationResult result = storage.createPlayCampaignMigration(campaignId, story, campaignName);
            int status = result.created ? 201 : 200;
            HttpSupport.sendResponse(exchange, status, JsonUtils.toJson(result.snapshot));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignMigrationStateGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> snapshot = storage.getPlayCampaignMigration(campaignId);
        if (snapshot == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(snapshot));
    }

    private void handlePlayCampaignSearchRecordCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String recordId = (String) req.get("record_id");
            String text = (String) req.get("text");
            if (recordId == null || text == null || recordId.isEmpty() || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!storage.insertPlayCampaignSearchRecord(campaignId, recordId, text)) {
                badRequest(exchange);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("record_id", recordId);
            res.put("text", text);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSearchRecordList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isDm = "dm".equals(user.role) && user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isDm && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            Map<String, String> params = parseQueryParams(exchange);
            String q = params.get("q");
            int limit = parseIntParam(params.get("limit"), 2, 1, 3);
            int cursor = parseIntParam(params.get("cursor"), 0, 0, Integer.MAX_VALUE);

            List<Map<String, Object>> all = storage.listPlayCampaignSearchRecords(campaignId);
            List<Map<String, Object>> filtered = new ArrayList<>();
            if (q != null && !q.isEmpty()) {
                String lowerQ = q.toLowerCase();
                for (Map<String, Object> record : all) {
                    String text = (String) record.get("text");
                    if (text != null && text.toLowerCase().contains(lowerQ)) {
                        filtered.add(record);
                    }
                }
            } else {
                filtered.addAll(all);
            }

            int total = filtered.size();
            int start = Math.min(cursor, total);
            int end = Math.min(start + limit, total);
            List<Map<String, Object>> page = new ArrayList<>();
            for (int i = start; i < end; i++) {
                page.add(filtered.get(i));
            }

            Integer nextCursor = end < total ? end : null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("records", page);
            res.put("next_cursor", nextCursor);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRateEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            if (eventId == null || eventId.isEmpty()) {
                throw new RuntimeException("Missing event_id");
            }
            int accepted = storage.countPlayCampaignRateEventsByActor(campaignId, user.username);
            if (accepted >= 2) {
                storage.incrementPlayCampaignMetric(campaignId, "rejected_rate_events");
                HttpSupport.sendResponse(exchange, 429, ERROR_RATE_LIMIT_EXCEEDED);
                return;
            }
            if (storage.playCampaignRateEventExists(campaignId, eventId)) {
                badRequest(exchange);
                return;
            }
            Map<String, Object> event = storage.insertPlayCampaignRateEvent(campaignId, eventId, user.username);
            if (event == null) {
                badRequest(exchange);
                return;
            }
            storage.incrementPlayCampaignMetric(campaignId, "accepted_rate_events");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("actor", user.username);
            res.put("remaining", 2 - (accepted + 1));
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRateEventList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> events = storage.listPlayCampaignRateEvents(campaignId);
        int accepted = storage.countPlayCampaignRateEventsByActor(campaignId, user.username);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("events", events);
        res.put("remaining", 2 - accepted);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignMetricsGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> res = storage.getPlayCampaignMetrics(campaignId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignServiceMode(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        if (!"dm".equals(user.role)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object maintenanceObj = req.get("maintenance");
            if (!(maintenanceObj instanceof Boolean)) {
                throw new RuntimeException("Invalid maintenance value");
            }
            boolean maintenance = (Boolean) maintenanceObj;
            ServiceState.setMaintenance(maintenance);
            String response = maintenance ? "{\"maintenance\":true}" : "{\"maintenance\":false}";
            HttpSupport.sendResponse(exchange, 200, response);
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignBackupCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            HttpSupport.readBody(exchange);
        } catch (RuntimeException e) {
            badRequest(exchange);
            return;
        }
        Map<String, Object> res = storage.createPlayCampaignBackup(campaignId);
        if (res == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignBackupList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> backups = storage.listPlayCampaignBackups(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("backups", backups);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignBackupRestore(HttpExchange exchange, String campaignId, String backupId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            HttpSupport.readBody(exchange);
        } catch (RuntimeException e) {
            badRequest(exchange);
            return;
        }
        Map<String, Object> res = storage.restorePlayCampaignBackup(campaignId, backupId);
        if (res == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private Map<String, String> parseQueryParams(HttpExchange exchange) {
        Map<String, String> params = new LinkedHashMap<>();
        String query = exchange.getRequestURI().getRawQuery();
        if (query == null || query.isEmpty()) {
            return params;
        }
        for (String part : query.split("&")) {
            int eq = part.indexOf('=');
            if (eq < 0) {
                params.put(URLDecoder.decode(part, StandardCharsets.UTF_8), "");
            } else {
                String key = URLDecoder.decode(part.substring(0, eq), StandardCharsets.UTF_8);
                String value = URLDecoder.decode(part.substring(eq + 1), StandardCharsets.UTF_8);
                params.put(key, value);
            }
        }
        return params;
    }

    private int parseIntParam(String value, int defaultValue, int min, int max) {
        if (value == null) {
            return defaultValue;
        }
        try {
            int parsed = Integer.parseInt(value);
            if (parsed < min || parsed > max) {
                throw new RuntimeException("Out of range");
            }
            return parsed;
        } catch (NumberFormatException e) {
            throw new RuntimeException("Invalid integer");
        }
    }

    private void handlePlayCampaignReplayEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            String kind = (String) req.get("kind");
            String text = (String) req.get("text");
            if (eventId == null || eventId.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (!"append".equals(kind)) {
                throw new RuntimeException("Invalid kind");
            }
            if (storage.playCampaignReplayEventExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            Map<String, Object> event = storage.insertPlayCampaignReplayEvent(campaignId, eventId, kind, text);
            if (event == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(event));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignReplayGet(HttpExchange exchange, String campaignId) throws IOException {
        handlePlayCampaignReplayRead(exchange, campaignId);
    }

    private void handlePlayCampaignReplayCheck(HttpExchange exchange, String campaignId) throws IOException {
        handlePlayCampaignReplayRead(exchange, campaignId);
    }

    private void handlePlayCampaignReplayRead(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> events = storage.listPlayCampaignReplayEvents(campaignId);
        StringBuilder storyBuilder = new StringBuilder();
        List<String> eventIds = new ArrayList<>();
        for (Map<String, Object> event : events) {
            eventIds.add((String) event.get("event_id"));
            storyBuilder.append((String) event.get("text"));
        }
        String story = storyBuilder.toString();
        String digest = String.join(",", eventIds) + "|" + story;
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("story", story);
        res.put("event_ids", eventIds);
        res.put("digest", digest);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignRngSeedPut(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!"dm".equals(user.role) || !user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String seed = (String) req.get("seed");
            if (seed == null || seed.isEmpty()) {
                throw new RuntimeException("Missing seed");
            }
            if (storage.getPlayCampaignRngSeed(campaignId) != null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            if (!storage.setPlayCampaignRngSeed(campaignId, seed)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("seed", seed);
            res.put("rolls", new ArrayList<Map<String, Object>>());
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRngRollPost(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        if (storage.getPlayCampaignRngSeed(campaignId) == null) {
            HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String rollId = (String) req.get("roll_id");
            Object sidesObj = req.get("sides");
            if (rollId == null || rollId.isEmpty() || sidesObj == null) {
                throw new RuntimeException("Missing fields");
            }
            int sides = JsonUtils.toInt(sidesObj);
            if (sides < 2 || sides > 100) {
                throw new RuntimeException("Invalid sides");
            }
            Map<String, Object> roll = storage.insertPlayCampaignRngRoll(campaignId, rollId, sides);
            if (roll == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(roll));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignRngLedgerGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        String seed = storage.getPlayCampaignRngSeed(campaignId);
        if (seed == null) {
            seed = "";
        }
        List<Map<String, Object>> rolls = storage.listPlayCampaignRngRolls(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("seed", seed);
        res.put("rolls", rolls);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignModerationReportCreate(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String reportId = (String) req.get("report_id");
            String targetId = (String) req.get("target_id");
            String reason = (String) req.get("reason");
            if (reportId == null || reportId.isEmpty() || targetId == null || targetId.isEmpty() || reason == null || reason.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.playCampaignModerationReportExists(campaignId, reportId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MODERATION_REPORT_EXISTS);
                return;
            }
            Map<String, Object> report = storage.insertPlayCampaignModerationReport(campaignId, reportId, targetId, reason, user.username);
            if (report == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MODERATION_REPORT_EXISTS);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(report));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignModerationReportList(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> reports = storage.listPlayCampaignModerationReports(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("reports", reports);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignModerationReportResolve(HttpExchange exchange, String campaignId, String reportId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> report = storage.getPlayCampaignModerationReport(campaignId, reportId);
        if (report == null) {
            notFound(exchange);
            return;
        }
        if (!"open".equals(report.get("status"))) {
            HttpSupport.sendResponse(exchange, 409, ERROR_MODERATION_REPORT_ALREADY_RESOLVED);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String action = (String) req.get("action");
            String note = (String) req.get("note");
            if ((action == null || (!"allow".equals(action) && !"remove".equals(action))) || note == null || note.isEmpty()) {
                throw new RuntimeException("Invalid fields");
            }
            if (!storage.resolvePlayCampaignModerationReport(campaignId, reportId, action, note, user.username)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_MODERATION_REPORT_ALREADY_RESOLVED);
                return;
            }
            Map<String, Object> updated = storage.getPlayCampaignModerationReport(campaignId, reportId);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(updated));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private List<String> parseTagList(Object tagsObj, boolean requireNonEmpty) {
        if (tagsObj == null) throw new RuntimeException("Missing tags");
        if (!(tagsObj instanceof List)) throw new RuntimeException("Invalid tags");
        List<?> tagsRaw = (List<?>) tagsObj;
        if (requireNonEmpty && tagsRaw.isEmpty()) throw new RuntimeException("Empty tags");
        List<String> tags = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object o : tagsRaw) {
            if (!(o instanceof String)) throw new RuntimeException("Non-string tag");
            String tag = (String) o;
            if (tag.trim().isEmpty()) throw new RuntimeException("Empty tag");
            if (!seen.add(tag)) throw new RuntimeException("Duplicate tag");
            tags.add(tag);
        }
        return tags;
    }

    private void handlePlayCampaignSafetyBoundariesPut(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            Object tagsObj = req.get("blocked_tags");
            List<String> tags = parseTagList(tagsObj, true);
            Collections.sort(tags);
            storage.replacePlayCampaignSafetyBoundaries(campaignId, tags);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("blocked_tags", tags);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSafetyBoundariesGet(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<String> tags = storage.getPlayCampaignSafetyBoundaries(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("blocked_tags", tags);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignSafetyCheckCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            String kind = (String) req.get("kind");
            String text = (String) req.get("text");
            Object tagsObj = req.get("tags");
            if (eventId == null || eventId.isEmpty() || kind == null || text == null || text.isEmpty() || tagsObj == null) {
                throw new RuntimeException("Missing fields");
            }
            if (!"narration".equals(kind) && !"chat".equals(kind)) {
                throw new RuntimeException("Invalid kind");
            }
            List<String> tags = parseTagList(tagsObj, true);
            if (storage.playCampaignSafetyEventExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            List<String> blockedTags = storage.getPlayCampaignSafetyBoundaries(campaignId);
            for (String tag : tags) {
                if (blockedTags.contains(tag)) {
                    HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                    return;
                }
            }
            Map<String, Object> event = storage.insertPlayCampaignSafetyEvent(campaignId, eventId, kind, text, tags);
            if (event == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(event));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSafetyEventList(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        List<Map<String, Object>> events = storage.listPlayCampaignSafetyEvents(campaignId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("events", events);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
    }

    private void handlePlayCampaignFixtureSeed(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String fixtureId = (String) req.get("fixture_id");
            if (!"canonical-v1".equals(fixtureId)) {
                throw new RuntimeException("Invalid fixture_id");
            }
            boolean created = storage.seedPlayCampaignFixture(campaignId);
            Map<String, Object> res = storage.getPlayCampaignFixture(campaignId);
            HttpSupport.sendResponse(exchange, created ? 201 : 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignFixtureStateGet(HttpExchange exchange, String campaignId) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> fixture = storage.getPlayCampaignFixture(campaignId);
        if (fixture == null) {
            notFound(exchange);
            return;
        }
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(fixture));
    }

    private void handlePlayCampaignSpectatorsCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        if (!"dm".equals(user.role)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        if (!user.username.equals(campaign.get("owner"))) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String spectatorId = (String) req.get("spectator_id");
            if (spectatorId == null || spectatorId.isEmpty()) throw new RuntimeException("Missing spectator_id");
            if (!storage.insertPlayCampaignSpectator(spectatorId, campaignId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_CONFLICT);
                return;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("spectator_id", spectatorId);
            res.put("token", "spectator-" + spectatorId);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignSpectatorView(HttpExchange exchange, String campaignId) throws IOException {
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        if (auth == null) {
            unauthorized(exchange);
            return;
        }
        if (auth.startsWith("Bearer session-")) {
            forbidden(exchange);
            return;
        }
        String spectatorId = authenticateSpectator(exchange);
        if (spectatorId == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        String tokenCampaignId = storage.getPlayCampaignSpectatorCampaignId(spectatorId);
        if (tokenCampaignId == null) {
            unauthorized(exchange);
            return;
        }
        if (!tokenCampaignId.equals(campaignId)) {
            forbidden(exchange);
            return;
        }
        Map<String, Object> view = storage.getPlayCampaignSpectatorView(campaignId);
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(view));
    }

    private void handlePlayCampaignFeedEventCreate(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String eventId = (String) req.get("event_id");
            String text = (String) req.get("text");
            if (eventId == null || eventId.isEmpty() || text == null || text.isEmpty()) {
                throw new RuntimeException("Missing fields");
            }
            if (storage.playCampaignFeedEventExists(campaignId, eventId)) {
                HttpSupport.sendResponse(exchange, 409, ERROR_FEED_EVENT_EXISTS);
                return;
            }
            Map<String, Object> res = storage.insertPlayCampaignFeedEvent(campaignId, eventId, text);
            if (res == null) {
                HttpSupport.sendResponse(exchange, 409, ERROR_FEED_EVENT_EXISTS);
                return;
            }
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private void handlePlayCampaignEventFeedRead(HttpExchange exchange, String campaignId) throws IOException {
        User user = authenticate(exchange);
        if (user == null) {
            unauthorized(exchange);
            return;
        }
        Map<String, Object> campaign = storage.getPlayCampaign(campaignId);
        if (campaign == null) {
            HttpSupport.sendResponse(exchange, 404, ERROR_CAMPAIGN_NOT_FOUND);
            return;
        }
        boolean isOwner = user.username.equals(campaign.get("owner"));
        boolean isMember = storage.isPlayCampaignMember(campaignId, user.username);
        if (!isOwner && !isMember) {
            forbidden(exchange);
            return;
        }
        try {
            String query = exchange.getRequestURI().getQuery();
            int cursor = 0;
            int limit = 2;
            if (query != null && !query.isEmpty()) {
                for (String part : query.split("&")) {
                    int eq = part.indexOf('=');
                    if (eq < 0) continue;
                    String key = URLDecoder.decode(part.substring(0, eq), StandardCharsets.UTF_8);
                    String value = URLDecoder.decode(part.substring(eq + 1), StandardCharsets.UTF_8);
                    if ("cursor".equals(key)) {
                        cursor = Integer.parseInt(value);
                    } else if ("limit".equals(key)) {
                        limit = Integer.parseInt(value);
                    }
                }
            }
            if (cursor < 0 || limit < 1 || limit > 3) {
                throw new RuntimeException("Invalid pagination");
            }
            Map<String, Object> res = storage.listPlayCampaignFeedEvents(campaignId, cursor, limit);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }
}
