<?php

namespace App\Http;

use App\Analytics\AnalyticsController;
use App\Audit\AuditController;
use App\Auth\AuthController;
use App\Campaign\CampaignController;
use App\Characters\CharacterController;
use App\Combat\CombatController;
use App\Compendium\CompendiumController;
use App\Dice\DiceController;
use App\DmTools\DmToolsController;
use App\Downtime\DowntimeController;
use App\Health\HealthController;
use App\Inventory\InventoryController;
use App\PhbRules\PhbRulesController;
use App\Play\PlayController;
use App\Session\SessionController;
use App\Storage\StorageController;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

/**
 * Builds the application's Symfony RouteCollection: every HTTP route the
 * server exposes, mapped to a [controller instance, method] callable.
 *
 * Each route carries two custom defaults consumed by Kernel:
 *   - _controller: the callable to invoke
 *   - _needsBody:  whether Kernel should parse and pass the JSON request
 *                   body as the callable's first argument
 *
 * Any path parameters (e.g. {id}, {slug}, {campaignId}) are passed through
 * as additional positional arguments, after the body when present.
 */
final class RouteFactory
{
    private function __construct()
    {
    }

    public static function build(): RouteCollection
    {
        $health = new HealthController();
        $storage = new StorageController();
        $combat = new CombatController();
        $auth = new AuthController();
        $compendium = new CompendiumController();
        $campaign = new CampaignController();
        $dmTools = new DmToolsController();
        $dice = new DiceController();
        $characters = new CharacterController();
        $phbRules = new PhbRulesController();
        $inventory = new InventoryController();
        $downtime = new DowntimeController();
        $session = new SessionController();
        $audit = new AuditController();
        $analytics = new AnalyticsController();
        $play = new PlayController();

        $routes = new RouteCollection();

        $add = static function (
            RouteCollection $routes,
            string $name,
            string $method,
            string $path,
            callable $controller,
            bool $needsBody,
            bool $needsAuth = false,
        ): void {
            $routes->add($name, new Route($path, [
                '_controller' => $controller,
                '_needsBody' => $needsBody,
                '_needsAuth' => $needsAuth,
            ], [], [], null, [], [$method]));
        };

        $add($routes, 'health', 'GET', '/health', [$health, 'check'], false);

        $add($routes, 'storage_status', 'GET', '/v1/storage/status', [$storage, 'status'], false);
        $add($routes, 'storage_reset', 'POST', '/v1/storage/reset', [$storage, 'reset'], false);

        $add($routes, 'combat_create_session', 'POST', '/v1/combat/sessions', [$combat, 'createSession'], true);
        $add($routes, 'combat_add_condition', 'POST', '/v1/combat/sessions/{id}/conditions', [$combat, 'addCondition'], true);
        $add($routes, 'combat_advance_turn', 'POST', '/v1/combat/sessions/{id}/advance', [$combat, 'advanceTurn'], false);

        $add($routes, 'auth_register', 'POST', '/v1/auth/register', [$auth, 'register'], true);
        $add($routes, 'auth_login', 'POST', '/v1/auth/login', [$auth, 'login'], true);

        $add($routes, 'compendium_create_monster', 'POST', '/v1/compendium/monsters', [$compendium, 'createMonster'], true);
        $add($routes, 'compendium_get_monster', 'GET', '/v1/compendium/monsters/{slug}', [$compendium, 'getMonster'], false);
        $add($routes, 'compendium_create_item', 'POST', '/v1/compendium/items', [$compendium, 'createItem'], true);
        $add($routes, 'compendium_get_item', 'GET', '/v1/compendium/items/{slug}', [$compendium, 'getItem'], false);

        $add($routes, 'campaign_create', 'POST', '/v1/campaigns', [$campaign, 'create'], true);
        $add($routes, 'campaign_add_character', 'POST', '/v1/campaigns/{campaignId}/characters', [$campaign, 'addCharacter'], true);
        $add($routes, 'campaign_add_event', 'POST', '/v1/campaigns/{campaignId}/events', [$campaign, 'addEvent'], true);
        $add($routes, 'campaign_get_state', 'GET', '/v1/campaigns/{campaignId}/state', [$campaign, 'getState'], false);
        $add($routes, 'campaign_create_quest', 'POST', '/v1/campaigns/{campaignId}/quests', [$campaign, 'createQuest'], true);
        $add($routes, 'campaign_quest_summary', 'GET', '/v1/campaigns/{campaignId}/quests/summary', [$campaign, 'questSummary'], false);
        $add($routes, 'campaign_quest_progress', 'POST', '/v1/campaigns/{campaignId}/quests/{questId}/progress', [$campaign, 'updateQuestProgress'], true);
        $add($routes, 'campaign_create_faction', 'POST', '/v1/campaigns/{campaignId}/factions', [$campaign, 'createFaction'], true);
        $add($routes, 'campaign_create_npc', 'POST', '/v1/campaigns/{campaignId}/npcs', [$campaign, 'createNpc'], true);
        $add($routes, 'campaign_relationships', 'GET', '/v1/campaigns/{campaignId}/relationships', [$campaign, 'relationshipSummary'], false);

        $add($routes, 'dm_encounter_builder', 'POST', '/v1/dm/encounter-builder', [$dmTools, 'encounterBuilder'], true);
        $add($routes, 'dm_loot_parcel', 'POST', '/v1/dm/loot-parcel', [$dmTools, 'lootParcel'], true);
        $add($routes, 'dm_session_recap', 'POST', '/v1/dm/session-recap', [$dmTools, 'sessionRecap'], true);

        $add($routes, 'dice_stats', 'POST', '/v1/dice/stats', [$dice, 'stats'], true);
        $add($routes, 'checks_ability', 'POST', '/v1/checks/ability', [$dice, 'abilityCheck'], true);
        $add($routes, 'encounters_adjusted_xp', 'POST', '/v1/encounters/adjusted-xp', [$dice, 'adjustedXp'], true);
        $add($routes, 'initiative_order', 'POST', '/v1/initiative/order', [$dice, 'initiativeOrder'], true);

        $add($routes, 'characters_ability_modifier', 'POST', '/v1/characters/ability-modifier', [$characters, 'abilityModifier'], true);
        $add($routes, 'characters_proficiency', 'POST', '/v1/characters/proficiency', [$characters, 'proficiency'], true);
        $add($routes, 'characters_derived_stats', 'POST', '/v1/characters/derived-stats', [$characters, 'derivedStats'], true);

        $add($routes, 'phb_spell_slots', 'POST', '/v1/phb/spell-slots', [$phbRules, 'spellSlots'], true);
        $add($routes, 'phb_rests_long', 'POST', '/v1/phb/rests/long', [$phbRules, 'longRest'], true);
        $add($routes, 'phb_equipment_load', 'POST', '/v1/phb/equipment-load', [$phbRules, 'equipmentLoad'], true);

        $add($routes, 'campaign_add_inventory_item', 'POST', '/v1/campaigns/{campaignId}/inventory', [$inventory, 'addItem'], true);
        $add($routes, 'campaign_inventory_summary', 'GET', '/v1/campaigns/{campaignId}/inventory/summary', [$inventory, 'summary'], false);
        $add($routes, 'campaign_assign_equipment', 'POST', '/v1/campaigns/{campaignId}/characters/{characterId}/equipment', [$inventory, 'assignEquipment'], true);

        $add($routes, 'downtime_create_crafting', 'POST', '/v1/campaigns/{campaignId}/downtime/crafting', [$downtime, 'createProject'], true);
        $add($routes, 'downtime_advance_crafting', 'POST', '/v1/campaigns/{campaignId}/downtime/crafting/{projectId}/advance', [$downtime, 'advance'], true);

        $add($routes, 'campaign_create_session', 'POST', '/v1/campaigns/{campaignId}/sessions', [$session, 'create'], true);
        $add($routes, 'campaign_session_attendance', 'POST', '/v1/campaigns/{campaignId}/sessions/{sessionId}/attendance', [$session, 'recordAttendance'], true);
        $add($routes, 'campaign_next_session', 'GET', '/v1/campaigns/{campaignId}/sessions/next', [$session, 'next'], false);

        $add($routes, 'campaign_audit', 'GET', '/v1/campaigns/{campaignId}/audit', [$audit, 'audit'], false);
        $add($routes, 'campaign_export', 'GET', '/v1/campaigns/{campaignId}/export', [$audit, 'export'], false);

        $add($routes, 'campaign_analytics_summary', 'GET', '/v1/campaigns/{campaignId}/analytics/summary', [$analytics, 'summary'], false);
        $add($routes, 'campaign_analytics_risk_report', 'POST', '/v1/campaigns/{campaignId}/analytics/risk-report', [$analytics, 'riskReport'], true);

        $add($routes, 'play_create_campaign', 'POST', '/v1/play/campaigns', [$play, 'createCampaign'], true, true);
        $add($routes, 'play_join_campaign', 'POST', '/v1/play/campaigns/{campaignId}/members', [$play, 'joinCampaign'], true, true);
        $add($routes, 'play_start_campaign', 'POST', '/v1/play/campaigns/{campaignId}/start', [$play, 'startCampaign'], false, true);
        $add($routes, 'play_add_narration', 'POST', '/v1/play/campaigns/{campaignId}/narrations', [$play, 'addNarration'], true, true);
        $add($routes, 'play_submit_action', 'POST', '/v1/play/campaigns/{campaignId}/actions', [$play, 'submitAction'], true, true);
        $add($routes, 'play_get_turn', 'GET', '/v1/play/campaigns/{campaignId}/turn', [$play, 'getTurn'], false, true);
        $add($routes, 'play_nudge_turn', 'POST', '/v1/play/campaigns/{campaignId}/turn/nudge', [$play, 'nudgeTurn'], true, true);
        $add($routes, 'play_my_turn', 'GET', '/v1/play/campaigns/{campaignId}/my-turn', [$play, 'myTurn'], false, true);
        $add($routes, 'play_gm_status', 'GET', '/v1/play/campaigns/{campaignId}/gm/status', [$play, 'gmStatus'], false, true);
        $add($routes, 'play_add_resolution', 'POST', '/v1/play/campaigns/{campaignId}/resolutions', [$play, 'addResolution'], true, true);
        $add($routes, 'play_update_document', 'PUT', '/v1/play/campaigns/{campaignId}/document', [$play, 'updateDocument'], true, true);
        $add($routes, 'play_get_document', 'GET', '/v1/play/campaigns/{campaignId}/document', [$play, 'getDocument'], false, true);

        $add($routes, 'play_create_scene', 'POST', '/v1/play/campaigns/{campaignId}/scenes', [$play, 'createScene'], true, true);
        $add($routes, 'play_get_current_scene', 'GET', '/v1/play/campaigns/{campaignId}/scenes/current', [$play, 'getCurrentScene'], false, true);
        $add($routes, 'play_enter_scene', 'POST', '/v1/play/campaigns/{campaignId}/scenes/{sceneId}/enter', [$play, 'enterScene'], false, true);
        $add($routes, 'play_close_scene', 'POST', '/v1/play/campaigns/{campaignId}/scenes/{sceneId}/close', [$play, 'closeScene'], false, true);

        $add($routes, 'play_create_location', 'POST', '/v1/play/campaigns/{campaignId}/locations', [$play, 'createLocation'], true, true);
        $add($routes, 'play_create_connection', 'POST', '/v1/play/campaigns/{campaignId}/locations/{fromId}/connections', [$play, 'createConnection'], true, true);
        $add($routes, 'play_get_travel', 'GET', '/v1/play/campaigns/{campaignId}/locations/{locId}/travel', [$play, 'getTravel'], false, true);
        $add($routes, 'play_travel_turn', 'POST', '/v1/play/campaigns/{campaignId}/turn/travel', [$play, 'travelTurn'], true, true);
        $add($routes, 'play_rest_turn', 'POST', '/v1/play/campaigns/{campaignId}/turn/rest', [$play, 'restTurn'], true, true);

        $add($routes, 'play_create_encounter', 'POST', '/v1/play/campaigns/{campaignId}/encounters', [$play, 'createEncounter'], true, true);
        $add($routes, 'play_add_monster', 'POST', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/monsters', [$play, 'addMonster'], true, true);
        $add($routes, 'play_remove_monster', 'DELETE', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/monsters/{monsterId}', [$play, 'removeMonster'], false, true);
        $add($routes, 'play_bind_combatant', 'POST', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/combatants', [$play, 'bindCombatant'], true, true);
        $add($routes, 'play_unbind_combatant', 'DELETE', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/combatants/{member}', [$play, 'unbindCombatant'], false, true);
        $add($routes, 'play_get_encounter_turn', 'GET', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/turn', [$play, 'getEncounterTurn'], false, true);
        $add($routes, 'play_advance_encounter_turn', 'POST', '/v1/play/campaigns/{campaignId}/encounters/{encounterId}/turn/advance', [$play, 'advanceEncounterTurn'], false, true);

        return $routes;
    }
}
