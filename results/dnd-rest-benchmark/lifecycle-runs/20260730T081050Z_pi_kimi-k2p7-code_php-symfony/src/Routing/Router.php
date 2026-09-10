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
        $c = static fn (string $method): callable => [$controllers, $method];

        $routes->add('health', self::get('/health', $c('health')));
        $routes->add('healthz', self::get('/healthz', $c('healthz')));
        $routes->add('readyz', self::get('/readyz', $c('readyz')));
        $routes->add('schema', self::get('/v1/schema', $c('schema')));
        $routes->add('storage_status', self::get('/v1/storage/status', $c('storageStatus')));
        $routes->add('storage_reset', self::post('/v1/storage/reset', $c('storageReset')));
        $routes->add('dice_stats', self::post('/v1/dice/stats', $c('diceStats')));
        $routes->add('ability_check', self::post('/v1/checks/ability', $c('abilityCheck')));
        $routes->add('adjusted_xp', self::post('/v1/encounters/adjusted-xp', $c('adjustedXp')));
        $routes->add('initiative', self::post('/v1/initiative/order', $c('initiativeOrder')));
        $routes->add('ability_modifier', self::post('/v1/characters/ability-modifier', $c('abilityModifier')));
        $routes->add('proficiency', self::post('/v1/characters/proficiency', $c('proficiencyBonus')));
        $routes->add('derived_stats', self::post('/v1/characters/derived-stats', $c('derivedStats')));
        $routes->add('create_combat_session', self::post('/v1/combat/sessions', $c('createCombatSession')));
        $routes->add('add_condition', self::post('/v1/combat/sessions/{id}/conditions', $c('addCondition')));
        $routes->add('advance_turn', self::post('/v1/combat/sessions/{id}/advance', $c('advanceTurn')));
        $routes->add('auth_register', self::post('/v1/auth/register', $c('authRegister')));
        $routes->add('auth_login', self::post('/v1/auth/login', $c('authLogin')));
        $routes->add('compendium_monsters_create', self::post('/v1/compendium/monsters', $c('createMonster')));
        $routes->add('compendium_monsters_read', self::get('/v1/compendium/monsters/{slug}', $c('readMonster')));
        $routes->add('compendium_items_create', self::post('/v1/compendium/items', $c('createItem')));
        $routes->add('compendium_items_read', self::get('/v1/compendium/items/{slug}', $c('readItem')));
        $routes->add('campaigns_create', self::post('/v1/campaigns', $c('createCampaign')));
        $routes->add('campaigns_characters_add', self::post('/v1/campaigns/{id}/characters', $c('addCampaignCharacter')));
        $routes->add('campaigns_events_add', self::post('/v1/campaigns/{id}/events', $c('addCampaignEvent')));
        $routes->add('campaigns_state_read', self::get('/v1/campaigns/{id}/state', $c('readCampaignState')));
        $routes->add('quests_summary', self::get('/v1/campaigns/{id}/quests/summary', $c('getQuestSummary')));
        $routes->add('quests_progress', self::post('/v1/campaigns/{id}/quests/{quest_id}/progress', $c('updateQuestProgress')));
        $routes->add('quests_create', self::post('/v1/campaigns/{id}/quests', $c('createQuest')));
        $routes->add('campaigns_factions_create', self::post('/v1/campaigns/{id}/factions', $c('createFaction')));
        $routes->add('campaigns_npcs_create', self::post('/v1/campaigns/{id}/npcs', $c('createNpc')));
        $routes->add('campaigns_relationships', self::get('/v1/campaigns/{id}/relationships', $c('readRelationships')));
        $routes->add('campaigns_inventory_summary', self::get('/v1/campaigns/{id}/inventory/summary', $c('getInventorySummary')));
        $routes->add('campaigns_inventory_add', self::post('/v1/campaigns/{id}/inventory', $c('addInventoryItem')));
        $routes->add('campaigns_equipment_assign', self::post('/v1/campaigns/{id}/characters/{character_id}/equipment', $c('assignEquipment')));
        $routes->add('downtime_crafting_create', self::post('/v1/campaigns/{id}/downtime/crafting', $c('createCraftingProject')));
        $routes->add('downtime_crafting_advance', self::post('/v1/campaigns/{id}/downtime/crafting/{project_id}/advance', $c('advanceCraftingProject')));
        $routes->add('campaigns_sessions_schedule', self::post('/v1/campaigns/{id}/sessions', $c('scheduleSession')));
        $routes->add('campaigns_sessions_attendance', self::post('/v1/campaigns/{id}/sessions/{session_id}/attendance', $c('recordAttendance')));
        $routes->add('campaigns_sessions_next', self::get('/v1/campaigns/{id}/sessions/next', $c('getNextSession')));
        $routes->add('campaigns_audit', self::get('/v1/campaigns/{id}/audit', $c('auditCampaign')));
        $routes->add('campaigns_export', self::get('/v1/campaigns/{id}/export', $c('exportCampaign')));
        $routes->add('campaigns_analytics_summary', self::get('/v1/campaigns/{id}/analytics/summary', $c('campaignAnalyticsSummary')));
        $routes->add('campaigns_analytics_risk_report', self::post('/v1/campaigns/{id}/analytics/risk-report', $c('campaignRiskReport')));
        $routes->add('phb_spell_slots', self::post('/v1/phb/spell-slots', $c('phbSpellSlots')));
        $routes->add('phb_long_rest', self::post('/v1/phb/rests/long', $c('phbLongRest')));
        $routes->add('phb_equipment_load', self::post('/v1/phb/equipment-load', $c('phbEquipmentLoad')));
        $routes->add('dm_encounter_builder', self::post('/v1/dm/encounter-builder', $c('dmEncounterBuilder')));
        $routes->add('dm_loot_parcel', self::post('/v1/dm/loot-parcel', $c('dmLootParcel')));
        $routes->add('dm_session_recap', self::post('/v1/dm/session-recap', $c('dmSessionRecap')));
        $routes->add('play_campaigns_create', self::post('/v1/play/campaigns', $c('createPlayCampaign')));
        $routes->add('play_campaigns_join', self::post('/v1/play/campaigns/{id}/members', $c('joinPlayCampaign')));
        $routes->add('play_campaigns_invitations_create', self::post('/v1/play/campaigns/{id}/invitations', $c('createPlayCampaignInvitation'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_invitations_accept', self::post('/v1/play/campaigns/{id}/invitations/{invitation_id}/accept', $c('acceptPlayCampaignInvitation'), ['id' => '[^/]+', 'invitation_id' => '[^/]+']));
        $routes->add('play_campaigns_invitations_list', self::get('/v1/play/campaigns/{id}/invitations', $c('listPlayCampaignInvitations'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_delegations_audit', self::get('/v1/play/campaigns/{id}/delegations/audit', $c('auditPlayCampaignDelegation'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_delegations_create', self::post('/v1/play/campaigns/{id}/delegations', $c('grantPlayCampaignDelegation'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_delegations_revoke', self::delete('/v1/play/campaigns/{id}/delegations/{username}', $c('revokePlayCampaignDelegation'), ['id' => '[^/]+', 'username' => '[^/]+']));
        $routes->add('play_campaigns_audit_events_create', self::post('/v1/play/campaigns/{id}/audit-events', $c('createPlayCampaignAuditEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_audit_events_read', self::get('/v1/play/campaigns/{id}/audit-events', $c('getPlayCampaignAuditEvents'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_projection_events_create', self::post('/v1/play/campaigns/{id}/projection-events', $c('createPlayCampaignProjectionEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_projection_rebuild', self::get('/v1/play/campaigns/{id}/projection/rebuild', $c('rebuildPlayCampaignProjection'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_projection_read', self::get('/v1/play/campaigns/{id}/projection', $c('getPlayCampaignProjection'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_idempotent_events_create', self::post('/v1/play/campaigns/{id}/idempotent-events', $c('createPlayCampaignIdempotentEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_idempotent_events_read', self::get('/v1/play/campaigns/{id}/idempotent-events', $c('getPlayCampaignIdempotentEvents'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_safe_turns_create', self::post('/v1/play/campaigns/{id}/safe-turns', $c('submitPlayCampaignSafeTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_safe_turns_read', self::get('/v1/play/campaigns/{id}/safe-turns', $c('getPlayCampaignSafeTurns'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_session_zero_update', self::put('/v1/play/campaigns/{id}/session-zero', $c('setPlayCampaignSessionZero'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_session_zero_read', self::get('/v1/play/campaigns/{id}/session-zero', $c('getPlayCampaignSessionZero'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_start', self::post('/v1/play/campaigns/{id}/start', $c('startPlayCampaign')));
        $routes->add('play_campaigns_content_create', self::post('/v1/play/campaigns/{id}/content', $c('createPlayCampaignContent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_content_update_tags', self::put('/v1/play/campaigns/{id}/content/{content_id}/tags', $c('updatePlayCampaignContentTags'), ['id' => '[^/]+', 'content_id' => '[^/]+']));
        $routes->add('play_campaigns_onboarding', self::get('/v1/play/campaigns/{id}/onboarding', $c('readPlayCampaignOnboarding'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_content_list', self::get('/v1/play/campaigns/{id}/content', $c('getPlayCampaignContent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_narrate', self::post('/v1/play/campaigns/{id}/narrations', $c('addPlayCampaignNarration')));
        $routes->add('play_campaigns_turn_nudge', self::post('/v1/play/campaigns/{id}/turn/nudge', $c('nudgePlayCampaignTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_turn', self::get('/v1/play/campaigns/{id}/turn', $c('getPlayCampaignTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_my_turn', self::get('/v1/play/campaigns/{id}/my-turn', $c('getPlayCampaignMyTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_gm_status', self::get('/v1/play/campaigns/{id}/gm/status', $c('getPlayCampaignGmStatus'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_action', self::post('/v1/play/campaigns/{id}/actions', $c('submitPlayCampaignAction'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_resolution', self::post('/v1/play/campaigns/{id}/resolutions', $c('resolvePlayCampaignAction'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_document_get', self::get('/v1/play/campaigns/{id}/document', $c('getPlayCampaignDocument'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_document_update', self::put('/v1/play/campaigns/{id}/document', $c('updatePlayCampaignDocument'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_exports_create', self::post('/v1/play/campaigns/{id}/exports', $c('createPlayCampaignExport'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_exports_list', self::get('/v1/play/campaigns/{id}/exports', $c('listPlayCampaignExports'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_exports_read', self::get('/v1/play/campaigns/{id}/exports/{version}', $c('getPlayCampaignExport'), ['id' => '[^/]+', 'version' => '[^/]+']));
        $routes->add('play_campaigns_imports_create', self::post('/v1/play/campaigns/{id}/imports', $c('createPlayCampaignImport'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_imports_state', self::get('/v1/play/campaigns/{id}/import-state', $c('getPlayCampaignImportState'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_migrations_create', self::post('/v1/play/campaigns/{id}/migrations', $c('createPlayCampaignMigration'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_migrations_state', self::get('/v1/play/campaigns/{id}/migration-state', $c('getPlayCampaignMigrationState'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_search_records_create', self::post('/v1/play/campaigns/{id}/search-records', $c('createPlayCampaignSearchRecord'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_search_records_list', self::get('/v1/play/campaigns/{id}/search-records', $c('listPlayCampaignSearchRecords'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_rate_events_create', self::post('/v1/play/campaigns/{id}/rate-events', $c('createPlayCampaignRateEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_rate_events_list', self::get('/v1/play/campaigns/{id}/rate-events', $c('listPlayCampaignRateEvents'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_metrics', self::get('/v1/play/campaigns/{id}/metrics', $c('getPlayCampaignMetrics'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_backups_create', self::post('/v1/play/campaigns/{id}/backups', $c('createPlayCampaignBackup'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_backups_list', self::get('/v1/play/campaigns/{id}/backups', $c('listPlayCampaignBackups'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_backups_restore', self::post('/v1/play/campaigns/{id}/backups/{backup_id}/restore', $c('restorePlayCampaignBackup'), ['id' => '[^/]+', 'backup_id' => '[^/]+']));
        $routes->add('play_campaigns_replay_events_create', self::post('/v1/play/campaigns/{id}/replay-events', $c('appendPlayCampaignReplayEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_replay_read', self::get('/v1/play/campaigns/{id}/replay', $c('getPlayCampaignReplay'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_replay_check', self::get('/v1/play/campaigns/{id}/replay/check', $c('checkPlayCampaignReplay'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_rng_seed', self::put('/v1/play/campaigns/{id}/rng-seed', $c('setPlayCampaignRngSeed'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_rng_rolls', self::post('/v1/play/campaigns/{id}/rng-rolls', $c('appendPlayCampaignRngRoll'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_rng_ledger', self::get('/v1/play/campaigns/{id}/rng-ledger', $c('getPlayCampaignRngLedger'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_moderation_reports_create', self::post('/v1/play/campaigns/{id}/moderation/reports', $c('createPlayCampaignModerationReport'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_moderation_reports_read', self::get('/v1/play/campaigns/{id}/moderation/reports', $c('getPlayCampaignModerationReports'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_moderation_reports_resolve', self::put('/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', $c('resolvePlayCampaignModerationReport'), ['id' => '[^/]+', 'report_id' => '[^/]+']));
        $routes->add('play_campaigns_safety_boundaries_replace', self::put('/v1/play/campaigns/{id}/safety-boundaries', $c('replacePlayCampaignSafetyBoundaries'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_safety_boundaries_read', self::get('/v1/play/campaigns/{id}/safety-boundaries', $c('getPlayCampaignSafetyBoundaries'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_safety_checks_submit', self::post('/v1/play/campaigns/{id}/safety-checks', $c('submitPlayCampaignSafetyCheck'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_safety_events_read', self::get('/v1/play/campaigns/{id}/safety-events', $c('getPlayCampaignSafetyEvents'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_service_mode', self::post('/v1/play/campaigns/{id}/service-mode', $c('setPlayCampaignServiceMode'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_fixture_seeds_create', self::post('/v1/play/campaigns/{id}/fixture-seeds', $c('seedPlayCampaignFixture'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_fixture_state_read', self::get('/v1/play/campaigns/{id}/fixture-state', $c('getPlayCampaignFixtureState'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_spectators_create', self::post('/v1/play/campaigns/{id}/spectators', $c('createPlayCampaignSpectator'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_spectator_view', self::get('/v1/play/campaigns/{id}/spectator-view', $c('getPlayCampaignSpectatorView'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_feed_events_create', self::post('/v1/play/campaigns/{id}/feed-events', $c('createPlayCampaignFeedEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_event_feed_read', self::get('/v1/play/campaigns/{id}/event-feed', $c('getPlayCampaignEventFeed'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_scenes_create', self::post('/v1/play/campaigns/{id}/scenes', $c('createPlayCampaignScene'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_current_scene', self::get('/v1/play/campaigns/{id}/scenes/current', $c('getPlayCampaignCurrentScene'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_scene_enter', self::post('/v1/play/campaigns/{id}/scenes/{scene_id}/enter', $c('enterPlayCampaignScene'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_scene_close', self::post('/v1/play/campaigns/{id}/scenes/{scene_id}/close', $c('closePlayCampaignScene'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_locations_create', self::post('/v1/play/campaigns/{id}/locations', $c('createPlayCampaignLocation'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_connections_create', self::post('/v1/play/campaigns/{id}/locations/{from_id}/connections', $c('createPlayCampaignLocationConnection'), ['id' => '[^/]+', 'from_id' => '[^/]+']));
        $routes->add('play_campaigns_travel_read', self::get('/v1/play/campaigns/{id}/locations/{loc_id}/travel', $c('getPlayCampaignTravel'), ['id' => '[^/]+', 'loc_id' => '[^/]+']));
        $routes->add('play_campaigns_turn_travel', self::post('/v1/play/campaigns/{id}/turn/travel', $c('travelPlayCampaignTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_turn_rest', self::post('/v1/play/campaigns/{id}/turn/rest', $c('restPlayCampaignTurn'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_encounters_create', self::post('/v1/play/campaigns/{id}/encounters', $c('createPlayCampaignEncounter'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_monsters_add', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters', $c('addPlayCampaignMonster'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_monsters_remove', self::delete('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}', $c('removePlayCampaignMonster'), ['id' => '[^/]+', 'enc_id' => '[^/]+', 'monster_id' => '[^/]+']));
        $routes->add('play_campaigns_combatants_bind', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants', $c('bindPlayCampaignCombatant'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_combatants_unbind', self::delete('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}', $c('unbindPlayCampaignCombatant'), ['id' => '[^/]+', 'enc_id' => '[^/]+', 'member' => '[^/]+']));
        $routes->add('play_campaigns_encounter_turn_advance', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance', $c('advancePlayCampaignEncounterTurn'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_turn', self::get('/v1/play/campaigns/{id}/encounters/{enc_id}/turn', $c('getPlayCampaignEncounterTurn'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_condition', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/conditions', $c('addPlayCampaignEncounterCondition'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_status', self::get('/v1/play/campaigns/{id}/encounters/{enc_id}/status', $c('getPlayCampaignEncounterStatus'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_action', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/actions', $c('submitPlayCampaignEncounterAction'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_turn_delay', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay', $c('delayPlayCampaignEncounterTurn'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_turn_ready', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready', $c('readyPlayCampaignEncounterTurn'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_damage', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/damage', $c('damagePlayCampaignEncounter'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_heal', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/heal', $c('healPlayCampaignEncounter'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_rewards', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/rewards', $c('awardPlayCampaignEncounterRewards'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_close', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/close', $c('closePlayCampaignEncounter'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_encounter_end', self::post('/v1/play/campaigns/{id}/encounters/{enc_id}/end', $c('endPlayCampaignEncounter'), ['id' => '[^/]+', 'enc_id' => '[^/]+']));
        $routes->add('play_campaigns_character_damage', self::post('/v1/play/campaigns/{id}/characters/{char_id}/damage', $c('damagePlayCampaignCharacter'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_death_saves', self::post('/v1/play/campaigns/{id}/characters/{char_id}/death-saves', $c('recordDeathSave'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_status', self::get('/v1/play/campaigns/{id}/characters/{char_id}/status', $c('getPlayCampaignCharacterStatus'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_owner', self::get('/v1/play/campaigns/{id}/characters/{char_id}/owner', $c('getPlayCampaignCharacterOwner'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_claim', self::post('/v1/play/campaigns/{id}/characters/{char_id}/claim', $c('claimPlayCampaignCharacter'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_transfer', self::post('/v1/play/campaigns/{id}/characters/{char_id}/transfer', $c('transferPlayCampaignCharacter'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_build', self::post('/v1/play/campaigns/{id}/characters/{char_id}/build', $c('buildPlayCampaignCharacter'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_level_up', self::post('/v1/play/campaigns/{id}/characters/{char_id}/level-up', $c('levelUpPlayCampaignCharacter'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_skill_check', self::post('/v1/play/campaigns/{id}/characters/{char_id}/skill-check', $c('playCampaignCharacterSkillCheck'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_spells_add', self::post('/v1/play/campaigns/{id}/characters/{char_id}/spells', $c('addCharacterSpell'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_spells_get', self::get('/v1/play/campaigns/{id}/characters/{char_id}/spells', $c('getCharacterSpellbook'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_prepared_spells_update', self::put('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', $c('updateCharacterPreparedSpells'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_prepared_spells_get', self::get('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', $c('getCharacterPreparedSpells'), ['id' => '[^/]+', 'char_id' => '[^/]+']));
        $routes->add('play_campaigns_character_casts_create', self::post('/v1/play/campaigns/{id}/characters/{character_id}/casts', $c('castCharacterSpell'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_casts_get', self::get('/v1/play/campaigns/{id}/characters/{character_id}/casts', $c('getCharacterCasts'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_concentration_set', self::put('/v1/play/campaigns/{id}/characters/{character_id}/concentration', $c('setCharacterConcentration'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_concentration_get', self::get('/v1/play/campaigns/{id}/characters/{character_id}/concentration', $c('getCharacterConcentration'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_concentration_advance', self::post('/v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn', $c('advanceCharacterConcentrationTurn'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_concentration_clear', self::delete('/v1/play/campaigns/{id}/characters/{character_id}/concentration', $c('clearCharacterConcentration'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_inventory_add', self::post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', $c('addPlayCampaignCharacterInventoryItem'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_inventory_list', self::get('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', $c('getPlayCampaignCharacterInventoryItems'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_inventory_remove', self::delete('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}', $c('removePlayCampaignCharacterInventoryItem'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'item_id' => '[^/]+']));
        $routes->add('play_campaigns_character_equip', self::put('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', $c('equipPlayCampaignCharacterItem'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'slot' => '[^/]+']));
        $routes->add('play_campaigns_character_equipment_get', self::get('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', $c('getPlayCampaignCharacterEquipment'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'slot' => '[^/]+']));
        $routes->add('play_campaigns_character_attune', self::post('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune', $c('attunePlayCampaignCharacterItem'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'slot' => '[^/]+']));
        $routes->add('play_campaigns_character_consume', self::post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume', $c('consumePlayCampaignCharacterItem'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'item_id' => '[^/]+']));
        $routes->add('play_campaigns_character_currency_get', self::get('/v1/play/campaigns/{id}/characters/{character_id}/currency', $c('getCharacterCurrency'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_character_currency_transfer', self::post('/v1/play/campaigns/{id}/characters/{character_id}/currency/transfers', $c('transferCharacterCurrency'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_transactional_transfers_create', self::post('/v1/play/campaigns/{id}/transactional-transfers', $c('createTransactionalTransfer'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_transactional_transfers_read', self::get('/v1/play/campaigns/{id}/transactional-transfers', $c('getTransactionalTransfers'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_loot_create', self::post('/v1/play/campaigns/{id}/loot', $c('createPlayCampaignLoot'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_loot_vote', self::post('/v1/play/campaigns/{id}/loot/{loot_id}/votes', $c('votePlayCampaignLoot'), ['id' => '[^/]+', 'loot_id' => '[^/]+']));
        $routes->add('play_campaigns_loot_assign', self::post('/v1/play/campaigns/{id}/loot/{loot_id}/assign', $c('assignPlayCampaignLoot'), ['id' => '[^/]+', 'loot_id' => '[^/]+']));
        $routes->add('play_campaigns_loot_get', self::get('/v1/play/campaigns/{id}/loot/{loot_id}', $c('getPlayCampaignLoot'), ['id' => '[^/]+', 'loot_id' => '[^/]+']));
        $routes->add('play_campaigns_npcs_create', self::post('/v1/play/campaigns/{id}/npcs', $c('createPlayCampaignNpc'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_npcs_agenda_update', self::put('/v1/play/campaigns/{id}/npcs/{npc_id}/agenda', $c('updatePlayCampaignNpcAgenda'), ['id' => '[^/]+', 'npc_id' => '[^/]+']));
        $routes->add('play_campaigns_npcs_read', self::get('/v1/play/campaigns/{id}/npcs/{npc_id}', $c('getPlayCampaignNpc'), ['id' => '[^/]+', 'npc_id' => '[^/]+']));
        $routes->add('play_campaigns_factions_create', self::post('/v1/play/campaigns/{id}/factions', $c('createPlayCampaignFaction'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_reputation_change', self::post('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', $c('changePlayCampaignReputation'), ['id' => '[^/]+', 'faction_id' => '[^/]+']));
        $routes->add('play_campaigns_reputation_read', self::get('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', $c('getPlayCampaignReputation'), ['id' => '[^/]+', 'faction_id' => '[^/]+']));
        $routes->add('play_campaigns_npcs_dialogue_create', self::post('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', $c('addPlayCampaignNpcDialogue'), ['id' => '[^/]+', 'npc_id' => '[^/]+']));
        $routes->add('play_campaigns_npcs_dialogue_read', self::get('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', $c('getPlayCampaignNpcDialogue'), ['id' => '[^/]+', 'npc_id' => '[^/]+']));
        $routes->add('play_campaigns_relationships_create', self::post('/v1/play/campaigns/{id}/relationships', $c('createPlayCampaignRelationship'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_relationships_update', self::put('/v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}', $c('updatePlayCampaignRelationship'), ['id' => '[^/]+', 'source_id' => '[^/]+', 'target_id' => '[^/]+', 'kind' => '[^/]+']));
        $routes->add('play_campaigns_relationships_read', self::get('/v1/play/campaigns/{id}/relationships', $c('getPlayCampaignRelationships'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_clues_create', self::post('/v1/play/campaigns/{id}/clues', $c('createPlayCampaignClue'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_clues_read', self::get('/v1/play/campaigns/{id}/clues', $c('getPlayCampaignClues'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_quests_create', self::post('/v1/play/campaigns/{id}/quests', $c('createPlayCampaignQuest'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_quests_state_update', self::put('/v1/play/campaigns/{id}/quests/{quest_id}/state', $c('updatePlayCampaignQuestState'), ['id' => '[^/]+', 'quest_id' => '[^/]+']));
        $routes->add('play_campaigns_quests_read', self::get('/v1/play/campaigns/{id}/quests', $c('getPlayCampaignQuests'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_quests_rewards_configure', self::put('/v1/play/campaigns/{id}/quests/{quest_id}/rewards', $c('configurePlayCampaignQuestRewards'), ['id' => '[^/]+', 'quest_id' => '[^/]+']));
        $routes->add('play_campaigns_quests_rewards_award', self::post('/v1/play/campaigns/{id}/quests/{quest_id}/rewards/award', $c('awardPlayCampaignQuestRewards'), ['id' => '[^/]+', 'quest_id' => '[^/]+']));
        $routes->add('play_campaigns_character_rewards', self::get('/v1/play/campaigns/{id}/characters/{character_id}/rewards', $c('getPlayCampaignCharacterRewards'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_world_events_create', self::post('/v1/play/campaigns/{id}/world-events', $c('schedulePlayCampaignWorldEvent'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_world_events_resolve', self::post('/v1/play/campaigns/{id}/world-events/{event_id}/resolve', $c('resolvePlayCampaignWorldEvent'), ['id' => '[^/]+', 'event_id' => '[^/]+']));
        $routes->add('play_campaigns_world_events_read', self::get('/v1/play/campaigns/{id}/world-events', $c('getPlayCampaignWorldEvents'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_calendar_create', self::post('/v1/play/campaigns/{id}/calendar', $c('createPlayCampaignCalendar'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_calendar_read', self::get('/v1/play/campaigns/{id}/calendar', $c('getPlayCampaignCalendar'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_calendar_advance', self::post('/v1/play/campaigns/{id}/calendar/advance', $c('advancePlayCampaignCalendar'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_settlements_create', self::post('/v1/play/campaigns/{id}/settlements', $c('createPlayCampaignSettlement'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_settlements_update', self::put('/v1/play/campaigns/{id}/settlements/{settlement_id}', $c('updatePlayCampaignSettlement'), ['id' => '[^/]+', 'settlement_id' => '[^/]+']));
        $routes->add('play_campaigns_settlements_discover', self::post('/v1/play/campaigns/{id}/settlements/{settlement_id}/discover', $c('discoverPlayCampaignSettlement'), ['id' => '[^/]+', 'settlement_id' => '[^/]+']));
        $routes->add('play_campaigns_settlements_list', self::get('/v1/play/campaigns/{id}/settlements', $c('getPlayCampaignSettlements'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_shops_create', self::post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops', $c('createPlayCampaignShop'), ['id' => '[^/]+', 'settlement_id' => '[^/]+']));
        $routes->add('play_campaigns_shops_read', self::get('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}', $c('getPlayCampaignShop'), ['id' => '[^/]+', 'settlement_id' => '[^/]+', 'shop_id' => '[^/]+']));
        $routes->add('play_campaigns_shops_buy', self::post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy', $c('buyFromPlayCampaignShop'), ['id' => '[^/]+', 'settlement_id' => '[^/]+', 'shop_id' => '[^/]+']));
        $routes->add('play_campaigns_shops_sell', self::post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell', $c('sellToPlayCampaignShop'), ['id' => '[^/]+', 'settlement_id' => '[^/]+', 'shop_id' => '[^/]+']));
        $routes->add('play_campaigns_recipes_create', self::post('/v1/play/campaigns/{id}/recipes', $c('createPlayCampaignRecipe'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_recipes_list', self::get('/v1/play/campaigns/{id}/recipes', $c('listPlayCampaignRecipes'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_recipes_craft', self::post('/v1/play/campaigns/{id}/recipes/{recipe_id}/craft', $c('craftPlayCampaignRecipe'), ['id' => '[^/]+', 'recipe_id' => '[^/]+']));
        $routes->add('play_campaigns_downtime_activities_create', self::post('/v1/play/campaigns/{id}/downtime/activities', $c('createPlayCampaignDowntimeActivity'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_downtime_allocations_create', self::post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations', $c('createPlayCampaignDowntimeAllocation'), ['id' => '[^/]+', 'character_id' => '[^/]+']));
        $routes->add('play_campaigns_downtime_allocations_progress', self::post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress', $c('progressPlayCampaignDowntimeAllocation'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'activity_id' => '[^/]+']));
        $routes->add('play_campaigns_downtime_allocations_read', self::get('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}', $c('getPlayCampaignDowntimeAllocation'), ['id' => '[^/]+', 'character_id' => '[^/]+', 'activity_id' => '[^/]+']));
        $routes->add('play_campaigns_notes_create', self::post('/v1/play/campaigns/{id}/notes', $c('createPlayCampaignNote'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_notes_list', self::get('/v1/play/campaigns/{id}/notes', $c('getPlayCampaignNotes'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_notes_read', self::get('/v1/play/campaigns/{id}/notes/{note_id}', $c('getPlayCampaignNote'), ['id' => '[^/]+', 'note_id' => '[^/]+']));
        $routes->add('play_campaigns_notes_update', self::put('/v1/play/campaigns/{id}/notes/{note_id}', $c('updatePlayCampaignNote'), ['id' => '[^/]+', 'note_id' => '[^/]+']));
        $routes->add('play_campaigns_whispers_create', self::post('/v1/play/campaigns/{id}/whispers', $c('createPlayCampaignWhisper'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_whispers_list', self::get('/v1/play/campaigns/{id}/whispers', $c('getPlayCampaignWhispers'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_messages_create', self::post('/v1/play/campaigns/{id}/messages', $c('createPlayCampaignMessage'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_messages_list', self::get('/v1/play/campaigns/{id}/messages', $c('getPlayCampaignMessages'), ['id' => '[^/]+']));
        $routes->add('play_campaigns_character_sheet', self::get('/v1/play/campaigns/{id}/characters/{character_id}/sheet', $c('getPlayCampaignCharacterSheet'), ['id' => '[^/]+', 'character_id' => '[^/]+']));

        return $routes;
    }

    private static function get(string $path, callable $controller, array $requirements = []): Route
    {
        return self::route($path, $controller, ['GET'], $requirements);
    }

    private static function post(string $path, callable $controller, array $requirements = []): Route
    {
        return self::route($path, $controller, ['POST'], $requirements);
    }

    private static function put(string $path, callable $controller, array $requirements = []): Route
    {
        return self::route($path, $controller, ['PUT'], $requirements);
    }

    private static function delete(string $path, callable $controller, array $requirements = []): Route
    {
        return self::route($path, $controller, ['DELETE'], $requirements);
    }

    private static function route(string $path, callable $controller, array $methods, array $requirements = []): Route
    {
        return new Route($path, ['_controller' => $controller], $requirements, [], '', [], $methods);
    }
}
