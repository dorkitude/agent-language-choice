<?php

declare(strict_types=1);

namespace App\Routing;

use App\Http\Controllers;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

/**
 * Build the Symfony RouteCollection for the DM tools API.
 *
 * Route names are stable identifiers used for debugging; they do not affect
 * the public URL contract.
 */
final class Router
{
    public static function build(Controllers $controllers): RouteCollection
    {
        $routes = new RouteCollection();

        $routes->add('health', new Route('/health', ['_controller' => [$controllers, 'health']], [], [], '', [], ['GET']));
        $routes->add('storage_status', new Route('/v1/storage/status', ['_controller' => [$controllers, 'storageStatus']], [], [], '', [], ['GET']));
        $routes->add('storage_reset', new Route('/v1/storage/reset', ['_controller' => [$controllers, 'storageReset']], [], [], '', [], ['POST']));
        $routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => [$controllers, 'diceStats']], [], [], '', [], ['POST']));
        $routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => [$controllers, 'abilityCheck']], [], [], '', [], ['POST']));
        $routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => [$controllers, 'adjustedXp']], [], [], '', [], ['POST']));
        $routes->add('initiative', new Route('/v1/initiative/order', ['_controller' => [$controllers, 'initiativeOrder']], [], [], '', [], ['POST']));
        $routes->add('ability_modifier', new Route('/v1/characters/ability-modifier', ['_controller' => [$controllers, 'abilityModifier']], [], [], '', [], ['POST']));
        $routes->add('proficiency', new Route('/v1/characters/proficiency', ['_controller' => [$controllers, 'proficiencyBonus']], [], [], '', [], ['POST']));
        $routes->add('derived_stats', new Route('/v1/characters/derived-stats', ['_controller' => [$controllers, 'derivedStats']], [], [], '', [], ['POST']));
        $routes->add('create_combat_session', new Route('/v1/combat/sessions', ['_controller' => [$controllers, 'createCombatSession']], [], [], '', [], ['POST']));
        $routes->add('add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_controller' => [$controllers, 'addCondition']], [], [], '', [], ['POST']));
        $routes->add('advance_turn', new Route('/v1/combat/sessions/{id}/advance', ['_controller' => [$controllers, 'advanceTurn']], [], [], '', [], ['POST']));
        $routes->add('auth_register', new Route('/v1/auth/register', ['_controller' => [$controllers, 'authRegister']], [], [], '', [], ['POST']));
        $routes->add('auth_login', new Route('/v1/auth/login', ['_controller' => [$controllers, 'authLogin']], [], [], '', [], ['POST']));
        $routes->add('compendium_monsters_create', new Route('/v1/compendium/monsters', ['_controller' => [$controllers, 'createMonster']], [], [], '', [], ['POST']));
        $routes->add('compendium_monsters_read', new Route('/v1/compendium/monsters/{slug}', ['_controller' => [$controllers, 'readMonster']], [], [], '', [], ['GET']));
        $routes->add('compendium_items_create', new Route('/v1/compendium/items', ['_controller' => [$controllers, 'createItem']], [], [], '', [], ['POST']));
        $routes->add('compendium_items_read', new Route('/v1/compendium/items/{slug}', ['_controller' => [$controllers, 'readItem']], [], [], '', [], ['GET']));
        $routes->add('campaigns_create', new Route('/v1/campaigns', ['_controller' => [$controllers, 'createCampaign']], [], [], '', [], ['POST']));
        $routes->add('campaigns_characters_add', new Route('/v1/campaigns/{id}/characters', ['_controller' => [$controllers, 'addCampaignCharacter']], [], [], '', [], ['POST']));
        $routes->add('campaigns_events_add', new Route('/v1/campaigns/{id}/events', ['_controller' => [$controllers, 'addCampaignEvent']], [], [], '', [], ['POST']));
        $routes->add('campaigns_state_read', new Route('/v1/campaigns/{id}/state', ['_controller' => [$controllers, 'readCampaignState']], [], [], '', [], ['GET']));
        $routes->add('quests_summary', new Route('/v1/campaigns/{id}/quests/summary', ['_controller' => [$controllers, 'getQuestSummary']], [], [], '', [], ['GET']));
        $routes->add('quests_progress', new Route('/v1/campaigns/{id}/quests/{quest_id}/progress', ['_controller' => [$controllers, 'updateQuestProgress']], [], [], '', [], ['POST']));
        $routes->add('quests_create', new Route('/v1/campaigns/{id}/quests', ['_controller' => [$controllers, 'createQuest']], [], [], '', [], ['POST']));
        $routes->add('campaigns_factions_create', new Route('/v1/campaigns/{id}/factions', ['_controller' => [$controllers, 'createFaction']], [], [], '', [], ['POST']));
        $routes->add('campaigns_npcs_create', new Route('/v1/campaigns/{id}/npcs', ['_controller' => [$controllers, 'createNpc']], [], [], '', [], ['POST']));
        $routes->add('campaigns_relationships', new Route('/v1/campaigns/{id}/relationships', ['_controller' => [$controllers, 'readRelationships']], [], [], '', [], ['GET']));
        $routes->add('campaigns_inventory_summary', new Route('/v1/campaigns/{id}/inventory/summary', ['_controller' => [$controllers, 'getInventorySummary']], [], [], '', [], ['GET']));
        $routes->add('campaigns_inventory_add', new Route('/v1/campaigns/{id}/inventory', ['_controller' => [$controllers, 'addInventoryItem']], [], [], '', [], ['POST']));
        $routes->add('campaigns_equipment_assign', new Route('/v1/campaigns/{id}/characters/{character_id}/equipment', ['_controller' => [$controllers, 'assignEquipment']], [], [], '', [], ['POST']));
        $routes->add('downtime_crafting_create', new Route('/v1/campaigns/{id}/downtime/crafting', ['_controller' => [$controllers, 'createCraftingProject']], [], [], '', [], ['POST']));
        $routes->add('downtime_crafting_advance', new Route('/v1/campaigns/{id}/downtime/crafting/{project_id}/advance', ['_controller' => [$controllers, 'advanceCraftingProject']], [], [], '', [], ['POST']));
        $routes->add('campaigns_sessions_schedule', new Route('/v1/campaigns/{id}/sessions', ['_controller' => [$controllers, 'scheduleSession']], [], [], '', [], ['POST']));
        $routes->add('campaigns_sessions_attendance', new Route('/v1/campaigns/{id}/sessions/{session_id}/attendance', ['_controller' => [$controllers, 'recordAttendance']], [], [], '', [], ['POST']));
        $routes->add('campaigns_sessions_next', new Route('/v1/campaigns/{id}/sessions/next', ['_controller' => [$controllers, 'getNextSession']], [], [], '', [], ['GET']));
        $routes->add('campaigns_audit', new Route('/v1/campaigns/{id}/audit', ['_controller' => [$controllers, 'auditCampaign']], [], [], '', [], ['GET']));
        $routes->add('campaigns_export', new Route('/v1/campaigns/{id}/export', ['_controller' => [$controllers, 'exportCampaign']], [], [], '', [], ['GET']));
        $routes->add('phb_spell_slots', new Route('/v1/phb/spell-slots', ['_controller' => [$controllers, 'phbSpellSlots']], [], [], '', [], ['POST']));
        $routes->add('phb_long_rest', new Route('/v1/phb/rests/long', ['_controller' => [$controllers, 'phbLongRest']], [], [], '', [], ['POST']));
        $routes->add('phb_equipment_load', new Route('/v1/phb/equipment-load', ['_controller' => [$controllers, 'phbEquipmentLoad']], [], [], '', [], ['POST']));
        $routes->add('dm_encounter_builder', new Route('/v1/dm/encounter-builder', ['_controller' => [$controllers, 'dmEncounterBuilder']], [], [], '', [], ['POST']));
        $routes->add('dm_loot_parcel', new Route('/v1/dm/loot-parcel', ['_controller' => [$controllers, 'dmLootParcel']], [], [], '', [], ['POST']));
        $routes->add('dm_session_recap', new Route('/v1/dm/session-recap', ['_controller' => [$controllers, 'dmSessionRecap']], [], [], '', [], ['POST']));

        return $routes;
    }
}
